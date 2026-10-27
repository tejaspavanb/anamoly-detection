import copy
import os
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from agent import diagnose
from chat import answer as chat_answer
from data_collector import SERVICES, collect_services, feature_vector, find_service, recent_log_lines
from model import build_model
from snapshot import render_snapshot

FAULT_LABELS = {
    "latency": "latency spike",
    "errors": "error storm",
    "timeout": "handler timeout",
    "crash": "crash",
    "none": "restore",
}
ACTIVE_PHASES = {"watching", "analyzing", "repairing", "verifying", "ready", "needs_key", "ai_error", "still_unhealthy"}

model = build_model()
lock = threading.Lock()
state = {
    "latest": None,
    "history": [],
    "timeline": [],
    "events": [],
    "incident": None,
    "snapshot": None,
    "snapshot_for": None,
    "busy": False,
    "seq": 0,
    "seen_up": False,
    "cooldown_until": 0.0,
    "auto_repair": True,
}


def iso_now():
    return datetime.now(timezone.utc).isoformat()


def push_event(level, message):
    state["events"].append({"ts": iso_now(), "level": level, "message": message})
    del state["events"][:-80]


def public_settings():
    model_name = os.environ.get("GROQ_MODEL", "qwen/qwen3.8-27b")
    return {
        "has_key": bool(os.environ.get("GROQ_API_KEY", "").strip()),
        "auto_repair": state["auto_repair"],
        "model": model_name,
    }


def score_services(services):
    ready = all(service["reachable"] for service in services)
    if ready:
        state["seen_up"] = True
    vector = feature_vector(services)
    enough = ready and min(service["requests"] for service in services) >= 4
    score = float(model.score(vector)[0]) if enough else 0.0
    root, scores = model.attribute(vector) if enough else (None, {})
    anomaly = bool(enough and score > model.threshold)
    if state["seen_up"] and any(not service["reachable"] for service in services):
        anomaly = True
        down = [service["name"] for service in services if not service["reachable"]]
        root = down[0]
        for name in down:
            scores[name] = max(scores.get(name, 0.0), 1.0)
    return {
        "services": services,
        "score": score,
        "threshold": float(model.threshold),
        "anomaly": anomaly,
        "attribution": {"service": root, "scores": scores},
        "enough": enough,
        "ready": ready,
        "log_lines": recent_log_lines(services),
    }


def blank_incident():
    state["seq"] += 1
    state["snapshot"] = None
    state["snapshot_for"] = None
    return {
        "id": f"inc-{state['seq']}",
        "phase": "watching",
        "started_at": iso_now(),
        "since": time.time(),
        "analysis_ready": False,
        "root_cause_service": None,
        "fault_type": None,
        "confidence": None,
        "summary": "",
        "evidence": [],
        "suggestions": [],
        "repair": None,
        "repair_applied": False,
        "error": None,
        "model": None,
        "used_image": False,
    }


def apply_plan(plan):
    repair = plan.get("repair") or {}
    action = repair.get("action")
    service = find_service(repair.get("service") or "")
    if action not in {"clear_fault", "restart"} or not service:
        return {"applied": False, "detail": "no automatic repair"}
    response = requests.post(
        f"{service['url']}/api/repair",
        json={"action": "restart" if action == "restart" else "clear"},
        timeout=3,
    )
    response.raise_for_status()
    return {"applied": True, "service": service["name"], "action": action}


def analyze_job(apply):
    try:
        with lock:
            snapshot = copy.deepcopy(state["latest"])
            incident = state["incident"]
            if snapshot is None or incident is None:
                return
            incident["phase"] = "analyzing"
        image = render_snapshot(snapshot)
        plan = diagnose(snapshot, image)
        with lock:
            if state["incident"] is not incident:
                return
            incident["analysis_ready"] = True
            incident["root_cause_service"] = plan["root_cause_service"]
            incident["fault_type"] = plan["fault_type"]
            incident["confidence"] = plan["confidence"]
            incident["summary"] = plan["summary"]
            incident["evidence"] = plan["evidence"]
            incident["suggestions"] = plan["suggestions"]
            incident["repair"] = plan["repair"]
            incident["model"] = plan["model"]
            incident["used_image"] = plan["used_image"]
            incident["error"] = None
            state["snapshot"] = image
            state["snapshot_for"] = incident["id"]
            push_event("ai", f"Groq ({plan['model']}) points at {plan['root_cause_service'] or 'no service'}")
        should_apply = apply and plan["repair"]["action"] in {"clear_fault", "restart"}
        if should_apply:
            with lock:
                if state["incident"] is not incident:
                    return
                incident["phase"] = "repairing"
            result = apply_plan(plan)
            with lock:
                if state["incident"] is not incident:
                    return
                incident["repair_applied"] = result.get("applied", False)
                incident["phase"] = "verifying" if result.get("applied") else "ready"
                incident["repaired_at"] = time.time()
                state["cooldown_until"] = time.time() + 8
                if result.get("applied"):
                    push_event("repair", f"applied {result['action']} on {result['service']}")
                else:
                    push_event("ai", result.get("detail") or "repair skipped")
        else:
            with lock:
                incident["phase"] = "ready"
    except Exception as exc:
        with lock:
            if state["incident"] is not None:
                state["incident"]["phase"] = "needs_key" if "missing Groq" in str(exc) else "ai_error"
                state["incident"]["error"] = str(exc)
            push_event("error", str(exc)[:180])
    finally:
        with lock:
            state["busy"] = False


def start_analysis(apply):
    if state["busy"] or state["latest"] is None:
        return False
    if state["incident"] is None or state["incident"]["phase"] == "resolved":
        state["incident"] = blank_incident()
    state["busy"] = True
    threading.Thread(target=analyze_job, args=(apply,), daemon=True).start()
    return True


def tick():
    snapshot = score_services(collect_services())
    with lock:
        state["latest"] = snapshot
        if snapshot["enough"] or snapshot["anomaly"]:
            state["history"].append(round(snapshot["score"], 5))
            del state["history"][:-60]
        state["timeline"].append({
            "ts": iso_now(),
            "anomaly": bool(snapshot["anomaly"]),
            "score": round(float(snapshot["score"]), 5),
            "services": [
                {
                    "name": service["name"],
                    "status": "down" if not service.get("reachable") else (service.get("status") or "down"),
                    "latency": round(float(service.get("avg_latency_ms") or 0), 1),
                    "error_rate": round(float(service.get("error_rate") or 0), 3),
                    "rps": round(float(service.get("rps") or 0), 2),
                }
                for service in snapshot["services"]
            ],
        })
        del state["timeline"][:-180]
        incident = state["incident"]
        now = time.time()
        if incident and incident["phase"] == "watching" and not snapshot["anomaly"]:
            state["incident"] = None
            incident = None
        elif incident and incident["phase"] == "verifying":
            age = now - incident.get("repaired_at", now)
            if snapshot["enough"] and not snapshot["anomaly"] and age > 2:
                incident["phase"] = "resolved"
                push_event("ok", "autoencoder back under the threshold")
            elif age > 12 and snapshot["anomaly"]:
                incident["phase"] = "still_unhealthy"
                push_event("error", "repair ran and the score is still high")
        active = incident is not None and incident["phase"] in ACTIVE_PHASES
        if snapshot["anomaly"] and not active and now >= state["cooldown_until"] and not state["busy"]:
            state["incident"] = blank_incident()
            push_event("ai", "anomaly crossed the autoencoder threshold")
            incident = state["incident"]
        if (
            incident
            and incident["phase"] == "watching"
            and now - incident["since"] >= 3
            and not state["busy"]
        ):
            if not public_settings()["has_key"]:
                incident["phase"] = "needs_key"
                push_event("ai", "add a Groq key to diagnose this window")
            else:
                start_analysis(state["auto_repair"])


def traffic_loop():
    url = f"{SERVICES[0]['url']}/api/work"
    while True:
        try:
            requests.get(url, timeout=5)
        except requests.RequestException:
            pass
        time.sleep(0.25)


def watcher():
    while True:
        try:
            tick()
        except Exception as exc:
            print("tick failed", exc)
        time.sleep(1)


@asynccontextmanager
async def lifespan(_app):
    threading.Thread(target=traffic_loop, daemon=True).start()
    threading.Thread(target=watcher, daemon=True).start()
    yield


app = FastAPI(title="Microservice Anomaly Detection", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class FaultIn(BaseModel):
    service: str
    mode: str


class SettingsIn(BaseModel):
    groq_api_key: str | None = None
    auto_repair: bool | None = None
    model: str | None = None


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatIn(BaseModel):
    messages: list[ChatMessage]


def mutate_services(service_name, mode, source="operator"):
    if mode not in FAULT_LABELS:
        raise HTTPException(status_code=400, detail="unknown mode")
    targets = SERVICES if service_name == "all" else [find_service(service_name)]
    if not targets or targets[0] is None:
        raise HTTPException(status_code=404, detail="unknown service")
    try:
        for service in targets:
            if mode == "none":
                response = requests.post(f"{service['url']}/api/repair", json={"action": "clear"}, timeout=3)
            else:
                response = requests.post(f"{service['url']}/api/fault", json={"mode": mode}, timeout=3)
            response.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"service unreachable: {exc}") from exc
    with lock:
        label = FAULT_LABELS[mode]
        names = "all services" if service_name == "all" else service_name
        who = "chat" if source == "chat" else "operator"
        push_event("fault" if mode != "none" else "ok", f"{who}: {label} on {names}")
        if mode == "none" and state["incident"] and state["incident"]["phase"] != "resolved":
            state["incident"]["phase"] = "resolved"
            state["cooldown_until"] = time.time() + 8
        elif mode != "none":
            state["incident"] = None
            state["snapshot"] = None
            state["cooldown_until"] = 0
    return {"ok": True, "service": service_name, "mode": mode}


def overview_payload():
    latest = state["latest"] or {
        "services": [],
        "score": 0,
        "threshold": float(model.threshold),
        "anomaly": False,
        "attribution": {"service": None, "scores": {}},
        "ready": False,
    }
    incident = state["incident"]
    public_incident = None
    if incident:
        public_incident = {key: value for key, value in incident.items() if key not in {"since", "repaired_at"}}
    return {
        "services": latest["services"],
        "score": latest["score"],
        "threshold": latest["threshold"],
        "anomaly": latest["anomaly"],
        "attribution": latest["attribution"],
        "ready": latest["ready"],
        "history": list(state["history"]),
        "timeline": list(state["timeline"]),
        "events": list(state["events"]),
        "incident": public_incident,
        "settings": public_settings(),
    }


@app.get("/api/health")
def health():
    return {"ok": True, "threshold": model.threshold}


@app.get("/api/overview")
def overview():
    with lock:
        return overview_payload()


@app.get("/api/ai/snapshot")
def ai_snapshot():
    with lock:
        incident = state["incident"]
        if not incident or state["snapshot_for"] != incident.get("id"):
            return {"image": None}
        return {"image": state["snapshot"]}


@app.post("/api/faults")
def inject_fault(body: FaultIn):
    return mutate_services(body.service, body.mode)


@app.post("/api/chat")
def chat(body: ChatIn):
    with lock:
        snapshot = copy.deepcopy(state["latest"]) or {
            "services": [],
            "score": 0,
            "threshold": float(model.threshold),
            "anomaly": False,
            "attribution": {"service": None, "scores": {}},
            "log_lines": [],
        }
        incident = state["incident"]
        public_incident = None
        if incident:
            public_incident = {key: value for key, value in incident.items() if key not in {"since", "repaired_at"}}
    messages = [{"role": item.role, "content": item.content} for item in body.messages][-8:]
    result = chat_answer(messages, snapshot, public_incident)
    for action in result.get("actions") or []:
        action["applied"] = False
        if not action.get("apply"):
            continue
        service_name = "all" if action.get("type") == "restore_all" else action.get("service")
        try:
            mutate_services(service_name, "none", source="chat")
        except HTTPException as exc:
            result["reply"] = result["reply"].rstrip() + f" Could not restore {service_name}: {exc.detail}."
            continue
        action["applied"] = True
    return result


@app.post("/api/settings")
def update_settings(body: SettingsIn):
    with lock:
        if body.groq_api_key is not None:
            os.environ["GROQ_API_KEY"] = body.groq_api_key.strip()
            push_event("ai", "Groq key saved for this session" if body.groq_api_key.strip() else "Groq key cleared")
        if body.auto_repair is not None:
            state["auto_repair"] = body.auto_repair
        if body.model:
            os.environ["GROQ_MODEL"] = body.model.strip()
        incident = state["incident"]
        should_run = incident and incident["phase"] == "needs_key" and public_settings()["has_key"]
        if should_run:
            start_analysis(state["auto_repair"])
        return public_settings()


@app.post("/api/ai/analyze")
def analyze_now():
    with lock:
        if not public_settings()["has_key"]:
            raise HTTPException(status_code=400, detail="Add a Groq API key first")
        if not start_analysis(state["auto_repair"]):
            raise HTTPException(status_code=409, detail="analysis already running")
        push_event("ai", "operator asked Groq to read the console")
    return {"ok": True}


@app.post("/api/ai/repair")
def repair_now():
    with lock:
        incident = state["incident"]
        plan = None if not incident else {
            "repair": incident.get("repair") or {"action": "none", "service": None},
        }
        if not incident or not incident.get("analysis_ready"):
            raise HTTPException(status_code=400, detail="no diagnosis to apply")
        incident["phase"] = "repairing"
    try:
        result = apply_plan(plan)
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    with lock:
        if state["incident"]:
            state["incident"]["repair_applied"] = result.get("applied", False)
            state["incident"]["phase"] = "verifying" if result.get("applied") else "ready"
            state["incident"]["repaired_at"] = time.time()
            state["cooldown_until"] = time.time() + 8
        if result.get("applied"):
            push_event("repair", f"applied {result['action']} on {result['service']}")
        else:
            push_event("ai", "model did not recommend an automatic repair")
    return result

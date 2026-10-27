import json
import os
import re

import requests

from data_collector import SERVICES, recent_log_lines

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
TEXT_FALLBACK = "openai/gpt-oss-20b"

SYSTEM = """You are the on-call engineer for a local three-service demo.
Call chain: frontend-service:3000 -> backend-service:3001 -> payment-service:3002.
You receive metrics, service logs, and a console snapshot image.
Diagnose the failing service from those symptoms. Do not claim a service failed unless the logs or metrics support it.
The only safe automatic repairs are clear_fault and restart, which put that service back into a healthy mode.
Return JSON only with this shape:
{"root_cause_service":"payment-service","fault_type":"errors|latency|timeout|crash|unknown","confidence":0-100,"summary":"two sentences","evidence":["short cite","short cite"],"suggestions":["operator step","operator step","operator step"],"repair":{"action":"clear_fault|restart|none","service":"payment-service","reason":"short"}}
Use clear_fault or restart when a service is unhealthy and a reset would restore traffic. Use none when the system is healthy."""


def _canonical(value):
    if not value:
        return None
    compact = re.sub(r"[^a-z]", "", str(value).lower())
    aliases = (
        ("paymentservice", "payment-service"),
        ("backendservice", "backend-service"),
        ("frontendservice", "frontend-service"),
        ("payment", "payment-service"),
        ("backend", "backend-service"),
        ("frontend", "frontend-service"),
        ("gateway", "frontend-service"),
    )
    for alias, name in aliases:
        if alias in compact:
            return name
    known = {service["name"] for service in SERVICES}
    return value if value in known else None


def _message_text(message):
    chunks = []
    content = message.get("content")
    if isinstance(content, str):
        chunks.append(content)
    elif isinstance(content, list):
        for part in content:
            if isinstance(part, str):
                chunks.append(part)
            elif isinstance(part, dict):
                chunks.append(part.get("text") or "")
    for key in ("reasoning", "reasoning_content"):
        if isinstance(message.get(key), str):
            chunks.append(message[key])
    return "\n".join(chunks)


def _extract_json(text):
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end < start:
        raise ValueError("model did not return JSON")
    return json.loads(cleaned[start:end + 1])


def _normalize(data, model, used_image):
    repair = data.get("repair") if isinstance(data.get("repair"), dict) else {}
    service = _canonical(repair.get("service")) or _canonical(data.get("root_cause_service"))
    action = repair.get("action") if repair.get("action") in {"clear_fault", "restart", "none"} else "none"
    if action != "none" and not service:
        action = "none"
    confidence = data.get("confidence") or 0
    try:
        confidence = max(0, min(100, float(confidence)))
    except (TypeError, ValueError):
        confidence = 0
    evidence = data.get("evidence") if isinstance(data.get("evidence"), list) else []
    suggestions = data.get("suggestions") if isinstance(data.get("suggestions"), list) else []
    return {
        "root_cause_service": _canonical(data.get("root_cause_service")) or service,
        "fault_type": str(data.get("fault_type") or "unknown"),
        "confidence": confidence,
        "summary": str(data.get("summary") or "").strip(),
        "evidence": [str(item) for item in evidence][:4],
        "suggestions": [str(item) for item in suggestions][:4],
        "repair": {
            "action": action,
            "service": service,
            "reason": str(repair.get("reason") or "").strip(),
        },
        "model": model,
        "used_image": used_image,
    }


def _prompt(snapshot):
    metric_rows = []
    for service in snapshot["services"]:
        metric_rows.append(
            f"- {service['name']} status={service['status']} reachable={service['reachable']} "
            f"latency_ms={service['avg_latency_ms']:.0f} error_rate={service['error_rate']:.2f} "
            f"rps={service['rps']:.2f} requests={service['requests']}"
        )
    attribution = snapshot.get("attribution") or {}
    return "\n".join([
        "Autoencoder flagged this window." if snapshot.get("anomaly") else "Autoencoder says this window is inside normal range.",
        f"Reconstruction error {snapshot.get('score', 0):.4f} vs threshold {snapshot.get('threshold', 0):.4f}.",
        f"Per-service reconstruction error: {json.dumps(attribution.get('scores') or {})}.",
        "Metrics:",
        *metric_rows,
        "Logs:",
        *(snapshot.get("log_lines") or ["(no logs yet)"]),
        "The attached image is the same console: latency, error, and rate bars plus those logs.",
    ])


def _chat(model, content, api_key, json_mode=True):
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": content},
        ],
        "temperature": 0.2,
        "max_completion_tokens": 900,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    response = requests.post(
        GROQ_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=body,
        timeout=60,
    )
    if response.status_code == 400 and json_mode:
        return _chat(model, content, api_key, json_mode=False)
    if response.status_code >= 400:
        raise RuntimeError(f"Groq {response.status_code}: {response.text[:280]}")
    payload = response.json()
    message = payload["choices"][0]["message"]
    return _normalize(_extract_json(_message_text(message)), model, used_image=isinstance(content, list))


def canonical_service(value):
    return _canonical(value)


def complete(system, messages):
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("missing Groq API key")
    preferred = os.environ.get("GROQ_MODEL", "").strip() or TEXT_FALLBACK
    models = []
    for name in (preferred, TEXT_FALLBACK):
        if name not in models:
            models.append(name)
    errors = []
    for model in models:
        try:
            return _complete_once(model, system, messages, api_key)
        except Exception as exc:
            errors.append(str(exc))
    raise RuntimeError(errors[-1] if errors else "Groq request failed")


def _complete_once(model, system, messages, api_key, json_mode=True):
    body = {
        "model": model,
        "messages": [{"role": "system", "content": system}, *messages],
        "temperature": 0.3,
        "max_completion_tokens": 700,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    response = requests.post(
        GROQ_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=body,
        timeout=60,
    )
    if response.status_code == 400 and json_mode:
        return _complete_once(model, system, messages, api_key, json_mode=False)
    if response.status_code >= 400:
        raise RuntimeError(f"Groq {response.status_code}: {response.text[:280]}")
    message = response.json()["choices"][0]["message"]
    return _message_text(message)


def diagnose(snapshot, image_data_url):
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("missing Groq API key")
    if not snapshot.get("log_lines"):
        snapshot = {**snapshot, "log_lines": recent_log_lines(snapshot["services"])}
    vision_model = os.environ.get("GROQ_MODEL", "qwen/qwen3.8-27b").strip() or "qwen/qwen3.8-27b"
    text = _prompt(snapshot)
    vision_content = [
        {"type": "text", "text": text},
        {"type": "image_url", "image_url": {"url": image_data_url}},
    ]
    errors = []
    for model, content in ((vision_model, vision_content), (TEXT_FALLBACK, text)):
        try:
            return _chat(model, content, api_key)
        except Exception as exc:
            errors.append(str(exc))
    raise RuntimeError(errors[-1] if errors else "Groq request failed")

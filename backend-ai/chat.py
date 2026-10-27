import os
import re

from agent import canonical_service, complete, _extract_json

CHAT_SYSTEM = """You are the operator's assistant for a local three-service demo.
Call chain: frontend-service:3000 -> backend-service:3001 -> payment-service:3002.
Explain the live window in plain language, using the metrics and logs you are given.
You can recommend a restore, which clears a bad mode and lets the process accept traffic again.
Return JSON only:
{"reply":"short explanation","actions":[{"type":"restore","service":"payment-service","label":"Restore payment","apply":false}]}
type is restore or restore_all. apply is true only when the user asked to fix, resolve, repair, restore, or clear.
Do not set apply on a question. Use an empty actions list when the system is healthy and nothing needs a restore."""

FAULT_EXPLAIN = {
    "errors": "is failing most calls (error storm)",
    "latency": "is holding each request for about 1.6 seconds",
    "timeout": "is stalling past the caller's deadline",
    "crash": "is refusing traffic",
}


def _wants_fix(text):
    cleaned = " ".join(str(text).lower().split())
    if cleaned.startswith("how ") or cleaned.startswith("why ") or cleaned.startswith("what "):
        return False
    return any(word in cleaned for word in ("fix", "resolve", "repair", "restore", "clear", "heal"))


def _service_label(name):
    return (name or "").replace("-service", "")


def describe(snapshot, incident):
    services = snapshot.get("services") or []
    score = float(snapshot.get("score") or 0)
    threshold = float(snapshot.get("threshold") or 0)
    suspect = None
    if incident and incident.get("root_cause_service"):
        suspect = incident["root_cause_service"]
    elif snapshot.get("attribution"):
        suspect = (snapshot.get("attribution") or {}).get("service")
    faulty = [service for service in services if service.get("fault") not in (None, "none", "")]
    parts = []
    if snapshot.get("anomaly"):
        parts.append(f"Reconstruction error is {score:.4f}, above the threshold {threshold:.4f}.")
    else:
        parts.append(f"Reconstruction error is {score:.4f}, under the threshold {threshold:.4f}.")
    for service in faulty:
        reason = FAULT_EXPLAIN.get(service["fault"], f"is in {service['fault']} mode")
        parts.append(
            f"{service['name']} {reason}. "
            f"Latency {service['avg_latency_ms']:.0f} ms, "
            f"errors {service['error_rate'] * 100:.0f}%, "
            f"{service['rps']:.1f} requests/s."
        )
    if suspect and snapshot.get("anomaly"):
        parts.append(f"The strongest signal is {suspect}. Calls ahead of it fail when it does.")
    errors = [line for line in (snapshot.get("log_lines") or []) if " ERROR " in f" {line}"]
    if suspect:
        # Log shape is "hh:mm:ss LEVEL service message"; upstream lines also name the callee.
        owned = [line for line in errors if len(line.split()) > 2 and line.split()[2] == suspect]
        if owned:
            errors = owned
    if errors:
        parts.append(f"Latest error log: {errors[-1]}")
    if incident and incident.get("summary"):
        parts.append(incident["summary"])
    return " ".join(parts), suspect, faulty


def _actions_for(faulty, suspect, apply):
    if faulty:
        actions = [
            {
                "type": "restore",
                "service": service["name"],
                "label": f"Restore {_service_label(service['name'])}",
                "apply": apply and len(faulty) == 1,
            }
            for service in faulty
        ]
        if len(faulty) > 1:
            actions.append({"type": "restore_all", "service": "all", "label": "Restore all", "apply": apply})
        return actions
    if apply and suspect:
        return [{
            "type": "restore",
            "service": suspect,
            "label": f"Restore {_service_label(suspect)}",
            "apply": True,
        }]
    if suspect:
        return [{
            "type": "restore",
            "service": suspect,
            "label": f"Restore {_service_label(suspect)}",
            "apply": False,
        }]
    return []


def _local_answer(user_text, snapshot, incident):
    summary, suspect, faulty = describe(snapshot, incident)
    apply = _wants_fix(user_text)
    actions = _actions_for(faulty, suspect if snapshot.get("anomaly") else None, apply)
    if not snapshot.get("anomaly") and not faulty:
        reply = summary + " Nothing needs a restore right now."
        return {"reply": reply, "actions": []}
    if apply and actions:
        names = ", ".join(action["label"].replace("Restore ", "") for action in actions if action["apply"])
        reply = summary + f" I am restoring {names}."
    else:
        reply = summary + " Use the restore button on the service that is actually failing, not the one that only reports the error."
    return {"reply": reply, "actions": actions}


def _groq_answer(messages, snapshot, incident):
    summary, _, _ = describe(snapshot, incident)
    metrics = []
    for service in snapshot.get("services") or []:
        metrics.append(
            f"- {service['name']} fault={service.get('fault') or 'none'} "
            f"latency_ms={service.get('avg_latency_ms', 0):.0f} "
            f"error_rate={service.get('error_rate', 0):.2f} rps={service.get('rps', 0):.2f}"
        )
    context = "\n".join([summary, "Metrics:", *metrics, "Logs:", *(snapshot.get("log_lines") or ["(none)"])[-12:]])
    transcript = [{"role": "user", "content": "Live console:\n" + context}]
    for message in messages[-8:]:
        role = "assistant" if message.get("role") == "assistant" else "user"
        content = str(message.get("content") or "").strip()[:2000]
        if content:
            transcript.append({"role": role, "content": content})
    raw = complete(CHAT_SYSTEM, transcript)
    data = _extract_json(raw)
    reply = str(data.get("reply") or "").strip() or summary
    actions = []
    for item in data.get("actions") or []:
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        if kind == "restore_all":
            actions.append({
                "type": "restore_all",
                "service": "all",
                "label": "Restore all",
                "apply": bool(item.get("apply")),
            })
            continue
        service = canonical_service(item.get("service"))
        if kind == "restore" and service:
            actions.append({
                "type": "restore",
                "service": service,
                "label": f"Restore {service.replace('-service', '')}",
                "apply": bool(item.get("apply")),
            })
    return {"reply": reply, "actions": actions}


def answer(messages, snapshot, incident):
    user_text = ""
    for message in reversed(messages):
        if message.get("role") == "user":
            user_text = message.get("content") or ""
            break
    if not os.environ.get("GROQ_API_KEY", "").strip():
        result = _local_answer(user_text, snapshot, incident)
        result["source"] = "metrics"
        return result
    try:
        result = _groq_answer(messages, snapshot, incident)
        result["source"] = "groq"
        return result
    except Exception as exc:
        result = _local_answer(user_text, snapshot, incident)
        result["source"] = "metrics"
        detail = re.sub(r"\s+", " ", str(exc))[:180]
        result["reply"] = f"{result['reply']} Groq did not answer ({detail}), so this is from the live metrics."
        return result

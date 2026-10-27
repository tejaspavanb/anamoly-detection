import os
from concurrent.futures import ThreadPoolExecutor

import requests

LATENCY_CAP = 2000.0
RPS_CAP = 6.0


def load_dotenv():
    path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env"))
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_dotenv()

SERVICES = [
    {"name": "frontend-service", "port": 3000, "url": os.getenv("FRONTEND_URL", "http://127.0.0.1:3000")},
    {"name": "backend-service", "port": 3001, "url": os.getenv("BACKEND_URL", "http://127.0.0.1:3001")},
    {"name": "payment-service", "port": 3002, "url": os.getenv("PAYMENT_URL", "http://127.0.0.1:3002")},
]

_session = requests.Session()
_pool = ThreadPoolExecutor(max_workers=3)


def _blank(service):
    return {
        "name": service["name"],
        "port": service["port"],
        "reachable": False,
        "status": "down",
        "fault": "none",
        "uptime_s": 0,
        "requests": 0,
        "error_rate": 1.0,
        "avg_latency_ms": 0.0,
        "rps": 0.0,
        "logs": [],
    }


def _fetch(service):
    try:
        response = _session.get(f"{service['url']}/api/metrics", timeout=1.5)
        response.raise_for_status()
        payload = response.json()
        payload["name"] = service["name"]
        payload["port"] = service["port"]
        payload["reachable"] = True
        payload["logs"] = payload.get("logs") or []
        return payload
    except requests.RequestException:
        return _blank(service)


def feature_vector(services):
    vector = []
    for service in services:
        if service["reachable"]:
            vector.extend([
                min(1.0, max(0.0, service["avg_latency_ms"] / LATENCY_CAP)),
                min(1.0, max(0.0, service["error_rate"])),
                min(1.0, max(0.0, service["rps"] / RPS_CAP)),
            ])
        else:
            vector.extend([1.0, 1.0, 0.0])
    return vector


def collect_services():
    return list(_pool.map(_fetch, SERVICES))


def recent_log_lines(services, limit=18):
    rows = []
    for service in services:
        rows.extend(service.get("logs") or [])
    rows.sort(key=lambda entry: entry.get("ts") or "")
    errors = [row for row in rows if row.get("level") in {"error", "warn"}]
    chosen = errors[-limit:] if len(errors) >= 6 else rows[-limit:]
    lines = []
    for entry in chosen:
        clock = (entry.get("ts") or "")[11:19]
        level = (entry.get("level") or "info").upper()
        lines.append(f"{clock} {level} {entry.get('service')} {entry.get('message')}")
    return lines


def find_service(name):
    for service in SERVICES:
        if service["name"] == name:
            return service
    return None

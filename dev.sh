#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

if [[ ! -d node_modules/express ]]; then
  npm install
fi
if [[ ! -d dashboard/node_modules ]]; then
  (cd dashboard && npm install)
fi
if [[ ! -x backend-ai/.venv/bin/uvicorn ]]; then
  python3 -m venv backend-ai/.venv
  backend-ai/.venv/bin/pip install -r backend-ai/requirements.txt
fi

pids=()
cleanup() {
  for pid in "${pids[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
}
trap cleanup EXIT INT TERM

(cd payment-service && exec node index.js) &
pids+=($!)
(cd backend-service && exec node index.js) &
pids+=($!)
(cd frontend-service && exec node index.js) &
pids+=($!)
(cd backend-ai && exec .venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000) &
pids+=($!)
(cd dashboard && exec ./node_modules/.bin/vite --host 127.0.0.1 --port 5173) &
pids+=($!)

echo "Dashboard   http://127.0.0.1:5173"
echo "Frontend    http://127.0.0.1:3000"
echo "Backend     http://127.0.0.1:3001"
echo "Payment     http://127.0.0.1:3002"
echo "AI API      http://127.0.0.1:8000"

while true; do
  for pid in "${pids[@]}"; do
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "process $pid exited"
      exit 1
    fi
  done
  sleep 1
done

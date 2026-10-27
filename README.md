# Microservice anomaly detection

Live console for a three-service chain. The dashboard shows each process, its port, and its logs. Inject a failure, and an autoencoder scores the traffic. Groq then reads the metrics, the logs, and a snapshot of the console, names the failing service, and can repair it.

```
frontend-service :3000  →  backend-service :3001  →  payment-service :3002
```

## Run

```bash
cp .env.example .env   # optional, or paste the key in the dashboard
npm run dev
```

Open http://127.0.0.1:5173. A Groq key from https://console.groq.com/keys (free tier) unlocks the multimodal diagnosis. The autoencoder still scores traffic without it. The key can live in `.env` as `GROQ_API_KEY`, or be pasted into the dashboard for the current session.

Default model is `qwen/qwen3.8-27b` (vision). Set `GROQ_MODEL` to override it.

## What to try

1. Wait until all three terminals show `listening` and request lines.
2. Choose a service and inject an error storm, latency spike, timeout, or crash.
3. Watch the score cross the threshold. With auto-repair on, Groq diagnoses the window and clears the fault. Turn auto-repair off to read the suggestions and apply the repair yourself.
4. Use the chat on the right to ask why the window looks wrong. "Resolve it" restores the service that is failing. Each inject and restore button runs on its own, so one request does not freeze the others.

Each service also has its own page on its port (`http://127.0.0.1:3001`).

`docker compose up --build` runs the same stack. `docker compose --profile tracing up` adds Jaeger, Prometheus, and the OpenTelemetry collector from the original setup. Day-to-day tracing in this demo is the trace id stamped on each log line.

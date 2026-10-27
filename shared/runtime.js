const express = require('express');
const http = require('http');
const crypto = require('crypto');

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const CALL_TIMEOUT_MS = 3000;

function createService({ name, port, downstream }) {
  const app = express();
  app.use(express.json());
  const logs = [];
  const samples = [];
  let fault = { mode: 'none' };
  const started = Date.now();

  function log(level, message, extra = {}) {
    const entry = {
      ts: new Date().toISOString(),
      level,
      service: name,
      message,
      trace: extra.trace || null,
    };
    logs.push(entry);
    if (logs.length > 400) logs.shift();
    console.log(`[${entry.ts}] ${level.toUpperCase()} ${name} ${message}`);
  }

  function record(ok, ms, status) {
    samples.push({ ts: Date.now(), ok, ms, status });
    const cutoff = Date.now() - 10000;
    while (samples.length && samples[0].ts < cutoff) samples.shift();
  }

  function metrics() {
    const window = samples.filter((s) => s.ts > Date.now() - 10000);
    const n = window.length;
    const errors = window.filter((s) => !s.ok).length;
    const avg = n ? window.reduce((sum, s) => sum + s.ms, 0) / n : 0;
    return {
      service: name,
      port,
      uptime_s: Math.round((Date.now() - started) / 1000),
      status: fault.mode === 'crash' ? 'down' : fault.mode === 'none' ? 'up' : 'degraded',
      fault: fault.mode,
      reachable: true,
      requests: n,
      error_rate: n ? errors / n : 0,
      avg_latency_ms: avg,
      rps: n / 10,
      logs: logs.slice(-80),
    };
  }

  function callDownstream(trace) {
    const target = new URL('/api/work', downstream.url);
    const startedAt = Date.now();
    return new Promise((resolve) => {
      let settled = false;
      const finish = (result) => {
        if (settled) return;
        settled = true;
        resolve({ ...result, ms: Date.now() - startedAt });
      };
      const req = http.request(
        {
          hostname: target.hostname,
          port: target.port,
          path: `${target.pathname}${target.search}`,
          method: 'GET',
          headers: { 'x-trace-id': trace },
        },
        (res) => {
          let body = '';
          res.on('data', (chunk) => {
            body += chunk;
          });
          res.on('end', () => {
            let parsed = body;
            try {
              parsed = JSON.parse(body);
            } catch (_) {
              /* plain text */
            }
            finish({ ok: res.statusCode < 400, status: res.statusCode, body: parsed });
          });
        }
      );
      req.setTimeout(CALL_TIMEOUT_MS, () => {
        req.destroy();
        finish({ ok: false, status: 504, body: { error: 'timeout' } });
      });
      req.on('error', (err) => finish({ ok: false, status: 502, body: { error: err.message } }));
      req.end();
    });
  }

  async function handleWork(req, res) {
    const trace = req.get('x-trace-id') || crypto.randomBytes(3).toString('hex');
    const mode = fault.mode;
    const t0 = Date.now();
    try {
      if (mode === 'crash') {
        record(false, 1, 503);
        log('error', 'GET /api/work 503 service unhealthy', { trace });
        return res.status(503).json({ error: 'service unhealthy', service: name, trace });
      }

      let localDelay = 15 + Math.random() * 45;
      if (mode === 'latency') localDelay += 1400 + Math.random() * 400;
      if (mode === 'timeout') localDelay += 4500;
      await sleep(localDelay);
      const handlerMs = Math.round(localDelay);

      if (mode === 'timeout') {
        const total = Date.now() - t0;
        record(false, total, 504);
        log('error', `GET /api/work 504 handler ${handlerMs}ms total ${total}ms`, { trace });
        return res.status(504).json({ error: 'handler timed out', service: name, trace });
      }

      if (mode === 'errors' && Math.random() < 0.9) {
        const total = Date.now() - t0;
        record(false, total, 500);
        log('error', `GET /api/work 500 handler ${handlerMs}ms total ${total}ms`, { trace });
        return res.status(500).json({ error: 'internal error', service: name, trace });
      }

      if (downstream) {
        log('info', `-> ${downstream.name}`, { trace });
        const ds = await callDownstream(trace);
        log(ds.ok ? 'info' : 'error', `<- ${downstream.name} ${ds.status} in ${ds.ms}ms`, { trace });
        if (!ds.ok) {
          const total = Date.now() - t0;
          record(false, total, 502);
          log('error', `GET /api/work 502 handler ${handlerMs}ms total ${total}ms`, { trace });
          return res.status(502).json({
            error: 'downstream failure',
            service: name,
            downstream: ds.status,
            trace,
            latency_ms: total,
          });
        }
      }

      const total = Date.now() - t0;
      record(true, total, 200);
      const level = handlerMs > 800 ? 'warn' : 'info';
      log(level, `GET /api/work 200 handler ${handlerMs}ms total ${total}ms`, { trace });
      return res.json({ service: name, trace, latency_ms: total });
    } catch (err) {
      log('error', `handler failed: ${err.message}`, { trace });
      return res.status(500).json({ error: 'exception', service: name, trace });
    }
  }

  app.get('/favicon.ico', (_req, res) => res.status(204).end());
  app.get('/health', (_req, res) => {
    if (fault.mode === 'crash') return res.status(503).json({ status: 'down', service: name });
    res.json({ status: 'ok', service: name, port });
  });
  app.get('/api/metrics', (_req, res) => res.json(metrics()));
  app.get('/api/logs', (_req, res) => res.json({ service: name, logs: logs.slice(-120) }));
  app.get(['/api/work', '/api/data'], handleWork);
  app.post('/api/fault', (req, res) => {
    const mode = ['latency', 'errors', 'timeout', 'crash'].includes(req.body?.mode)
      ? req.body.mode
      : 'latency';
    samples.length = 0;
    fault = { mode };
    res.json({ ok: true, service: name, fault: mode });
  });
  app.post(['/api/repair', '/api/inject-fault'], (req, res) => {
    // Old inject route blocks the process; repair/clear keeps the server up for the demo.
    if (req.path === '/api/inject-fault') {
      fault = { mode: 'latency' };
      return res.json({ message: 'Fault executed', service: name, fault: 'latency' });
    }
    const action = req.body?.action || 'clear';
    fault = { mode: 'none' };
    samples.length = 0;
    const message = action === 'restart'
      ? 'process recycled, accepting traffic'
      : 'health restored, accepting traffic';
    log('info', message);
    res.json({ ok: true, service: name, action });
  });
  app.get('/', (_req, res) => {
    res.type('html').send(statusPage(name, port));
  });

  const server = app.listen(port, '0.0.0.0');
  server.on('listening', () => log('info', `listening on :${port}`));
  server.on('error', (err) => {
    console.error(err);
    process.exit(1);
  });
  return app;
}

function statusPage(name, port) {
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>${name} :${port}</title>
  <style>
    :root { color-scheme: dark; }
    body { margin: 0; background: #101410; color: #d7e0d4; font: 13px/1.5 ui-monospace, Menlo, monospace; }
    header { padding: 14px 18px; border-bottom: 1px solid #2a342c; display: flex; justify-content: space-between; }
    b { color: #f2f6ef; font-weight: 600; }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: #7dcea0; display: inline-block; margin-right: 8px; }
    #logs { padding: 12px 18px 28px; white-space: pre-wrap; }
    .error { color: #e36b5a; } .warn { color: #e6b15a; } .meta { color: #8b9788; }
  </style>
</head>
<body>
  <header><div><span class="dot"></span><b>${name}</b> listening on :${port}</div><div class="meta" id="stat">starting</div></header>
  <div id="logs">waiting for requests…</div>
  <script>
    const fmt = (ts) => new Date(ts).toLocaleTimeString('en-GB', { hour12: false });
    async function tick() {
      const [metrics, logs] = await Promise.all([
        fetch('/api/metrics').then((r) => r.json()),
        fetch('/api/logs').then((r) => r.json()),
      ]);
      document.getElementById('stat').textContent =
        metrics.status + '  ' + metrics.rps.toFixed(1) + ' rps  ' + Math.round(metrics.avg_latency_ms) + 'ms';
      document.getElementById('logs').innerHTML = logs.logs.slice(-40).map((line) =>
        '<div class="' + line.level + '"><span class="meta">' + fmt(line.ts) + '</span>  ' +
        line.level.toUpperCase().padEnd(5, ' ') + '  ' + line.message + '</div>'
      ).join('') || 'waiting for requests…';
    }
    tick();
    setInterval(tick, 1000);
  </script>
</body>
</html>`;
}

module.exports = { createService };

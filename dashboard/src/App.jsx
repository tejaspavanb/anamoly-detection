import { useEffect, useRef, useState } from 'react';
import Chat from './Chat.jsx';
import './App.css';

const NODES = [
  { name: 'frontend-service', port: 3000 },
  { name: 'backend-service', port: 3001 },
  { name: 'payment-service', port: 3002 },
];

const FAULTS = [
  { mode: 'errors', label: 'Error storm', detail: 'Most calls return 500' },
  { mode: 'latency', label: 'Latency spike', detail: 'Handler waits about 1.6s' },
  { mode: 'timeout', label: 'Handler timeout', detail: 'Stalls past the caller deadline' },
  { mode: 'crash', label: 'Crash', detail: 'Refuses traffic with 503' },
];

const PHASE_COPY = {
  watching: 'Score is over the line. Holding a few seconds so the logs fill in.',
  analyzing: 'Sending metrics, logs, and a console snapshot to Groq.',
  repairing: 'Applying the repair on the service Groq named.',
  verifying: 'Repair sent. Waiting for a clean window under the threshold.',
  ready: 'Diagnosis is in. Auto-repair is off, so the fault is still running.',
  needs_key: 'The autoencoder fired. Add a Groq key and it will read this window.',
  resolved: 'Back under the threshold.',
  still_unhealthy: 'The repair ran, and the score is still high.',
  ai_error: 'Groq did not return a diagnosis.',
};

function clock(ts) {
  const date = new Date(ts);
  if (Number.isNaN(date.getTime())) return '--:--:--.---';
  const base = date.toLocaleTimeString('en-GB', { hour12: false });
  return `${base}.${String(date.getMilliseconds()).padStart(3, '0')}`;
}

function shortName(name) {
  return (name || '').replace('-service', '');
}

function Spark({ points, threshold }) {
  if (!points || points.length < 2) return null;
  const width = 188;
  const height = 46;
  const max = Math.max(threshold * 1.5, ...points, 0.001);
  const coords = points.map((point, index) => {
    const x = (index / (points.length - 1)) * width;
    const y = height - (point / max) * (height - 4) - 2;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  const yLine = height - (threshold / max) * (height - 4) - 2;
  return (
    <svg className="spark" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Reconstruction error">
      <line x1="0" x2={width} y1={yLine} y2={yLine} />
      <polyline points={coords} />
    </svg>
  );
}

function Terminal({ service, marked }) {
  const body = useRef(null);
  const stick = useRef(true);
  const logs = service.logs || [];

  useEffect(() => {
    const el = body.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [logs]);

  const status = service.reachable === false ? 'down' : service.status || 'down';

  return (
    <section className={`terminal ${marked || ''} ${status}`}>
      <header className="term-bar">
        <span className={`dot ${status}`} />
        <span className="cmd">node index.js</span>
        <a href={`http://127.0.0.1:${service.port}/`} target="_blank" rel="noreferrer">
          :{service.port}
        </a>
        <span className="term-stat">
          {service.reachable === false
            ? 'not listening'
            : `${Number(service.rps || 0).toFixed(1)} rps · ${Math.round(service.avg_latency_ms || 0)} ms`}
        </span>
      </header>
      <div className="term-sub">
        <strong>{service.name}</strong>
        <span>{status === 'down' && service.reachable !== false ? 'unhealthy' : status}</span>
        {service.fault && service.fault !== 'none' && <em>{service.fault}</em>}
        {service.uptime_s ? <span>{service.uptime_s}s up</span> : null}
      </div>
      <div
        className="term-body"
        ref={body}
        onScroll={(event) => {
          const el = event.currentTarget;
          stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
        }}
      >
        {logs.length === 0 && <div className="muted">waiting for process output…</div>}
        {logs.map((line, index) => (
          <div className={`log ${line.level}`} key={`${line.ts}-${index}`}>
            <span>{clock(line.ts)}</span>
            <b>{line.level}</b>
            <code>{line.message}</code>
          </div>
        ))}
        {service.reachable !== false && <div className="live-cursor" aria-hidden="true" />}
      </div>
    </section>
  );
}

export default function App() {
  const [data, setData] = useState(null);
  const [offline, setOffline] = useState(false);
  const [target, setTarget] = useState('payment-service');
  const [pending, setPending] = useState({});
  const [notice, setNotice] = useState('');
  const [keyDraft, setKeyDraft] = useState('');
  const [shot, setShot] = useState(null);
  const [autoOverride, setAutoOverride] = useState(null);

  useEffect(() => {
    let stop = false;
    async function pull() {
      try {
        const response = await fetch('/api/overview');
        if (!response.ok) throw new Error(`overview ${response.status}`);
        const body = await response.json();
        if (!stop) {
          setData(body);
          setOffline(false);
        }
      } catch {
        if (!stop) setOffline(true);
      }
    }
    pull();
    const id = setInterval(pull, 1000);
    return () => {
      stop = true;
      clearInterval(id);
    };
  }, []);

  const incidentId = data?.incident?.id;
  const analysisReady = data?.incident?.analysis_ready;

  useEffect(() => {
    if (!analysisReady || !incidentId) return undefined;
    let cancel = false;
    fetch('/api/ai/snapshot')
      .then((response) => response.json())
      .then((body) => {
        if (!cancel) setShot({ id: incidentId, image: body.image });
      })
      .catch(() => {});
    return () => {
      cancel = true;
    };
  }, [incidentId, analysisReady]);

  const services = NODES.map((node) => {
    const live = data?.services?.find((service) => service.name === node.name);
    return live || {
      ...node,
      status: 'down',
      reachable: false,
      logs: [],
      rps: 0,
      avg_latency_ms: 0,
      error_rate: 0,
      fault: 'none',
      uptime_s: 0,
    };
  });

  const incident = data?.incident;
  const auto = autoOverride ?? data?.settings?.auto_repair ?? true;
  const root = incident?.analysis_ready ? incident.root_cause_service : null;
  const signal = data?.anomaly ? data?.attribution?.service : null;
  const score = data?.score || 0;
  const threshold = data?.threshold || 0;
  const ratio = threshold > 0 ? score / threshold : 0;

  async function run(key, url, payload) {
    setPending((current) => ({ ...current, [key]: true }));
    setNotice('');
    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const text = await response.text();
      if (!response.ok) {
        let detail = text;
        try {
          detail = JSON.parse(text).detail || text;
        } catch {
          /* plain text */
        }
        throw new Error(typeof detail === 'string' ? detail : 'request failed');
      }
      return true;
    } catch (error) {
      setNotice(error.message);
      return false;
    } finally {
      setPending((current) => ({ ...current, [key]: false }));
    }
  }

  const scores = data?.attribution?.scores || {};
  const image = shot && incidentId && shot.id === incidentId ? shot.image : null;
  const repair = incident?.repair;

  return (
    <div className="app">
      <header className="top">
        <div>
          <p className="eyebrow">Microservice anomaly detection</p>
          <h1>Live service console</h1>
        </div>
        <div className="top-controls">
          <span className={`health ${data?.anomaly ? 'bad' : 'ok'}`}>
            {offline ? 'API offline' : data?.anomaly ? 'Anomaly' : data?.ready ? 'Healthy' : 'Starting'}
          </span>
          <label className="toggle">
            <input
              type="checkbox"
              checked={auto}
              onChange={(event) => {
                const next = event.target.checked;
                setAutoOverride(next);
                run('auto', '/api/settings', { auto_repair: next });
              }}
            />
            Auto-repair
          </label>
          <span className="model">{data?.settings?.model || 'qwen/qwen3.8-27b'}</span>
        </div>
      </header>

      <section className="graph" aria-label="Service chain">
        {services.map((service, index) => {
          const mark = root === service.name ? 'root' : !root && signal === service.name ? 'signal' : '';
          return (
            <div className="graph-step" key={service.name}>
              {index > 0 && <div className="arrow" />}
              <div className={`gnode ${service.reachable === false ? 'down' : service.status} ${mark}`}>
                <strong>{shortName(service.name)}</strong>
                <span>:{service.port}</span>
                {mark === 'root' && <em>root cause</em>}
                {mark === 'signal' && <em>signal</em>}
              </div>
            </div>
          );
        })}
      </section>

      <section className="terminals">
        {services.map((service) => (
          <Terminal
            key={service.name}
            service={service}
            marked={root === service.name ? 'root' : !root && signal === service.name ? 'signal' : ''}
          />
        ))}
      </section>

      <section className="bottom">
        <div className="panel">
          <h2>Inject a failure</h2>
          <p className="hint">Traffic is already running through the chain. Pick a process and break it.</p>
          <div className="targets" role="group" aria-label="Service to break">
            {NODES.map((node) => (
              <button
                key={node.name}
                className={target === node.name ? 'on' : ''}
                onClick={() => setTarget(node.name)}
                type="button"
              >
                {shortName(node.name)}
              </button>
            ))}
          </div>
          <div className="faults">
            {FAULTS.map((fault) => {
              const key = `fault:${target}:${fault.mode}`;
              return (
                <button
                  key={fault.mode}
                  type="button"
                  className={fault.mode}
                  disabled={!!pending[key]}
                  onClick={() => run(key, '/api/faults', { service: target, mode: fault.mode })}
                >
                  <strong>{fault.label}</strong>
                  <span>{fault.detail} · {shortName(target)}</span>
                </button>
              );
            })}
          </div>
          <div className="restore">
            <button
              type="button"
              disabled={!!pending[`restore:${target}`]}
              onClick={() => run(`restore:${target}`, '/api/faults', { service: target, mode: 'none' })}
            >
              Restore {shortName(target)}
            </button>
            <button
              type="button"
              disabled={!!pending['restore:all']}
              onClick={() => run('restore:all', '/api/faults', { service: 'all', mode: 'none' })}
            >
              Restore all
            </button>
          </div>
          {notice && <p className="notice">{notice}</p>}
          <ul className="events">
            {(data?.events || []).slice(-6).reverse().map((event, index) => (
              <li key={`${event.ts}-${index}`} className={event.level}>
                <span>{clock(event.ts)}</span>
                {event.message}
              </li>
            ))}
          </ul>
        </div>

        <div className="panel diagnosis">
          <div className="score-head">
            <div>
              <h2>Autoencoder</h2>
              <p className="hint">
                Reconstruction error {score.toFixed(4)} · threshold {threshold.toFixed(4)}
              </p>
            </div>
            <Spark points={data?.history || []} threshold={threshold} />
          </div>
          <div className="meter" aria-hidden="true">
            <div className={data?.anomaly ? 'bad' : 'ok'} style={{ width: `${Math.min(100, ratio * 42)}%` }} />
          </div>
          <div className="bars">
            {NODES.map((node) => (
              <div className="bar-row" key={node.name}>
                <span>{shortName(node.name)}</span>
                <div className="track">
                  <div style={{ width: `${Math.min(100, ((scores[node.name] || 0) / Math.max(threshold, 0.0001)) * 100)}%` }} />
                </div>
              </div>
            ))}
          </div>

          {!data?.settings?.has_key && (
            <form
              className="key-form"
              onSubmit={(event) => {
                event.preventDefault();
                run('settings', '/api/settings', { groq_api_key: keyDraft }).then((ok) => {
                  if (ok) setKeyDraft('');
                });
              }}
            >
              <label htmlFor="groq-key">Groq API key</label>
              <div>
                <input
                  id="groq-key"
                  type="password"
                  autoComplete="off"
                  placeholder="gsk_…"
                  value={keyDraft}
                  onChange={(event) => setKeyDraft(event.target.value)}
                />
                <button type="submit" disabled={!!pending.settings || !keyDraft.trim()}>Save</button>
              </div>
              <p className="hint">Used for this session only. Free-tier vision model reads the snapshot plus the logs.</p>
            </form>
          )}

          {incident ? (
            <div className="incident">
              <div className="phase">{incident.phase.replaceAll('_', ' ')}</div>
              <p>{incident.error || PHASE_COPY[incident.phase] || incident.summary}</p>
              {incident.summary && incident.phase !== 'ai_error' && (
                <p className="summary">{incident.summary}</p>
              )}
              {incident.root_cause_service && (
                <p className="cause">
                  {shortName(incident.root_cause_service)}
                  {incident.fault_type ? ` · ${incident.fault_type}` : ''}
                  {incident.confidence != null ? ` · ${Math.round(incident.confidence)}%` : ''}
                  {incident.used_image ? ' · vision' : ''}
                </p>
              )}
              {incident.evidence?.length > 0 && (
                <ul className="evidence">
                  {incident.evidence.map((item) => <li key={item}>{item}</li>)}
                </ul>
              )}
              {incident.suggestions?.length > 0 && (
                <ol className="suggestions">
                  {incident.suggestions.map((item) => <li key={item}>{item}</li>)}
                </ol>
              )}
              {repair?.reason && <p className="hint">{repair.reason}</p>}
              <div className="ai-actions">
                <button type="button" disabled={!!pending.analyze || !data?.settings?.has_key} onClick={() => run('analyze', '/api/ai/analyze', {})}>
                  Run diagnosis
                </button>
                {repair && repair.action !== 'none' && (
                  <button
                    type="button"
                    className="solid"
                    disabled={!!pending.repair || incident.repair_applied}
                    onClick={() => run('repair', '/api/ai/repair', {})}
                  >
                    {incident.repair_applied ? 'Repair sent' : `Repair ${shortName(repair.service)}`}
                  </button>
                )}
              </div>
            </div>
          ) : (
            <div className="incident quiet">
              <p>{data?.ready ? 'No open incident. Inject a failure to wake the model.' : 'Waiting until frontend, backend, and payment are listening.'}</p>
              <button type="button" disabled={!!pending.analyze || !data?.settings?.has_key} onClick={() => run('analyze', '/api/ai/analyze', {})}>
                Run diagnosis
              </button>
            </div>
          )}

          {image && (
            <figure className="shot">
              <img src={image} alt="Console snapshot sent to the vision model" />
              <figcaption>Snapshot Groq saw</figcaption>
            </figure>
          )}
        </div>
        <Chat />
      </section>
    </div>
  );
}

const NODES = [
  { name: 'frontend-service', port: 3000 },
  { name: 'backend-service', port: 3001 },
  { name: 'payment-service', port: 3002 },
];

const BARS = 90;

function clock(ts) {
  const date = new Date(ts);
  if (Number.isNaN(date.getTime())) return '--:--:--';
  return date.toLocaleTimeString('en-GB', { hour12: false });
}

function shortName(name) {
  return (name || '').replace('-service', '');
}

function uptimeLabel(seconds) {
  if (!seconds) return 'just started';
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return minutes ? `${minutes}m ${rest}s up` : `${rest}s up`;
}

const FAULT_LABEL = { errors: 'error storm', latency: 'latency', timeout: 'timeout', crash: 'crashed' };

function serviceStatus(service) {
  if (!service || service.reachable === false || service.status === 'down') return 'down';
  if (service.status === 'degraded' || (service.error_rate || 0) >= 0.2 || (service.avg_latency_ms || 0) >= 1500) return 'degraded';
  return 'up';
}

function sampleStatus(point) {
  if (!point || point.status === 'down') return 'down';
  if (point.status === 'degraded' || (point.error_rate || 0) >= 0.2 || (point.latency || 0) >= 1500) return 'degraded';
  return 'up';
}

function bannerFor(services, data, offline) {
  if (offline) return { tone: 'down', title: 'Status unavailable', detail: 'The monitor API is not responding.' };
  if (!data?.ready) return { tone: 'degraded', title: 'Starting up', detail: 'Waiting until every process is listening.' };
  const statuses = services.map(serviceStatus);
  if (statuses.some((status) => status === 'down')) {
    return { tone: 'down', title: 'Major outage', detail: 'At least one service is not accepting traffic.' };
  }
  if (data.anomaly || statuses.some((status) => status === 'degraded')) {
    return { tone: 'degraded', title: 'Degraded performance', detail: 'A service is unhealthy or the autoencoder is over its threshold.' };
  }
  return { tone: 'ok', title: 'All systems operational', detail: 'Frontend, backend, and payment are accepting traffic.' };
}

function HistoryStrip({ samples, name }) {
  const recent = samples.slice(-BARS);
  const pad = Math.max(0, BARS - recent.length);
  const cells = [...Array(pad).fill(null), ...recent];
  return (
    <div className="strip" aria-hidden="true">
      {cells.map((sample, index) => {
        if (!sample) return <i key={`empty-${index}`} className="empty" />;
        const point = (sample.services || []).find((service) => service.name === name);
        const status = sampleStatus(point);
        return <i key={`${sample.ts}-${index}`} className={status} title={`${clock(sample.ts)} ${status}`} />;
      })}
    </div>
  );
}

export default function Status({ data, offline }) {
  const timeline = data?.timeline || [];
  const services = NODES.map((node) => {
    const live = data?.services?.find((service) => service.name === node.name);
    return live ? { ...node, ...live } : { ...node, reachable: false, status: 'down', rps: 0, avg_latency_ms: 0, error_rate: 0, uptime_s: 0, fault: 'none' };
  });
  const banner = bannerFor(services, data, offline);
  const events = [...(data?.events || [])].reverse();
  const updated = timeline.length ? clock(timeline[timeline.length - 1].ts) : clock(new Date().toISOString());

  return (
    <div className="status-wrap">
      <section className={`banner ${banner.tone}`}>
        <div>
          <h1>{banner.title}</h1>
          <p>{banner.detail}</p>
        </div>
        <div className="banner-meta">
          <span>Updated {updated}</span>
          <span>Last {Math.min(BARS, timeline.length) || 0} checks</span>
        </div>
      </section>

      <section className="status-list">
        {services.map((service) => {
          const status = serviceStatus(service);
          const points = timeline
            .map((sample) => (sample.services || []).find((item) => item.name === service.name))
            .filter(Boolean);
          const operational = points.filter((point) => sampleStatus(point) === 'up').length;
          const ratio = points.length ? Math.round((operational / points.length) * 1000) / 10 : 0;
          return (
            <article key={service.name} className={`status-row ${status}`}>
              <header>
                <div>
                  <strong>{shortName(service.name)}</strong>
                  <a href={`http://127.0.0.1:${service.port}/`} target="_blank" rel="noreferrer">:{service.port}</a>
                </div>
                <span className={`pill ${status}`}>{status === 'up' ? 'Operational' : status === 'degraded' ? 'Degraded' : 'Down'}</span>
              </header>
              <HistoryStrip samples={timeline} name={service.name} />
              <footer>
                <span>{ratio}% operational in this window</span>
                <span>{uptimeLabel(service.uptime_s)}</span>
                <span>{Number(service.rps || 0).toFixed(1)} rps</span>
                <span>{Math.round(service.avg_latency_ms || 0)} ms</span>
                <span>{((service.error_rate || 0) * 100).toFixed(0)}% errors</span>
                {service.fault && service.fault !== 'none' ? <span className="fault-note">{FAULT_LABEL[service.fault] || service.fault}</span> : null}
              </footer>
            </article>
          );
        })}
      </section>

      <p className="legend">
        <i className="up" /> Operational
        <i className="degraded" /> Degraded
        <i className="down" /> Down
        <i className="empty" /> No sample yet
      </p>

      <section className="panel history-panel">
        <h2>History</h2>
        <p className="hint">Faults, restores, and detector notes from this session.</p>
        {events.length === 0 ? (
          <p className="hint">No events yet. The bars above fill as checks come in.</p>
        ) : (
          <ul className="feed">
            {events.map((event, index) => (
              <li key={`${event.ts}-${index}`} className={event.level}>
                <span>{clock(event.ts)}</span>
                <i />
                {event.message}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

import { useEffect, useRef, useState } from 'react';

const STARTERS = [
  { id: 'why', label: 'Explain this window', text: 'Explain the current window in plain language. Do not change anything.' },
  { id: 'fix', label: 'Resolve it', text: 'Resolve the unhealthy service.' },
];

export default function Chat() {
  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      content: 'I read the live score and the service logs. Ask what looks wrong, or tell me to resolve it.',
      actions: [],
    },
  ]);
  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);
  const [acting, setActing] = useState(null);
  const [error, setError] = useState('');
  const scroller = useRef(null);

  useEffect(() => {
    const el = scroller.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, sending]);

  async function send(text) {
    const content = text.trim();
    if (!content || sending) return;
    const history = [...messages, { role: 'user', content, actions: [] }];
    setMessages(history);
    setDraft('');
    setSending(true);
    setError('');
    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages: history.slice(-8).map((item) => ({ role: item.role, content: item.content })),
        }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        const detail = body.detail || 'Chat failed';
        throw new Error(typeof detail === 'string' ? detail : 'Chat failed');
      }
      setMessages((current) => [
        ...current,
        { role: 'assistant', content: body.reply, actions: body.actions || [] },
      ]);
    } catch (err) {
      setError(err.message);
    } finally {
      setSending(false);
    }
  }

  async function runAction(action, messageIndex, actionIndex) {
    const key = `${messageIndex}-${actionIndex}`;
    setActing(key);
    setError('');
    try {
      const payload = action.type === 'restore_all'
        ? { service: 'all', mode: 'none' }
        : { service: action.service, mode: 'none' };
      const response = await fetch('/api/faults', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!response.ok) throw new Error('Restore failed');
      setMessages((current) => current.map((item, index) => {
        if (index !== messageIndex) return item;
        return {
          ...item,
          actions: item.actions.map((entry, i) => (i === actionIndex ? { ...entry, applied: true } : entry)),
        };
      }));
    } catch (err) {
      setError(err.message);
    } finally {
      setActing(null);
    }
  }

  return (
    <section className="panel chat">
      <h2>Ask about this window</h2>
      <p className="hint">Explains the score and logs, and can restore the service that is actually failing.</p>
      <div className="chat-starters">
        {STARTERS.map((starter) => (
          <button key={starter.id} type="button" disabled={sending} onClick={() => send(starter.text)}>
            {starter.label}
          </button>
        ))}
      </div>
      <div className="chat-log" ref={scroller}>
        {messages.map((message, index) => (
          <article key={`${message.role}-${index}`} className={`bubble ${message.role}`}>
            <p>{message.content}</p>
            {message.actions?.length > 0 && (
              <div className="chat-actions">
                {message.actions.map((action, actionIndex) => (
                  <button
                    key={`${action.label}-${actionIndex}`}
                    type="button"
                    className="solid"
                    disabled={action.applied || acting === `${index}-${actionIndex}`}
                    onClick={() => runAction(action, index, actionIndex)}
                  >
                    {action.applied ? `${action.label} done` : action.label}
                  </button>
                ))}
              </div>
            )}
          </article>
        ))}
        {sending && <p className="hint">Reading the live window…</p>}
      </div>
      {error && <p className="notice">{error}</p>}
      <form
        className="chat-form"
        onSubmit={(event) => {
          event.preventDefault();
          send(draft);
        }}
      >
        <input
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="Why is payment failing?"
          aria-label="Message"
        />
        <button type="submit" disabled={sending || !draft.trim()}>Send</button>
      </form>
    </section>
  );
}

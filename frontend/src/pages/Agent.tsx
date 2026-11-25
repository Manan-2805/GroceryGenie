import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';

import { useVoiceSession } from '../contexts/VoiceSessionContext';
import { api } from '../services/api';
import type { AssistantEvent, ConversationMessage } from '../services/assistant';
import { useUIStore } from '../store/uiStore';

type Mode = 'select' | 'text' | 'voice';
type RenderMessage = ConversationMessage & { key: string };
const identified = (message: ConversationMessage): RenderMessage => ({
  ...message,
  key: window.crypto.randomUUID(),
});

type Conversation = { id: string; updated_at: string };

export function Agent() {
  const { sessionId, setSessionId } = useUIStore();
  const [mode, setMode] = useState<Mode>('select');
  const [messages, setMessages] = useState<RenderMessage[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const pending = useRef<AbortController | null>(null);
  const tail = useRef<HTMLDivElement>(null);

  function receive(event: AssistantEvent) {
    setMessages((history) => [
      ...history.map((message) => ({ ...message, confirmation_id: null })),
      identified(
        event.type === 'permission_request'
          ? { role: 'assistant', content: event.summary, confirmation_id: event.confirmation_id }
          : { role: 'assistant', content: event.text, records: event.records ?? [] }
      ),
    ]);
  }

  const voice = useVoiceSession({
    session: setSessionId,
    speech: (text) =>
      setMessages((history) => [...history, identified({ role: 'user', content: text })]),
    event: receive,
  });

  useEffect(() => {
    tail.current?.scrollIntoView({ block: 'nearest' });
  }, [messages]);

  useEffect(() => () => pending.current?.abort(), []);

  async function listConversations() {
    setConversations((await api.get<Conversation[]>('/chat/conversations')).data);
  }

  async function history(id: string) {
    const response = await api.get<{ messages: ConversationMessage[] }>('/chat/history', {
      params: { session_id: id },
    });
    const saved = response.data.messages;
    setMessages(
      saved.map((entry, index) =>
        identified(index < saved.length - 1 ? { ...entry, confirmation_id: null } : entry)
      )
    );
  }

  function selectMode(next: Mode) {
    setError('');
    setMode(next);
    if (next !== 'voice') voice.endSession();
    if (next !== 'select') {
      void listConversations().catch(() => undefined);
      if (sessionId !== null && messages.length === 0) {
        void history(sessionId).catch(() => {
          setSessionId(null);
          setError('Previous conversation unavailable. You can start a new one.');
        });
      }
    }
  }

  async function send(text: string, decision?: { confirmation_id: string; approved: boolean }) {
    if (busy || (text.trim().length === 0 && decision === undefined)) return;
    const controller = new AbortController();
    pending.current = controller;
    setBusy(true);
    setError('');
    setInput('');
    const submitted =
      decision === undefined ? text.trim() : decision.approved ? 'Confirm' : 'Cancel';
    setMessages((history) => [...history, identified({ role: 'user', content: submitted })]);
    try {
      const response = await fetch('/api/v1/chat/text', {
        method: 'POST',
        credentials: 'same-origin',
        signal: controller.signal,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, message: submitted, ...decision }),
      });
      if (!response.ok) throw new Error(`Request failed (${response.status})`);
      const id = response.headers.get('X-Session-ID');
      if (id !== null) setSessionId(id);
      const payload = (await response.text()).split('\n').find((line) => line.startsWith('data: '));
      if (payload === undefined) throw new Error('Missing assistant response');
      receive(JSON.parse(payload.slice(6)) as AssistantEvent);
      void listConversations().catch(() => undefined);
    } catch {
      if (!controller.signal.aborted)
        setError(
          'The assistant could not return a response. Refresh the conversation before retrying an action.'
        );
    } finally {
      setBusy(false);
      pending.current = null;
    }
  }

  return (
    <section className="glass-panel flex min-h-[32rem] flex-col gap-4 p-5">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">GroceryGenie Assistant</h1>
        {mode !== 'select' && (
          <nav aria-label="Assistant modes" className="flex gap-3">
            <button
              className="rounded-lg border px-3 py-2"
              type="button"
              disabled={busy}
              onClick={() => selectMode('text')}
            >
              Text Mode
            </button>
            <button
              className="rounded-lg border px-3 py-2"
              type="button"
              disabled={busy}
              onClick={() => selectMode('voice')}
            >
              Voice Mode
            </button>
          </nav>
        )}
      </header>
      {mode === 'select' ? (
        <div className="grid gap-4 sm:grid-cols-2">
          <button
            className="glass-card p-6 text-left"
            type="button"
            onClick={() => selectMode('text')}
          >
            <span className="block text-lg font-semibold">Text Mode</span>Type your grocery request.
          </button>
          <button
            className="glass-card p-6 text-left"
            type="button"
            onClick={() => selectMode('voice')}
          >
            <span className="block text-lg font-semibold">Voice Mode</span>Speak and listen
            hands-free.
          </button>
        </div>
      ) : (
        <>
          <div className="flex flex-wrap gap-3">
            <label className="flex items-center gap-2">
              Conversation
              <select
                className="rounded border bg-app p-2"
                disabled={busy || voice.status !== 'idle'}
                value={sessionId ?? ''}
                onChange={(event) => {
                  const id = event.target.value;
                  setSessionId(id || null);
                  setMessages([]);
                  if (id.length > 0)
                    void history(id).catch(() => setError('Conversation could not be loaded.'));
                }}
              >
                <option value="">New conversation</option>
                {conversations.map((item) => (
                  <option key={item.id} value={item.id}>
                    {new Date(item.updated_at).toLocaleString()}
                  </option>
                ))}
              </select>
            </label>
            {sessionId !== null && (
              <button
                className="rounded border px-3"
                type="button"
                disabled={busy || voice.status !== 'idle'}
                onClick={() => {
                  void api
                    .delete(`/chat/conversations/${sessionId}`)
                    .then(() => {
                      setSessionId(null);
                      setMessages([]);
                      return listConversations();
                    })
                    .catch(() => setError('Conversation could not be deleted.'));
                }}
              >
                Delete conversation
              </button>
            )}
          </div>
          {mode === 'voice' && (
            <div className="flex flex-wrap items-center gap-3">
              {voice.status === 'idle' ? (
                <button
                  className="rounded-lg bg-accent px-4 py-2 text-white"
                  type="button"
                  onClick={() => void voice.startSession(sessionId)}
                >
                  Start voice session
                </button>
              ) : (
                <button
                  className="rounded-lg border px-4 py-2"
                  type="button"
                  onClick={voice.endSession}
                >
                  End voice session
                </button>
              )}
              {voice.status === 'speaking' || voice.status === 'thinking' ? (
                <button
                  className="rounded-lg border px-3 py-2"
                  type="button"
                  onClick={voice.interrupt}
                >
                  Interrupt
                </button>
              ) : null}
              <span role="status">
                {voice.status === 'idle' ? 'Microphone is off' : voice.status}
              </span>
            </div>
          )}
          {error.length > 0 || voice.error.length > 0 ? (
            <p role="alert">{error || voice.error}</p>
          ) : null}
          <div
            role="log"
            aria-label="Conversation messages"
            className="space-y-3 overflow-y-auto rounded-xl border p-3"
            style={{ maxHeight: '55vh' }}
          >
            {messages.length === 0 && <p>Try “find milk under ₹50” or “show my orders”.</p>}
            {messages.map((message) => (
              <article
                key={message.key}
                className={
                  message.role === 'assistant' ? 'glass-card mr-12 p-3' : 'glass-card ml-12 p-3'
                }
              >
                <p className="text-xs font-semibold">
                  {message.role === 'assistant' ? 'GroceryGenie' : 'You'}
                </p>
                <p className="whitespace-pre-wrap">{message.content}</p>
                {(message.records ?? [])
                  .filter((record) => record.package !== undefined)
                  .map((record) => (
                    <Link
                      key={record.id}
                      to={`/items/${record.id}`}
                      className="mt-2 block rounded border p-2"
                    >
                      {record.name} · {record.package} · ₹{record.price}
                    </Link>
                  ))}
                {typeof message.confirmation_id === 'string' ? (
                  <div className="mt-3 flex gap-2">
                    {[true, false].map((approved) => (
                      <button
                        className="rounded-lg border px-3 py-2"
                        type="button"
                        key={String(approved)}
                        disabled={busy}
                        onClick={() => {
                          const id = message.confirmation_id;
                          if (typeof id !== 'string') return;
                          if (mode === 'voice' && voice.status !== 'idle')
                            voice.confirm(id, approved);
                          else void send('', { confirmation_id: id, approved });
                        }}
                      >
                        {approved ? 'Confirm action' : 'Cancel action'}
                      </button>
                    ))}
                  </div>
                ) : null}
              </article>
            ))}
            <div ref={tail} />
          </div>
          {busy && <p role="status">Processing request…</p>}
          {mode === 'text' || voice.status === 'idle' ? (
            <form
              className="flex items-end gap-3"
              onSubmit={(event) => {
                event.preventDefault();
                void send(input);
              }}
            >
              <label className="grid flex-1 gap-1">
                Message
                <input
                  className="rounded-lg border bg-transparent p-3"
                  value={input}
                  maxLength={500}
                  onChange={(event) => setInput(event.target.value)}
                />
              </label>
              <button
                className="rounded-lg bg-accent px-4 py-3 text-white"
                type="submit"
                disabled={busy || input.trim().length === 0}
              >
                Send
              </button>
            </form>
          ) : null}
        </>
      )}
    </section>
  );
}

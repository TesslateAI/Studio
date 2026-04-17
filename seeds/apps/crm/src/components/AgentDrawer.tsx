'use client';

import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useShell } from '../lib/shell';

type Role = 'user' | 'assistant' | 'tool' | 'system';
interface UiMessage {
  role: Role;
  content: string;
  tool?: { name: string; args?: string; result?: string };
}

export default function AgentDrawer() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState<UiMessage[]>([]);
  const [busy, setBusy] = useState(false);
  const [handshake, setHandshake] = useState<{ sessionId: string; apiKey: string | null } | null>(
    null,
  );
  const shellRef = useRef<ReturnType<typeof useShell> | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const shell = useShell();
    shellRef.current = shell;
    let cancelled = false;
    shell.ready.then((h) => {
      if (cancelled) return;
      setHandshake({ sessionId: h.sessionId, apiKey: h.apiKey });
    });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (open) shellRef.current?.beginInvocation();
    return () => {
      if (open) shellRef.current?.endInvocation();
    };
  }, [open]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages]);

  async function sendTurn() {
    const text = input.trim();
    if (!text || busy) return;
    setInput('');
    const next = [...messages, { role: 'user' as const, content: text }];
    setMessages(next);
    setBusy(true);

    try {
      const res = await fetch('/api/agent', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(handshake?.apiKey ? { Authorization: `Bearer ${handshake.apiKey}` } : {}),
        },
        body: JSON.stringify({
          messages: next.map((m) => ({ role: m.role, content: m.content })),
        }),
      });
      if (!res.ok || !res.body) throw new Error(`agent HTTP ${res.status}`);

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      let assistant: UiMessage = { role: 'assistant', content: '' };
      setMessages((m) => [...m, assistant]);

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const events = buf.split('\n\n');
        buf = events.pop() ?? '';
        for (const evt of events) {
          const lines = evt.split('\n');
          let eventName = 'message';
          let data = '';
          for (const line of lines) {
            if (line.startsWith('event: ')) eventName = line.slice(7).trim();
            else if (line.startsWith('data: ')) data += line.slice(6);
          }
          if (!data) continue;
          let parsed: any = null;
          try {
            parsed = JSON.parse(data);
          } catch {
            parsed = data;
          }
          if (eventName === 'delta' && parsed?.text) {
            assistant = { ...assistant, content: (assistant.content || '') + parsed.text };
            setMessages((m) => [...m.slice(0, -1), assistant]);
          } else if (eventName === 'tool_call') {
            setMessages((m) => [
              ...m,
              {
                role: 'tool',
                content: `→ ${parsed.name}(${parsed.arguments || ''})`,
                tool: { name: parsed.name, args: parsed.arguments },
              },
            ]);
            assistant = { role: 'assistant', content: '' };
            setMessages((m) => [...m, assistant]);
          } else if (eventName === 'tool_result') {
            setMessages((m) => [
              ...m.slice(0, -1),
              {
                role: 'tool',
                content: `← ${parsed.name}: ${truncate(parsed.result, 200)}`,
                tool: { name: parsed.name, result: parsed.result },
              },
              assistant,
            ]);
          } else if (eventName === 'error') {
            setMessages((m) => [
              ...m,
              { role: 'system', content: `error: ${parsed?.message ?? parsed}` },
            ]);
          }
        }
      }
      router.refresh();
    } catch (e: any) {
      setMessages((m) => [...m, { role: 'system', content: `error: ${e?.message ?? e}` }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button
        onClick={() => setOpen((v) => !v)}
        style={{
          position: 'fixed',
          right: 16,
          bottom: 16,
          padding: '10px 16px',
          background: '#3b5bdb',
          color: 'white',
          border: 0,
          borderRadius: 999,
          cursor: 'pointer',
          boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
          zIndex: 40,
        }}
      >
        {open ? 'Close assistant' : 'Ask assistant'}
      </button>

      <aside
        style={{
          position: 'fixed',
          top: 0,
          right: 0,
          bottom: 0,
          width: open ? 380 : 0,
          background: '#0a0f24',
          borderLeft: open ? '1px solid #1a2244' : 'none',
          transition: 'width 0.2s ease',
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
          zIndex: 30,
        }}
      >
        {open && (
          <>
            <header
              style={{
                padding: 16,
                borderBottom: '1px solid #1a2244',
                fontSize: 14,
                opacity: 0.8,
              }}
            >
              CRM Assistant{' '}
              {handshake?.sessionId && (
                <span style={{ opacity: 0.5, fontSize: 11 }}>· {handshake.sessionId.slice(0, 8)}</span>
              )}
            </header>
            <div
              ref={scrollRef}
              style={{ flex: 1, overflowY: 'auto', padding: 12, display: 'grid', gap: 8 }}
            >
              {messages.map((m, i) => (
                <div key={i} style={bubbleStyle(m.role)}>
                  <div style={{ fontSize: 11, opacity: 0.6, marginBottom: 4 }}>{m.role}</div>
                  <div style={{ whiteSpace: 'pre-wrap', fontSize: 13 }}>{m.content}</div>
                </div>
              ))}
              {messages.length === 0 && (
                <div style={{ opacity: 0.5, fontSize: 13, padding: 8 }}>
                  Try: &ldquo;Add Jane Smith from acme.com as a lead&rdquo;
                </div>
              )}
            </div>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                sendTurn();
              }}
              style={{ padding: 12, borderTop: '1px solid #1a2244', display: 'flex', gap: 6 }}
            >
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Ask me to add, update, search contacts…"
                style={{
                  flex: 1,
                  padding: 8,
                  background: '#0f1630',
                  border: '1px solid #1f2a55',
                  color: '#e6e8ef',
                  borderRadius: 6,
                }}
              />
              <button
                type="submit"
                disabled={busy || !input.trim()}
                style={{
                  padding: '8px 14px',
                  background: '#3b5bdb',
                  color: 'white',
                  border: 0,
                  borderRadius: 6,
                  cursor: 'pointer',
                  opacity: busy ? 0.6 : 1,
                }}
              >
                Send
              </button>
            </form>
          </>
        )}
      </aside>
    </>
  );
}

function bubbleStyle(role: Role): React.CSSProperties {
  const base: React.CSSProperties = {
    padding: 10,
    borderRadius: 8,
    background: '#11183a',
    border: '1px solid #1a2244',
  };
  if (role === 'user') return { ...base, background: '#1a2352', borderColor: '#2a3a7a' };
  if (role === 'tool') return { ...base, background: '#0b1330', fontFamily: 'monospace' };
  if (role === 'system') return { ...base, background: '#3a1b1b', borderColor: '#6a2d2d' };
  return base;
}

function truncate(s: unknown, n: number): string {
  const str = typeof s === 'string' ? s : JSON.stringify(s);
  return str.length > n ? str.slice(0, n) + '…' : str;
}

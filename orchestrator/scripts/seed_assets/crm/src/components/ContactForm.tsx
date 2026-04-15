'use client';

import { useState } from 'react';

export default function ContactForm({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: () => void;
}) {
  const [form, setForm] = useState({
    name: '',
    email: '',
    company: '',
    phone: '',
    status: 'lead',
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await fetch('/api/contacts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: form.name,
          email: form.email,
          company: form.company || null,
          phone: form.phone || null,
          status: form.status,
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.error ? JSON.stringify(body.error) : `HTTP ${res.status}`);
      }
      onCreated();
    } catch (err: any) {
      setError(String(err?.message ?? err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(4,8,24,0.7)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 50,
      }}
    >
      <form
        onClick={(e) => e.stopPropagation()}
        onSubmit={submit}
        style={{
          background: '#0f1630',
          border: '1px solid #1f2a55',
          borderRadius: 10,
          padding: 24,
          width: 420,
          display: 'grid',
          gap: 10,
        }}
      >
        <h2 style={{ margin: 0 }}>New contact</h2>
        {(
          [
            ['name', 'Name'],
            ['email', 'Email'],
            ['company', 'Company'],
            ['phone', 'Phone'],
          ] as const
        ).map(([key, label]) => (
          <label key={key} style={{ display: 'grid', gap: 4, fontSize: 13 }}>
            {label}
            <input
              value={(form as any)[key]}
              onChange={(e) => setForm({ ...form, [key]: e.target.value })}
              style={{
                padding: 8,
                background: '#08102a',
                border: '1px solid #1f2a55',
                color: '#e6e8ef',
                borderRadius: 6,
              }}
              required={key === 'name' || key === 'email'}
              type={key === 'email' ? 'email' : 'text'}
            />
          </label>
        ))}
        <label style={{ display: 'grid', gap: 4, fontSize: 13 }}>
          Status
          <select
            value={form.status}
            onChange={(e) => setForm({ ...form, status: e.target.value })}
            style={{
              padding: 8,
              background: '#08102a',
              border: '1px solid #1f2a55',
              color: '#e6e8ef',
              borderRadius: 6,
            }}
          >
            <option value="lead">lead</option>
            <option value="customer">customer</option>
            <option value="lost">lost</option>
          </select>
        </label>
        {error && <div style={{ color: '#ff8484', fontSize: 13 }}>{error}</div>}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 6 }}>
          <button type="button" onClick={onClose} style={btnGhost}>
            Cancel
          </button>
          <button type="submit" disabled={busy} style={btnPrimary}>
            {busy ? 'Saving…' : 'Create'}
          </button>
        </div>
      </form>
    </div>
  );
}

const btnGhost: React.CSSProperties = {
  padding: '8px 14px',
  background: 'transparent',
  border: '1px solid #1f2a55',
  color: '#e6e8ef',
  borderRadius: 6,
  cursor: 'pointer',
};
const btnPrimary: React.CSSProperties = {
  padding: '8px 14px',
  background: '#3b5bdb',
  color: 'white',
  border: 0,
  borderRadius: 6,
  cursor: 'pointer',
};

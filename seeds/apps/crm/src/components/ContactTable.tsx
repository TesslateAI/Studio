'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState, useTransition } from 'react';
import ContactForm from './ContactForm';

type Contact = {
  id: string;
  name: string;
  email: string;
  company: string | null;
  phone: string | null;
  status: string;
  createdAt: string | Date;
};

export default function ContactTable({
  initialContacts,
  initialQuery,
  initialStatus,
}: {
  initialContacts: Contact[];
  initialQuery: string;
  initialStatus: string;
}) {
  const router = useRouter();
  const [q, setQ] = useState(initialQuery);
  const [status, setStatus] = useState(initialStatus);
  const [showForm, setShowForm] = useState(false);
  const [, startTransition] = useTransition();

  function applyFilters(nextQ = q, nextStatus = status) {
    const params = new URLSearchParams();
    if (nextQ) params.set('q', nextQ);
    if (nextStatus) params.set('status', nextStatus);
    startTransition(() => router.push(`/${params.toString() ? '?' + params.toString() : ''}`));
  }

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && applyFilters()}
          placeholder="Search name, email, company…"
          style={fieldStyle}
        />
        <select
          value={status}
          onChange={(e) => {
            setStatus(e.target.value);
            applyFilters(q, e.target.value);
          }}
          style={fieldStyle}
        >
          <option value="">all statuses</option>
          <option value="lead">lead</option>
          <option value="customer">customer</option>
          <option value="lost">lost</option>
        </select>
        <button onClick={() => setShowForm(true)} style={buttonStyle}>
          + New contact
        </button>
      </div>

      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr style={{ textAlign: 'left', opacity: 0.7, fontSize: 13 }}>
            <th style={th}>Name</th>
            <th style={th}>Email</th>
            <th style={th}>Company</th>
            <th style={th}>Status</th>
          </tr>
        </thead>
        <tbody>
          {initialContacts.map((c) => (
            <tr key={c.id} style={{ borderTop: '1px solid #1a2244' }}>
              <td style={td}>
                <Link
                  href={`/contacts/${c.id}`}
                  style={{ color: '#e6e8ef', textDecoration: 'none' }}
                >
                  {c.name}
                </Link>
              </td>
              <td style={td}>{c.email}</td>
              <td style={td}>{c.company ?? ''}</td>
              <td style={td}>
                <span
                  style={{
                    padding: '2px 8px',
                    borderRadius: 999,
                    background: '#1a2244',
                    fontSize: 12,
                  }}
                >
                  {c.status}
                </span>
              </td>
            </tr>
          ))}
          {initialContacts.length === 0 && (
            <tr>
              <td colSpan={4} style={{ padding: 20, opacity: 0.5, textAlign: 'center' }}>
                No contacts. Try asking the agent to add one.
              </td>
            </tr>
          )}
        </tbody>
      </table>

      {showForm && (
        <ContactForm
          onClose={() => setShowForm(false)}
          onCreated={() => {
            setShowForm(false);
            router.refresh();
          }}
        />
      )}
    </div>
  );
}

const fieldStyle: React.CSSProperties = {
  padding: 8,
  background: '#0f1630',
  border: '1px solid #1f2a55',
  color: '#e6e8ef',
  borderRadius: 6,
  flex: 1,
};
const buttonStyle: React.CSSProperties = {
  padding: '8px 14px',
  background: '#3b5bdb',
  color: 'white',
  border: 0,
  borderRadius: 6,
  cursor: 'pointer',
};
const th: React.CSSProperties = { padding: '8px 10px', fontWeight: 500 };
const td: React.CSSProperties = { padding: '10px' };

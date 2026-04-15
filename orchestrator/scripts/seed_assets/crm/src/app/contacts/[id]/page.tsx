import Link from 'next/link';
import { notFound } from 'next/navigation';
import { prisma } from '../../../lib/db';

export const dynamic = 'force-dynamic';

export default async function ContactDetailPage({ params }: { params: { id: string } }) {
  const contact = await prisma.contact.findUnique({
    where: { id: params.id },
    include: {
      notes: { orderBy: { createdAt: 'desc' } },
      activities: { orderBy: { createdAt: 'desc' }, take: 50 },
    },
  });
  if (!contact) notFound();

  return (
    <div style={{ maxWidth: 780 }}>
      <Link href="/" style={{ color: '#7aa2ff', textDecoration: 'none' }}>
        ← Back
      </Link>
      <header style={{ marginTop: 16, marginBottom: 24 }}>
        <h1 style={{ margin: 0 }}>{contact.name}</h1>
        <div style={{ opacity: 0.75, marginTop: 4 }}>
          {contact.email}
          {contact.company ? ` · ${contact.company}` : ''}
          {contact.phone ? ` · ${contact.phone}` : ''}
        </div>
        <div style={{ marginTop: 8 }}>
          <span
            style={{
              padding: '2px 8px',
              borderRadius: 999,
              background: '#1a2244',
              fontSize: 12,
            }}
          >
            {contact.status}
          </span>
        </div>
      </header>

      <section style={{ marginBottom: 32 }}>
        <h2 style={{ fontSize: 16 }}>Notes</h2>
        <form
          action={async (formData: FormData) => {
            'use server';
            const body = String(formData.get('body') ?? '').trim();
            if (!body) return;
            const { prisma: p } = await import('../../../lib/db');
            await p.note.create({ data: { contactId: contact.id, body } });
            await p.activity.create({
              data: {
                contactId: contact.id,
                kind: 'note_added' as any,
                details: JSON.stringify({ source: 'ui' }),
              },
            });
            const { revalidatePath } = await import('next/cache');
            revalidatePath(`/contacts/${contact.id}`);
          }}
          style={{ display: 'flex', gap: 8, marginBottom: 12 }}
        >
          <input
            name="body"
            placeholder="Add a note…"
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
            style={{
              padding: '8px 14px',
              background: '#3b5bdb',
              color: 'white',
              border: 0,
              borderRadius: 6,
            }}
          >
            Save
          </button>
        </form>
        <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
          {contact.notes.map((n) => (
            <li
              key={n.id}
              style={{
                padding: 10,
                background: '#11183a',
                borderRadius: 6,
                marginBottom: 6,
              }}
            >
              <div>{n.body}</div>
              <div style={{ opacity: 0.5, fontSize: 12, marginTop: 4 }}>
                {new Date(n.createdAt).toLocaleString()}
              </div>
            </li>
          ))}
          {contact.notes.length === 0 && <li style={{ opacity: 0.5 }}>No notes yet.</li>}
        </ul>
      </section>

      <section>
        <h2 style={{ fontSize: 16 }}>Activity</h2>
        <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
          {contact.activities.map((a) => (
            <li
              key={a.id}
              style={{
                padding: 8,
                borderBottom: '1px solid #1a2244',
                fontSize: 13,
              }}
            >
              <strong style={{ color: '#7aa2ff' }}>{a.kind}</strong>{' '}
              <span style={{ opacity: 0.6 }}>
                {new Date(a.createdAt).toLocaleString()}
              </span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

import { prisma } from '../lib/db';
import ContactTable from '../components/ContactTable';
import ActivityFeed from '../components/ActivityFeed';

export const dynamic = 'force-dynamic';

export default async function DashboardPage({
  searchParams,
}: {
  searchParams?: { q?: string; status?: string };
}) {
  const q = searchParams?.q ?? '';
  const status = searchParams?.status ?? '';

  const where: any = {};
  if (status && ['lead', 'customer', 'lost'].includes(status)) where.status = status;
  if (q) {
    where.OR = [
      { name: { contains: q } },
      { email: { contains: q } },
      { company: { contains: q } },
    ];
  }

  const [contacts, activities] = await Promise.all([
    prisma.contact.findMany({ where, orderBy: { createdAt: 'desc' }, take: 100 }),
    prisma.activity.findMany({
      orderBy: { createdAt: 'desc' },
      take: 25,
      include: { contact: true },
    }),
  ]);

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 320px', gap: 24 }}>
      <section>
        <header
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: 16,
          }}
        >
          <h1 style={{ fontSize: 24, margin: 0 }}>Contacts</h1>
        </header>
        <ContactTable initialContacts={contacts} initialQuery={q} initialStatus={status} />
      </section>
      <aside>
        <h2 style={{ fontSize: 16, margin: '0 0 12px 0', opacity: 0.8 }}>Activity</h2>
        <ActivityFeed activities={activities} />
      </aside>
    </div>
  );
}

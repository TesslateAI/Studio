async function getContacts() {
  // Server-side fetch goes directly to the API container via API_URL.
  const apiUrl = process.env.API_URL || "http://localhost:3001";
  try {
    const res = await fetch(`${apiUrl}/contacts`, { cache: "no-store" });
    if (!res.ok) return { contacts: [], error: `API ${res.status}` };
    return { contacts: await res.json(), error: null as string | null };
  } catch (e: any) {
    return { contacts: [], error: e?.message || "fetch failed" };
  }
}

export default async function Page() {
  const { contacts, error } = await getContacts();
  return (
    <main>
      <h1>Hello CRM</h1>
      <p>Multi-container demo: Next.js (this) + Node API + Postgres.</p>
      {error && (
        <p style={{ color: "crimson" }}>API error: {error}</p>
      )}
      <h2>Contacts</h2>
      {Array.isArray(contacts) && contacts.length === 0 ? (
        <p>No contacts yet. POST to /api/contacts to add one.</p>
      ) : (
        <ul>
          {Array.isArray(contacts) &&
            contacts.map((c: any) => (
              <li key={c.id}>
                <strong>{c.name}</strong> &mdash; {c.email}
              </li>
            ))}
        </ul>
      )}
    </main>
  );
}

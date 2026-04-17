type ActivityWithContact = {
  id: string;
  kind: string;
  details: string;
  createdAt: string | Date;
  contact: { id: string; name: string } | null;
};

export default function ActivityFeed({ activities }: { activities: ActivityWithContact[] }) {
  if (activities.length === 0) {
    return <div style={{ opacity: 0.5, fontSize: 13 }}>No recent activity.</div>;
  }
  return (
    <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
      {activities.map((a) => (
        <li
          key={a.id}
          style={{
            padding: '8px 10px',
            background: '#11183a',
            borderRadius: 6,
            marginBottom: 6,
            fontSize: 13,
          }}
        >
          <div>
            <strong style={{ color: '#7aa2ff' }}>{a.kind}</strong>
            {a.contact ? ` · ${a.contact.name}` : ''}
          </div>
          <div style={{ opacity: 0.5, fontSize: 11, marginTop: 2 }}>
            {new Date(a.createdAt).toLocaleString()}
          </div>
        </li>
      ))}
    </ul>
  );
}

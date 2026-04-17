import Link from 'next/link';

export default function NotFound() {
  return (
    <div style={{ padding: '48px 24px', maxWidth: 640 }}>
      <h1 style={{ fontSize: 24, marginBottom: 12 }}>Not found</h1>
      <p style={{ color: '#a7adc0', marginBottom: 16 }}>
        We couldn&apos;t find that page.
      </p>
      <Link href="/" style={{ color: '#7aa2ff' }}>← Back to dashboard</Link>
    </div>
  );
}

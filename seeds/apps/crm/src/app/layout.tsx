import type { Metadata } from 'next';
import AgentDrawer from '../components/AgentDrawer';

export const metadata: Metadata = {
  title: 'Tesslate CRM',
  description: 'A minimal CRM demo running on Tesslate Apps runtime.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          background: '#0b1020',
          color: '#e6e8ef',
          minHeight: '100vh',
          fontFamily: 'Inter, system-ui, sans-serif',
        }}
      >
        <div style={{ display: 'flex', minHeight: '100vh' }}>
          <main style={{ flex: 1, padding: '24px 32px' }}>{children}</main>
          <AgentDrawer />
        </div>
      </body>
    </html>
  );
}

import type { Metadata } from 'next';
import { Inter } from 'next/font/google';
import AgentDrawer from '../components/AgentDrawer';

const inter = Inter({ subsets: ['latin'] });

export const metadata: Metadata = {
  title: 'Tesslate CRM',
  description: 'A minimal CRM demo running on Tesslate Apps runtime.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body
        className={inter.className}
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

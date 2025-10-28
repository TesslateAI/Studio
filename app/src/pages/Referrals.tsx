import { useEffect, useState } from 'react';
import axios from 'axios';

const API_URL = import.meta.env.VITE_API_URL || '';

interface ReferralStat {
  referrer: string;
  landings: number;
  conversions: number;
  conversion_rate: number;
  latest_conversion: {
    username: string;
    email: string;
    time: string;
  } | null;
}

export default function Referrals() {
  const [stats, setStats] = useState<ReferralStat[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchStats = async () => {
      try {
        const response = await axios.get(`${API_URL}/api/referrals/stats`);
        setStats(response.data.stats || []);
      } catch (error) {
        console.error('Failed to fetch referral stats:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchStats();
  }, []);

  if (loading) {
    return (
      <div style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'var(--background)',
        color: 'var(--text)',
      }}>
        <div>Loading...</div>
      </div>
    );
  }

  return (
    <div style={{
      minHeight: '100vh',
      background: 'var(--background)',
      color: 'var(--text)',
      padding: '20px',
    }}>
      <div style={{ maxWidth: '1200px', margin: '0 auto' }}>
        <h1 style={{ fontSize: '2rem', marginBottom: '2rem', textAlign: 'center' }}>
          Referral Stats
        </h1>

        {stats.length === 0 ? (
          <div style={{ textAlign: 'center', opacity: 0.7, marginTop: '3rem' }}>
            No referral data yet
          </div>
        ) : (
          <div style={{
            display: 'grid',
            gap: '1rem',
            gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))'
          }}>
            {stats.map((stat) => (
              <div
                key={stat.referrer}
                style={{
                  background: 'var(--surface)',
                  borderRadius: '12px',
                  padding: '1.5rem',
                  border: '1px solid rgba(255, 255, 255, 0.1)',
                }}
              >
                <h2 style={{ fontSize: '1.5rem', marginBottom: '1rem', color: '#ff6b00' }}>
                  {stat.referrer}
                </h2>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span style={{ opacity: 0.7 }}>Landings:</span>
                    <strong>{stat.landings}</strong>
                  </div>

                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span style={{ opacity: 0.7 }}>Signups:</span>
                    <strong>{stat.conversions}</strong>
                  </div>

                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span style={{ opacity: 0.7 }}>Conversion Rate:</span>
                    <strong>{stat.conversion_rate}%</strong>
                  </div>

                  {stat.latest_conversion && (
                    <div style={{
                      marginTop: '1rem',
                      paddingTop: '1rem',
                      borderTop: '1px solid rgba(255, 255, 255, 0.1)'
                    }}>
                      <div style={{ fontSize: '0.875rem', opacity: 0.7, marginBottom: '0.5rem' }}>
                        Latest Signup:
                      </div>
                      <div style={{ fontSize: '0.875rem' }}>
                        <strong>{stat.latest_conversion.username}</strong>
                        <div style={{ opacity: 0.6 }}>{stat.latest_conversion.email}</div>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

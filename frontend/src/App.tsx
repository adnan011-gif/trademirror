import React, { useEffect, useState } from 'react';
import { fetchHealth } from './services/api';

export const App: React.FC = () => {
  const [healthStatus, setHealthStatus] = useState<string>('checking...');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchHealth()
      .then((data) => setHealthStatus(data.status))
      .catch((err: Error) => setError(err.message));
  }, []);

  return (
    <main style={{ padding: '2rem', maxWidth: '640px', margin: '0 auto', textAlign: 'center' }}>
      <h1>TradeMirror</h1>
      <p style={{ marginTop: '1rem', color: '#94a3b8' }}>
        Post-trade behavioural habit review tool for retail F&amp;O traders in India.
      </p>
      <div
        style={{
          marginTop: '2rem',
          padding: '1rem',
          borderRadius: '8px',
          border: '1px solid #334155',
          background: '#1e293b',
        }}
      >
        <span>API Health Status: </span>
        {error ? (
          <strong style={{ color: '#ef4444' }}>Error: {error}</strong>
        ) : (
          <strong style={{ color: '#10b981' }}>{healthStatus}</strong>
        )}
      </div>
    </main>
  );
};

export default App;

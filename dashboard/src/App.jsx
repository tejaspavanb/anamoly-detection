import React, { useState, useEffect } from 'react';
import axios from 'axios';

const App = () => {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const res = await axios.get('http://localhost:8000/api/anomaly/status');
        setStatus(res.data);
      } catch (err) {
        console.error("Error fetching anomaly status", err);
      } finally {
        setLoading(false);
      }
    };
    
    fetchData();
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div style={{
      minHeight: '100vh',
      backgroundColor: '#0f172a',
      color: '#f8fafc',
      fontFamily: "'Inter', sans-serif",
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      padding: '40px 20px'
    }}>
      <h1 style={{
        fontSize: '2.5rem',
        fontWeight: 'bold',
        background: 'linear-gradient(to right, #38bdf8, #818cf8)',
        WebkitBackgroundClip: 'text',
        color: 'transparent',
        marginBottom: '2rem'
      }}>
        Microservice Anomaly Monitor
      </h1>

      {loading ? (
        <p>Loading system status...</p>
      ) : status ? (
        <div style={{
          background: 'rgba(255, 255, 255, 0.05)',
          backdropFilter: 'blur(10px)',
          borderRadius: '16px',
          padding: '30px',
          border: '1px solid rgba(255, 255, 255, 0.1)',
          maxWidth: '600px',
          width: '100%',
          boxShadow: '0 4px 30px rgba(0, 0, 0, 0.1)'
        }}>
          <div style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            marginBottom: '20px'
          }}>
            <h2 style={{ fontSize: '1.5rem', margin: 0 }}>System Status</h2>
            <span style={{
              padding: '8px 16px',
              borderRadius: '9999px',
              fontWeight: 'bold',
              backgroundColor: status.anomaly_detected ? '#ef4444' : '#10b981',
              color: 'white',
              animation: status.anomaly_detected ? 'pulse 2s infinite' : 'none'
            }}>
              {status.anomaly_detected ? 'ANOMALY DETECTED' : 'HEALTHY'}
            </span>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '15px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ color: '#94a3b8' }}>Anomaly Score:</span>
              <span style={{ fontWeight: 'bold' }}>{status.anomaly_score.toFixed(4)}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ color: '#94a3b8' }}>Threshold:</span>
              <span>{status.threshold.toFixed(4)}</span>
            </div>
            {status.anomaly_detected && (
              <>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: '#94a3b8' }}>Root Cause:</span>
                  <span style={{ color: '#ef4444', fontWeight: 'bold' }}>{status.root_cause}</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: '#94a3b8' }}>Confidence:</span>
                  <span>{status.confidence.toFixed(1)}%</span>
                </div>
              </>
            )}
            
            <div style={{ marginTop: '20px', borderTop: '1px solid rgba(255,255,255,0.1)', paddingTop: '20px' }}>
              <h3 style={{ fontSize: '1.2rem', marginBottom: '10px' }}>Live Metrics</h3>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '10px' }}>
                <div style={{ background: 'rgba(0,0,0,0.2)', padding: '15px', borderRadius: '8px', textAlign: 'center' }}>
                  <div style={{ fontSize: '0.8rem', color: '#94a3b8' }}>Latency</div>
                  <div style={{ fontSize: '1.2rem', fontWeight: 'bold' }}>{status.metrics.latency.toFixed(1)}ms</div>
                </div>
                <div style={{ background: 'rgba(0,0,0,0.2)', padding: '15px', borderRadius: '8px', textAlign: 'center' }}>
                  <div style={{ fontSize: '0.8rem', color: '#94a3b8' }}>Req/s</div>
                  <div style={{ fontSize: '1.2rem', fontWeight: 'bold' }}>{status.metrics.request_rate.toFixed(0)}</div>
                </div>
                <div style={{ background: 'rgba(0,0,0,0.2)', padding: '15px', borderRadius: '8px', textAlign: 'center' }}>
                  <div style={{ fontSize: '0.8rem', color: '#94a3b8' }}>Error %</div>
                  <div style={{ fontSize: '1.2rem', fontWeight: 'bold' }}>{(status.metrics.error_rate * 100).toFixed(2)}%</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      ) : (
        <p style={{ color: '#ef4444' }}>Failed to load system status. Is the AI backend running?</p>
      )}
      
      <style>{`
        @keyframes pulse {
          0% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.7); }
          70% { box-shadow: 0 0 0 10px rgba(239, 68, 68, 0); }
          100% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0); }
        }
        body { margin: 0; }
      `}</style>
    </div>
  );
};

export default App;

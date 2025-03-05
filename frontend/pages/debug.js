import { useState, useEffect } from 'react';

export default function DebugPage() {
  const [healthStatus, setHealthStatus] = useState('Unknown');
  const [rootStatus, setRootStatus] = useState('Unknown');
  const [directBackendHealth, setDirectBackendHealth] = useState('Unknown');
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(false);

  const backendUrl = 'https://quiz-generator-pro.onrender.com';
  const proxyUrl = '/api/proxy';

  const addLog = (message) => {
    setLogs(prev => [...prev, `${new Date().toLocaleTimeString()}: ${message}`]);
  };

  const testProxyHealth = async () => {
    setLoading(true);
    addLog('Testing proxy /health endpoint...');
    
    try {
      const startTime = Date.now();
      const response = await fetch(`${proxyUrl}/health`);
      const endTime = Date.now();
      
      if (response.ok) {
        const data = await response.json();
        setHealthStatus(`OK (${endTime - startTime}ms)`);
        addLog(`Health check success in ${endTime - startTime}ms`);
        addLog(`Response: ${JSON.stringify(data)}`);
      } else {
        setHealthStatus(`Error: ${response.status}`);
        addLog(`Health check failed with status ${response.status}`);
      }
    } catch (error) {
      setHealthStatus(`Error: ${error.message}`);
      addLog(`Health check error: ${error.message}`);
    } finally {
      setLoading(false);
    }
  };

  const testProxyRoot = async () => {
    setLoading(true);
    addLog('Testing proxy root endpoint...');
    
    try {
      const startTime = Date.now();
      const response = await fetch(proxyUrl);
      const endTime = Date.now();
      
      if (response.ok) {
        const data = await response.json();
        setRootStatus(`OK (${endTime - startTime}ms)`);
        addLog(`Root check success in ${endTime - startTime}ms`);
        addLog(`Response: ${JSON.stringify(data)}`);
      } else {
        setRootStatus(`Error: ${response.status}`);
        addLog(`Root check failed with status ${response.status}`);
      }
    } catch (error) {
      setRootStatus(`Error: ${error.message}`);
      addLog(`Root check error: ${error.message}`);
    } finally {
      setLoading(false);
    }
  };

  const testDirectBackend = async () => {
    setLoading(true);
    addLog('Testing direct backend access (CORS might block this)...');
    
    try {
      const startTime = Date.now();
      const response = await fetch(`${backendUrl}/health`, {
        mode: 'no-cors' // This might still fail due to CORS
      });
      const endTime = Date.now();
      
      setDirectBackendHealth(`Response received (${endTime - startTime}ms)`);
      addLog(`Direct backend response in ${endTime - startTime}ms`);
    } catch (error) {
      setDirectBackendHealth(`Error: ${error.message}`);
      addLog(`Direct backend error: ${error.message}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ 
      maxWidth: '800px', 
      margin: '0 auto', 
      padding: '20px',
      fontFamily: 'system-ui, sans-serif'
    }}>
      <h1>Backend Connection Diagnostic</h1>
      
      <div style={{ marginBottom: '20px' }}>
        <p><strong>Proxy URL:</strong> {proxyUrl}</p>
        <p><strong>Backend URL:</strong> {backendUrl}</p>
      </div>
      
      <div style={{ 
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fill, minmax(250px, 1fr))',
        gap: '10px',
        marginBottom: '20px'
      }}>
        <div style={{ 
          padding: '15px', 
          border: '1px solid #ddd', 
          borderRadius: '5px' 
        }}>
          <h3>Proxy Health Check</h3>
          <p>Status: {healthStatus}</p>
          <button 
            onClick={testProxyHealth} 
            disabled={loading}
            style={{
              padding: '8px 16px',
              backgroundColor: '#4a51bf',
              color: 'white',
              border: 'none',
              borderRadius: '4px',
              cursor: loading ? 'not-allowed' : 'pointer'
            }}
          >
            Test /health
          </button>
        </div>
        
        <div style={{ 
          padding: '15px', 
          border: '1px solid #ddd', 
          borderRadius: '5px' 
        }}>
          <h3>Proxy Root Check</h3>
          <p>Status: {rootStatus}</p>
          <button 
            onClick={testProxyRoot} 
            disabled={loading}
            style={{
              padding: '8px 16px',
              backgroundColor: '#4a51bf',
              color: 'white',
              border: 'none',
              borderRadius: '4px',
              cursor: loading ? 'not-allowed' : 'pointer'
            }}
          >
            Test /
          </button>
        </div>
        
        <div style={{ 
          padding: '15px', 
          border: '1px solid #ddd', 
          borderRadius: '5px' 
        }}>
          <h3>Direct Backend Check</h3>
          <p>Status: {directBackendHealth}</p>
          <button 
            onClick={testDirectBackend} 
            disabled={loading}
            style={{
              padding: '8px 16px',
              backgroundColor: '#4a51bf',
              color: 'white',
              border: 'none',
              borderRadius: '4px',
              cursor: loading ? 'not-allowed' : 'pointer'
            }}
          >
            Test Direct
          </button>
        </div>
      </div>
      
      <div style={{ marginTop: '20px' }}>
        <h3>Debug Logs</h3>
        <div style={{ 
          maxHeight: '300px', 
          overflow: 'auto',
          backgroundColor: '#f5f5f5',
          padding: '10px',
          borderRadius: '5px',
          fontFamily: 'monospace',
          fontSize: '14px'
        }}>
          {logs.length === 0 ? (
            <p>No logs yet. Run tests to see results.</p>
          ) : (
            logs.map((log, index) => (
              <div key={index} style={{ marginBottom: '5px' }}>{log}</div>
            ))
          )}
        </div>
        <button 
          onClick={() => setLogs([])} 
          style={{
            marginTop: '10px',
            padding: '5px 10px',
            backgroundColor: '#f44336',
            color: 'white',
            border: 'none',
            borderRadius: '4px',
            cursor: 'pointer'
          }}
        >
          Clear Logs
        </button>
      </div>
    </div>
  );
}

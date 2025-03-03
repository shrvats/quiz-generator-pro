import React, { useState, useEffect } from 'react';

// Use this component at the top of your App.jsx
const BackendStatusIndicator = () => {
  const [status, setStatus] = useState('checking');
  const [retryCount, setRetryCount] = useState(0);
  const [timeWaiting, setTimeWaiting] = useState(0);
  const BACKEND_URL = "/api/proxy";

  useEffect(() => {
    let intervalId;
    let timeoutId;

    const checkBackend = async () => {
      try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 5000);
        
        const response = await fetch(`${BACKEND_URL}/health`, {
          signal: controller.signal
        });
        
        clearTimeout(timeoutId);
        
        if (response.ok) {
          setStatus('connected');
          clearInterval(intervalId);
        } else {
          setStatus('unavailable');
          setRetryCount(prev => prev + 1);
        }
      } catch (error) {
        if (error.name === 'AbortError') {
          setStatus('timeout');
        } else {
          setStatus('error');
        }
        setRetryCount(prev => prev + 1);
      }
    };

    // Initial check
    checkBackend();
    
    // Setup retry interval
    intervalId = setInterval(() => {
      checkBackend();
      setTimeWaiting(prev => prev + 5);
    }, 5000);
    
    // Auto-stop retrying after 60 seconds
    timeoutId = setTimeout(() => {
      clearInterval(intervalId);
      if (status !== 'connected') {
        setStatus('failed');
      }
    }, 60000);

    return () => {
      clearInterval(intervalId);
      clearTimeout(timeoutId);
    };
  }, []);

  if (status === 'connected') {
    return (
      <div className="status-bar status-connected">
        <p><strong>Backend Status:</strong> Connected ✅</p>
      </div>
    );
  }

  return (
    <div className="status-bar status-waiting">
      <h3>Starting up the backend service...</h3>
      <p>Free-tier servers on Render.com take up to 1-2 minutes to start after inactivity.</p>
      <div className="progress-container">
        <div 
          className="progress-bar" 
          style={{ 
            width: `${Math.min((timeWaiting / 60) * 100, 100)}%`,
            animation: 'pulse 2s infinite'
          }}
        ></div>
      </div>
      <p>
        {status === 'checking' && 'Checking connection...'}
        {status === 'timeout' && 'Connection timed out, retrying...'}
        {status === 'unavailable' && 'Backend not available yet, retrying...'}
        {status === 'error' && 'Connection error, retrying...'}
        {status === 'failed' && 'Failed to connect after multiple attempts.'}
      </p>
      <p>Time waiting: {timeWaiting} seconds (Attempt #{retryCount})</p>
      {status === 'failed' && (
        <button 
          onClick={() => window.location.reload()}
          className="btn primary-btn"
        >
          Reload Page
        </button>
      )}
      <style jsx>{`
        .status-bar {
          padding: 15px;
          border-radius: 8px;
          margin-bottom: 20px;
          text-align: center;
        }
        .status-waiting {
          background-color: #fff3e0;
          border: 1px solid #ff9800;
        }
        .progress-container {
          width: 100%;
          height: 8px;
          background-color: #f0f0f0;
          border-radius: 4px;
          overflow: hidden;
          margin: 15px 0;
        }
        .progress-bar {
          height: 100%;
          background-color: #ff9800;
          transition: width 0.5s ease;
        }
        @keyframes pulse {
          0% { opacity: 0.6; }
          50% { opacity: 1; }
          100% { opacity: 0.6; }
        }
      `}</style>
    </div>
  );
};

export default BackendStatusIndicator;

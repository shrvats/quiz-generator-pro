import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { MathJax } from 'better-react-mathjax';

// Backend connection options - try direct first, proxy as fallback
const DIRECT_URL = "https://quiz-backend-pro.onrender.com";
const PROXY_URL = "/api/proxy";

export default function QuizRenderer() {
  const [quiz, setQuiz] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [backendStatus, setBackendStatus] = useState('Checking...');
  const [connectionMethod, setConnectionMethod] = useState(null);

  // Check backend health on load
  useEffect(() => {
    const checkHealth = async () => {
      console.log("Testing backend connections...");
      
      // Try direct connection first with CORS mode set to no-cors
      try {
        const directResponse = await fetch(`${DIRECT_URL}/health`, {
          method: 'GET',
          mode: 'no-cors', // This prevents CORS errors but will give an opaque response
          cache: 'no-cache'
        });
        
        console.log("Direct connection seems to work");
        setBackendStatus('Connected ✅');
        setConnectionMethod('direct');
        return;
      } catch (directErr) {
        console.log("Direct connection failed, trying proxy");
      }
      
      // Try proxy as fallback
      try {
        const proxyResponse = await fetch(`${PROXY_URL}/health`);
        
        if (proxyResponse.ok) {
          const data = await proxyResponse.json();
          console.log("Proxy health check:", data);
          setBackendStatus('Connected via proxy ✅');
          setConnectionMethod('proxy');
          return;
        }
        throw new Error(`Status: ${proxyResponse.status}`);
      } catch (proxyErr) {
        console.error("Proxy connection failed:", proxyErr);
        setBackendStatus(`Failed to connect ❌ (${proxyErr.message})`);
        setConnectionMethod(null);
      }
    };
    
    checkHealth();
  }, []);

  const handleFile = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    
    setLoading(true);
    setError(null);
    
    // Determine which endpoint to use based on health check
    const endpoint = connectionMethod === 'direct' ? DIRECT_URL : PROXY_URL;
    
    try {
      // Create form data
      const formData = new FormData();
      formData.append('file', file);
      
      console.log(`Uploading file to ${endpoint}/process`);
      
      // Set appropriate headers and options based on connection method
      const config = { 
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: 60000 // 60 second timeout
      };
      
      // Add special handling for CORS if using direct connection
      if (connectionMethod === 'direct') {
        config.withCredentials = false;
      }
      
      const { data } = await axios.post(
        `${endpoint}/process`,
        formData,
        config
      );
      
      console.log("Received quiz data:", data);
      setQuiz(data);
    } catch (err) {
      console.error('Upload failed:', err);
      setError(`Upload failed: ${err.message || 'Unknown error'}`);
      
      // If the current method failed, try the alternative
      const altEndpoint = connectionMethod === 'direct' ? PROXY_URL : DIRECT_URL;
      try {
        console.log(`Trying alternative endpoint: ${altEndpoint}/process`);
        const formData = new FormData();
        formData.append('file', file);
        
        const config = {
          headers: { 'Content-Type': 'multipart/form-data' },
          timeout: 60000
        };
        
        if (connectionMethod !== 'direct') { // Using direct as fallback
          config.withCredentials = false;
        }
        
        const { data } = await axios.post(
          `${altEndpoint}/process`,
          formData,
          config
        );
        
        console.log("Received quiz data from alternative endpoint:", data);
        setQuiz(data);
        setError(null);
        
        // Update connection method for future requests
        setConnectionMethod(connectionMethod === 'direct' ? 'proxy' : 'direct');
        setBackendStatus(`Connected via alternative method ✅`);
      } catch (altErr) {
        console.error('Alternative upload also failed:', altErr);
        setError(`All connection methods failed. Please try again later.`);
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="container">
      <div className="status-bar" style={{
        background: backendStatus.includes('Connected') ? '#e8f5e9' : '#ffebee',
        padding: '10px',
        borderRadius: '4px',
        marginBottom: '20px'
      }}>
        <p><strong>Backend Status:</strong> {backendStatus}</p>
        <p><small>Connection method: {connectionMethod || 'None available'}</small></p>
      </div>
      
      <div className="upload-section">
        <h2>Upload PDF</h2>
        <input 
          type="file" 
          accept=".pdf" 
          onChange={handleFile}
          disabled={loading || !connectionMethod}
          style={{
            display: 'block',
            width: '100%',
            padding: '20px',
            background: '#f0f0f0',
            border: '3px dashed #1a237e',
            borderRadius: '8px',
            margin: '20px 0',
            cursor: (loading || !connectionMethod) ? 'not-allowed' : 'pointer'
          }}
        />
        
        {loading && <p>Processing PDF...</p>}
        {error && <p style={{color: 'red'}}>{error}</p>}
        {!connectionMethod && !loading && (
          <p style={{color: 'red'}}>
            No working connection to backend. Please check if the backend server is running.
          </p>
        )}
      </div>

      <div className="quiz-grid">
        {quiz.map((q, idx) => (
          <div key={idx} className="card">
            <div className="question">
              {q.question}
              {q.math?.map((formula, i) => (
                <MathJax key={i} dynamic>{`\\(${formula}\\)`}</MathJax>
              ))}
            </div>
            
            {q.tables?.map((table, i) => (
              <pre key={i} className="table">
                {table}
              </pre>
            ))}

            <div className="options">
              {Object.entries(q.options || {}).map(([opt, text]) => (
                <div key={opt} className="option">
                  <strong>{opt}.</strong> {text}
                </div>
              ))}
            </div>

            <div className="answer">
              <strong>Correct Answer:</strong> {q.correct}
              {q.explanation && (
                <div className="explanation">
                  <MathJax dynamic>{q.explanation}</MathJax>
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

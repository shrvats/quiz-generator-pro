import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { MathJax } from 'better-react-mathjax';

export default function QuizRenderer() {
  const [quiz, setQuiz] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [backendStatus, setBackendStatus] = useState('Checking...');

  // Debug backend connection on load
  useEffect(() => {
    console.log("Testing backend connection...");
    // Test if backend is reachable via proxy
    fetch('/api/proxy/health')
      .then(res => {
        if (!res.ok) {
          throw new Error(`Status: ${res.status}`);
        }
        return res.json();
      })
      .then(data => {
        console.log("Backend health check:", data);
        setBackendStatus('Connected ✅');
      })
      .catch(err => {
        console.error("Backend connection failed:", err);
        setBackendStatus(`Failed to connect ❌ (${err.message})`);
      });
  }, []);

  const handleFile = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    
    setLoading(true);
    setError(null);
    
    try {
      // Create form data
      const formData = new FormData();
      formData.append('file', file);
      
      // Set longer timeout (3 minutes)
      const axiosConfig = {
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: 180000 // 3 minutes
      };
      
      console.log("Uploading file to /api/proxy/process...");
      const { data } = await axios.post('/api/proxy/process', formData, axiosConfig);
      
      console.log("Received quiz data:", data);
      setQuiz(data);
    } catch (err) {
      console.error('Upload failed:', err);
      setError(`Upload failed: ${err.message || 'Unknown error'}`);
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
        <p><small>API Endpoint: /api/proxy/process</small></p>
      </div>
      
      <div className="upload-section">
        <h2>Upload PDF</h2>
        <p>Upload a PDF with quiz questions to generate interactive content.</p>
        <input 
          type="file" 
          accept=".pdf" 
          onChange={handleFile}
          disabled={loading}
          style={{
            display: 'block',
            width: '100%',
            padding: '20px',
            background: '#f0f0f0',
            border: '3px dashed #1a237e',
            borderRadius: '8px',
            margin: '20px 0',
            cursor: loading ? 'not-allowed' : 'pointer'
          }}
        />
        
        {loading && (
          <div className="loading-indicator" style={{textAlign: 'center', padding: '20px'}}>
            <p>Processing PDF... This may take up to 2 minutes for large files.</p>
            <div className="spinner" style={{
              border: '4px solid #f3f3f3',
              borderTop: '4px solid #1a237e',
              borderRadius: '50%',
              width: '30px',
              height: '30px',
              animation: 'spin 1s linear infinite',
              margin: '0 auto'
            }}></div>
            <style>{`
              @keyframes spin {
                0% { transform: rotate(0deg); }
                100% { transform: rotate(360deg); }
              }
            `}</style>
          </div>
        )}
        
        {error && (
          <div style={{
            color: 'white',
            background: '#d32f2f',
            padding: '15px',
            borderRadius: '4px',
            marginTop: '20px'
          }}>
            <strong>Error:</strong> {error}
            <p>Try refreshing the page or checking if the backend is running.</p>
          </div>
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

import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { MathJax } from 'better-react-mathjax';

// Backend connection options
const BACKEND_URL = "https://quiz-backend-pro.onrender.com";
const USE_PROXY = true; // Toggle between direct connection and proxy
const API_ENDPOINT = USE_PROXY ? "/api/proxy" : BACKEND_URL;

export default function QuizRenderer() {
  const [quiz, setQuiz] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [backendStatus, setBackendStatus] = useState('Checking...');

  // Check backend health on load
  useEffect(() => {
    console.log("Testing backend connection...");
    
    // Try connection based on selected method
    fetch(`${API_ENDPOINT}/health`)
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
        
        // If proxy fails, try direct connection as fallback
        if (USE_PROXY) {
          console.log("Trying direct connection as fallback...");
          fetch(`${BACKEND_URL}/health`)
            .then(res => res.json())
            .then(data => {
              console.log("Direct backend health check:", data);
              setBackendStatus('Connected via fallback ✅');
            })
            .catch(directErr => {
              console.error("Both connection methods failed");
            });
        }
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
      
      console.log(`Uploading file to ${API_ENDPOINT}/process`);
      const { data } = await axios.post(
        `${API_ENDPOINT}/process`,
        formData,
        { 
          headers: { 'Content-Type': 'multipart/form-data' },
          timeout: 60000 // 60 second timeout
        }
      );
      
      console.log("Received quiz data:", data);
      setQuiz(data);
    } catch (err) {
      console.error('Upload failed:', err);
      setError(`Upload failed: ${err.message || 'Unknown error'}`);
      
      // If using proxy and it fails, try direct connection
      if (USE_PROXY) {
        try {
          console.log("Trying direct backend connection for upload...");
          const formData = new FormData();
          formData.append('file', file);
          
          const { data } = await axios.post(
            `${BACKEND_URL}/process`,
            formData,
            { 
              headers: { 'Content-Type': 'multipart/form-data' },
              timeout: 60000
            }
          );
          
          console.log("Received quiz data from direct connection:", data);
          setQuiz(data);
          setError(null);
        } catch (directErr) {
          console.error('Direct upload also failed:', directErr);
          setError(`All connection methods failed. Please try again later.`);
        }
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
        <p><small>Connection method: {USE_PROXY ? 'API Proxy with fallback' : 'Direct backend connection'}</small></p>
      </div>
      
      <div className="upload-section">
        <h2>Upload PDF</h2>
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
        
        {loading && <p>Processing PDF...</p>}
        {error && <p style={{color: 'red'}}>{error}</p>}
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

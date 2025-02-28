import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { MathJax } from 'better-react-mathjax';

// CORRECT backend URL
const BACKEND_URL = "https://quiz-generator-pro.onrender.com";
const MAX_TIMEOUT = 180000; // 3 minutes timeout

export default function QuizRenderer() {
  const [quiz, setQuiz] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [backendStatus, setBackendStatus] = useState('Checking...');
  const [processingTime, setProcessingTime] = useState(0);
  const [processingTimer, setProcessingTimer] = useState(null);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [stage, setStage] = useState('idle'); // idle, uploading, processing

  // Check backend health on load
  useEffect(() => {
    console.log("Testing backend connection...");
    
    fetch(`${BACKEND_URL}/health`)
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
        console.error("Direct backend connection failed:", err);
        setBackendStatus(`Failed to connect ❌ (${err.message})`);
      });
  }, []);

  // Cleanup timer on unmount
  useEffect(() => {
    return () => {
      if (processingTimer) {
        clearInterval(processingTimer);
      }
    };
  }, [processingTimer]);

  const handleFile = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    
    setLoading(true);
    setError(null);
    setProcessingTime(0);
    setUploadProgress(0);
    setStage('uploading');
    
    // Start a timer to show processing time
    const timer = setInterval(() => {
      setProcessingTime(prev => prev + 1);
    }, 1000);
    
    setProcessingTimer(timer);
    
    try {
      // Create form data
      const formData = new FormData();
      formData.append('file', file);
      
      // Use direct backend URL for file uploads with extended timeout
      console.log(`Uploading file to ${BACKEND_URL}/process`);
      
      setStage('processing');
      
      const { data } = await axios.post(
        `${BACKEND_URL}/process`,
        formData,
        { 
          headers: { 'Content-Type': 'multipart/form-data' },
          timeout: MAX_TIMEOUT, // Extended timeout
          onUploadProgress: (progressEvent) => {
            const percentCompleted = Math.round(
              (progressEvent.loaded * 100) / progressEvent.total
            );
            setUploadProgress(percentCompleted);
            if (percentCompleted === 100) {
              setStage('processing');
            }
          }
        }
      );
      
      console.log("Received quiz data:", data);
      setQuiz(data);
      setStage('complete');
    } catch (err) {
      console.error('Upload failed:', err);
      
      let errorMessage = 'Unknown error';
      
      if (err.code === 'ECONNABORTED' || err.message.includes('timeout')) {
        errorMessage = `Processing timed out after ${MAX_TIMEOUT/1000} seconds. Try a smaller PDF or one with fewer questions.`;
      } else if (err.response) {
        errorMessage = `Server error: ${err.response.status} ${err.response.statusText}`;
        if (err.response.data && err.response.data.detail) {
          errorMessage += ` - ${err.response.data.detail}`;
        }
      } else if (err.message) {
        errorMessage = err.message;
      }
      
      setError(`Upload failed: ${errorMessage}`);
      setStage('error');
    } finally {
      setLoading(false);
      clearInterval(timer);
      setProcessingTimer(null);
    }
  };

  const getProgressPercentage = () => {
    if (stage === 'uploading') {
      return uploadProgress;
    } else if (stage === 'processing') {
      // Show a pulsing progress bar during processing
      return Math.min((processingTime / (MAX_TIMEOUT/1000)) * 100, 95);
    }
    return 0;
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
        <p><small>Using direct backend connection to {BACKEND_URL}</small></p>
      </div>
      
      <div className="upload-section">
        <h2>Upload PDF</h2>
        <p>Upload a PDF file containing quiz questions.</p>
        
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
          <div style={{ marginBottom: '20px' }}>
            <p>
              {stage === 'uploading' ? `Uploading PDF (${uploadProgress}%)...` : 
               `Processing PDF... (${processingTime} seconds elapsed)`}
            </p>
            <p style={{ fontSize: '0.9em', color: '#555' }}>
              {stage === 'uploading' ? 
                'Uploading your PDF to the server...' : 
                'PDF processing may take up to 3 minutes depending on file size and complexity.'}
            </p>
            <div style={{ 
              width: '100%', 
              height: '8px', 
              backgroundColor: '#f0f0f0',
              borderRadius: '4px',
              overflow: 'hidden',
              marginTop: '10px'
            }}>
              <div style={{
                width: `${getProgressPercentage()}%`,
                height: '100%',
                backgroundColor: '#1a237e',
                transition: 'width 0.5s ease',
                animation: stage === 'processing' ? 'pulse 2s infinite' : 'none'
              }}></div>
            </div>
            <style jsx>{`
              @keyframes pulse {
                0% { opacity: 0.6; }
                50% { opacity: 1; }
                100% { opacity: 0.6; }
              }
            `}</style>
          </div>
        )}
        {error && (
          <div style={{
            color: 'red',
            padding: '15px',
            backgroundColor: '#ffebee',
            borderRadius: '4px',
            marginBottom: '20px'
          }}>
            <p><strong>Error:</strong> {error}</p>
            <p style={{ fontSize: '0.9em', marginTop: '10px' }}>
              Suggestions:
              <ul>
                <li>Try with a smaller PDF file</li>
                <li>Ensure the PDF contains properly formatted questions</li>
                <li>Check if the backend service is running</li>
              </ul>
            </p>
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

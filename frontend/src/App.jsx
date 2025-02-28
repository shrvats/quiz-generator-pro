import React, { useState } from 'react';
import { MathJaxContext } from 'better-react-mathjax';
import axios from 'axios';

function App() {
  const [quiz, setQuiz] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(false);

  const handleFile = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    
    setLoading(true);
    setError(null);
    setSuccess(false);
    
    // Create form data
    const formData = new FormData();
    formData.append('file', file);
    
    // Try direct connection with fetch + no-cors first (just to wake up the server)
    try {
      await fetch("https://quiz-backend-pro.onrender.com/health", {
        method: 'GET',
        mode: 'no-cors'
      });
    } catch (e) {
      console.log("Wake-up call failed, but continuing anyway");
    }
    
    // Use proxy for actual upload
    try {
      const response = await axios.post('/api/proxy/process', formData, {
        headers: {
          'Content-Type': 'multipart/form-data'
        },
        timeout: 60000
      });
      
      setQuiz(response.data);
      setSuccess(true);
    } catch (err) {
      console.error("Upload failed:", err);
      setError(`Upload failed: ${err.message || "Unknown error"}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <MathJaxContext>
      <div className="container">
        <h1 style={{ color: '#1a237e', textAlign: 'center' }}>
          PDF Quiz Generator
        </h1>
        
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
          
          {loading && <p>Processing PDF... This may take up to 30 seconds.</p>}
          {error && <p style={{color: 'red'}}>{error}</p>}
          {success && <p style={{color: 'green'}}>PDF processed successfully!</p>}
        </div>

        <div className="quiz-grid">
          {quiz.map((q, idx) => (
            <div key={idx} className="card">
              <div className="question">
                {q.question}
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
                    {q.explanation}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </MathJaxContext>
  );
}

export default App;

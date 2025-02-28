import { useState, useEffect } from 'react'
import axios from 'axios'
import { MathJax } from 'better-react-mathjax'

export default function QuizRenderer() {
  const [quiz, setQuiz] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  // Debug backend connection on load
  useEffect(() => {
    console.log("Backend URL:", import.meta.env.VITE_API_URL);
    // Test if backend is reachable
    fetch(`${import.meta.env.VITE_API_URL}/health`)
      .then(res => res.json())
      .then(data => console.log("Backend health check:", data))
      .catch(err => console.error("Backend connection failed:", err));
  }, []);

  const handleFile = async (e) => {
    const file = e.target.files[0]
    if (!file) return
    
    setLoading(true)
    setError(null)
    
    try {
      const formData = new FormData()
      formData.append('file', file)
      
      const { data } = await axios.post(
        `${import.meta.env.VITE_API_URL}/process`,
        formData,
        { headers: { 'Content-Type': 'multipart/form-data' } }
      )
      
      setQuiz(data)
      console.log("Received quiz data:", data)
    } catch (err) {
      console.error('Upload failed:', err)
      setError(`Upload failed: ${err.message}`)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="container">
      {/* Debug info - remove in production */}
      <div style={{background: '#f0f0f0', padding: '10px', marginBottom: '20px'}}>
        <p>Backend URL: {import.meta.env.VITE_API_URL || 'Not set'}</p>
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
            cursor: 'pointer'
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
                <MathJax key={i} inline dynamic>
                  {`\\(${formula}\\)`}
                </MathJax>
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
  )
}



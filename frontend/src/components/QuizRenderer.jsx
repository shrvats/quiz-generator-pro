import { useState } from 'react'
import axios from 'axios'
import MathJax from 'react-mathjax-preview'

export default function QuizRenderer() {
  const [quiz, setQuiz] = useState([])
  const [loading, setLoading] = useState(false)

  const handleFile = async (e) => {
    const file = e.target.files[0]
    if (!file) return
    
    setLoading(true)
    try {
      const formData = new FormData()
      formData.append('file', file)
      
      const { data } = await axios.post(
        import.meta.env.VITE_API_URL + '/process',
        formData,
        { headers: { 'Content-Type': 'multipart/form-data' } }
      )
      
      setQuiz(data)
    } catch (error) {
      console.error('Upload failed:', error)
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      <input 
        type="file" 
        accept=".pdf" 
        onChange={handleFile}
        disabled={loading}
        style={{ 
          padding: '1.5rem',
          border: '2px dashed #1a237e',
          borderRadius: '8px',
          cursor: 'pointer'
        }}
      />
      
      {loading && (
        <div style={{ textAlign: 'center', margin: '2rem' }}>
          <div className="loader"></div>
          <p>Processing PDF...</p>
        </div>
      )}

      <div className="quiz-grid">
        {quiz.map((q, idx) => (
          <div key={idx} className="card">
            <div className="question">
              {q.question}
              {q.math.map((formula, i) => (
                <div key={i} style={{ margin: '1rem 0' }}>
                  <MathJax math={`$$${formula}$$`} />
                </div>
              ))}
            </div>
            
            {q.tables.map((table, i) => (
              <pre key={i} className="table">
                {table}
              </pre>
            ))}

            <div className="options">
              {Object.entries(q.options).map(([opt, text]) => (
                <div key={opt} className="option">
                  <strong style={{ color: '#1a237e' }}>{opt}.</strong> {text}
                </div>
              ))}
            </div>

            <div className="answer">
              <strong style={{ color: '#2e7d32' }}>Correct Answer:</strong> {q.correct}
              {q.explanation && (
                <div className="explanation">
                  <MathJax math={q.explanation} />
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </>
  )
}

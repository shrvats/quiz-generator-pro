import { useState } from 'react'
import axios from 'axios'
import { MathJax } from 'better-react-mathjax'

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
      />
      
      {loading && <p>Processing PDF...</p>}

      <div className="quiz-grid">
        {quiz.map((q, idx) => (
          <div key={idx} className="card">
            <div className="question">
              {q.question}
              {q.math.map((formula, i) => (
                <MathJax key={i} inline dynamic>
                  {`\\(${formula}\\)`}
                </MathJax>
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
    </>
  )
}


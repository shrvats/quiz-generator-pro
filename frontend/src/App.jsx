import React, { useState } from 'react';
import { MathJaxContext } from 'better-react-mathjax';
import axios from 'axios';

// IMPORTANT: Replace this with your actual backend URL
const BACKEND_URL = "https://quiz-generator-pro.onrender.com";

function App() {
  // PDF upload and processing states
  const [pdfQuestions, setPdfQuestions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  
  // Quiz states
  const [quizStarted, setQuizStarted] = useState(false);
  const [quizQuestions, setQuizQuestions] = useState([]);
  const [numQuestions, setNumQuestions] = useState(10);
  const [userAnswers, setUserAnswers] = useState({});
  const [quizSubmitted, setQuizSubmitted] = useState(false);
  const [score, setScore] = useState(0);

  // Handle PDF upload
  const handleFileUpload = async (event) => {
    const file = event.target.files[0];
    if (!file) return;
    
    setLoading(true);
    setError(null);
    
    const formData = new FormData();
    formData.append('file', file);
    
    try {
      const response = await axios.post(
        `${BACKEND_URL}/process`,
        formData,
        {
          headers: { 'Content-Type': 'multipart/form-data' },
          timeout: 180000 // 3 minutes
        }
      );
      
      console.log("Questions loaded:", response.data);
      setPdfQuestions(response.data);
      setNumQuestions(Math.min(10, response.data.length));
    } catch (err) {
      console.error("Error:", err);
      setError(`Failed to process PDF: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  // Start quiz with selected number of questions
  const startQuiz = () => {
    // Randomly select questions
    const shuffled = [...pdfQuestions].sort(() => 0.5 - Math.random());
    const selected = shuffled.slice(0, numQuestions);
    
    setQuizQuestions(selected);
    setUserAnswers({});
    setQuizSubmitted(false);
    setQuizStarted(true);
  };

  // Select an answer for a question
  const selectAnswer = (questionIndex, option) => {
    setUserAnswers({
      ...userAnswers,
      [questionIndex]: option
    });
  };

  // Submit quiz and calculate score
  const submitQuiz = () => {
    let correctCount = 0;
    
    quizQuestions.forEach((question, index) => {
      if (userAnswers[index] === question.correct) {
        correctCount++;
      }
    });
    
    setScore(correctCount);
    setQuizSubmitted(true);
  };

  // Reset quiz
  const resetQuiz = () => {
    setQuizStarted(false);
    setQuizSubmitted(false);
    setUserAnswers({});
  };

  // Upload screen
  if (!quizStarted && pdfQuestions.length === 0) {
    return (
      <div style={{ padding: '20px', maxWidth: '800px', margin: '0 auto' }}>
        <h1>PDF Quiz Generator</h1>
        
        <div style={{ 
          padding: '20px', 
          border: '1px solid #ddd', 
          borderRadius: '5px',
          marginBottom: '20px' 
        }}>
          <h2>Upload PDF</h2>
          <input 
            type="file" 
            accept=".pdf" 
            onChange={handleFileUpload}
            disabled={loading}
            style={{ display: 'block', marginBottom: '20px' }}
          />
          
          {loading && <p>Loading... Please wait</p>}
          {error && <p style={{ color: 'red' }}>{error}</p>}
        </div>
      </div>
    );
  }

  // Configuration screen
  if (!quizStarted && pdfQuestions.length > 0) {
    return (
      <div style={{ padding: '20px', maxWidth: '800px', margin: '0 auto' }}>
        <h1>Quiz Configuration</h1>
        
        <div style={{ 
          padding: '20px', 
          border: '1px solid #ddd', 
          borderRadius: '5px',
          marginBottom: '20px' 
        }}>
          <h2>Select Number of Questions</h2>
          <p>Total questions available: {pdfQuestions.length}</p>
          
          <div style={{ marginBottom: '20px' }}>
            <label htmlFor="numQuestions">
              Number of questions: {numQuestions}
            </label>
            <input 
              type="range" 
              id="numQuestions"
              min="1"
              max={Math.min(25, pdfQuestions.length)}
              value={numQuestions}
              onChange={(e) => setNumQuestions(parseInt(e.target.value))}
              style={{ width: '100%', display: 'block', marginTop: '10px' }}
            />
          </div>
          
          <button 
            onClick={startQuiz}
            style={{
              padding: '10px 20px',
              backgroundColor: '#007bff',
              color: 'white',
              border: 'none',
              borderRadius: '5px',
              cursor: 'pointer'
            }}
          >
            Start Quiz with {numQuestions} Questions
          </button>
        </div>
      </div>
    );
  }

  // Quiz screen
  return (
    <MathJaxContext>
      <div style={{ padding: '20px', maxWidth: '800px', margin: '0 auto' }}>
        <h1>Quiz</h1>
        
        {/* Header with progress */}
        <div style={{ 
          padding: '10px', 
          backgroundColor: '#f0f0f0', 
          borderRadius: '5px',
          marginBottom: '20px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center'
        }}>
          <div>Questions: {quizQuestions.length}</div>
          <div>Answered: {Object.keys(userAnswers).length} of {quizQuestions.length}</div>
        </div>
        
        {/* Quiz results (only shown when submitted) */}
        {quizSubmitted && (
          <div style={{ 
            padding: '20px', 
            backgroundColor: '#e8f5e9', 
            borderRadius: '5px',
            marginBottom: '20px',
            textAlign: 'center'
          }}>
            <h2>Quiz Results</h2>
            <p style={{ fontSize: '20px' }}>
              Your Score: <strong>{score}</strong> out of <strong>{quizQuestions.length}</strong>
              ({Math.round((score / quizQuestions.length) * 100)}%)
            </p>
            
            <div style={{ marginTop: '20px' }}>
              <button 
                onClick={resetQuiz}
                style={{
                  padding: '10px 20px',
                  backgroundColor: '#007bff',
                  color: 'white',
                  border: 'none',
                  borderRadius: '5px',
                  cursor: 'pointer',
                  marginRight: '10px'
                }}
              >
                Create New Quiz
              </button>
              
              <button 
                onClick={() => {
                  setPdfQuestions([]);
                  resetQuiz();
                }}
                style={{
                  padding: '10px 20px',
                  backgroundColor: '#6c757d',
                  color: 'white',
                  border: 'none',
                  borderRadius: '5px',
                  cursor: 'pointer'
                }}
              >
                Upload New PDF
              </button>
            </div>
          </div>
        )}
        
        {/* Questions */}
        {quizQuestions.map((question, index) => (
          <div 
            key={index}
            style={{ 
              marginBottom: '30px', 
              padding: '15px',
              border: '1px solid #ddd',
              borderRadius: '5px'
            }}
          >
            <div style={{ 
              padding: '10px', 
              backgroundColor: '#f0f0f0', 
              marginBottom: '15px',
              borderRadius: '5px',
              fontWeight: 'bold'
            }}>
              Question {index + 1}
              {question.id && ` (Q.${question.id})`}
            </div>
            
            <div style={{ marginBottom: '15px' }}>
              {question.question}
              
              {/* Table */}
              {question.has_table && question.table_html && (
                <div 
                  dangerouslySetInnerHTML={{ __html: question.table_html }}
                  style={{ 
                    margin: '15px 0', 
                    overflowX: 'auto',
                    padding: '10px',
                    border: '1px solid #ddd',
                    borderRadius: '5px'
                  }}
                />
              )}
            </div>
            
            {/* Options */}
            <div>
              {Object.entries(question.options || {}).map(([opt, text]) => (
                <div 
                  key={opt}
                  onClick={() => !quizSubmitted && selectAnswer(index, opt)}
                  style={{
                    padding: '10px',
                    marginBottom: '10px',
                    border: '1px solid #ddd',
                    borderRadius: '5px',
                    backgroundColor: userAnswers[index] === opt ? '#e3f2fd' : 'white',
                    cursor: quizSubmitted ? 'default' : 'pointer'
                  }}
                >
                  <strong>{opt}.</strong> {text}
                  
                  {/* Show correct/incorrect indicators in results mode */}
                  {quizSubmitted && userAnswers[index] === opt && (
                    <span style={{ 
                      float: 'right',
                      color: opt === question.correct ? 'green' : 'red'
                    }}>
                      {opt === question.correct ? '✓' : '✗'}
                    </span>
                  )}
                  
                  {/* Highlight correct answer in results mode */}
                  {quizSubmitted && opt === question.correct && userAnswers[index] !== opt && (
                    <span style={{ float: 'right', color: 'green' }}>✓ Correct</span>
                  )}
                </div>
              ))}
            </div>
            
            {/* Show answer explanation only in results mode */}
            {quizSubmitted && (
              <div style={{ 
                marginTop: '15px', 
                padding: '10px', 
                backgroundColor: '#fff3e0',
                borderRadius: '5px' 
              }}>
                <strong>Correct Answer:</strong> {question.correct}
                
                {question.explanation && (
                  <div style={{ marginTop: '10px' }}>
                    <strong>Explanation:</strong> {question.explanation}
                  </div>
                )}
                
                {question.things_to_remember && question.things_to_remember.length > 0 && (
                  <div style={{ marginTop: '10px' }}>
                    <strong>Things to Remember:</strong>
                    <ul>
                      {question.things_to_remember.map((item, i) => (
                        <li key={i}>{item}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
        
        {/* Submit button (only shown when not submitted) */}
        {!quizSubmitted && (
          <div style={{ 
            marginTop: '20px', 
            marginBottom: '40px',
            textAlign: 'center' 
          }}>
            <button 
              onClick={submitQuiz}
              disabled={Object.keys(userAnswers).length < quizQuestions.length}
              style={{
                padding: '10px 20px',
                backgroundColor: Object.keys(userAnswers).length < quizQuestions.length ? '#6c757d' : '#007bff',
                color: 'white',
                border: 'none',
                borderRadius: '5px',
                cursor: Object.keys(userAnswers).length < quizQuestions.length ? 'not-allowed' : 'pointer'
              }}
            >
              Submit Quiz
            </button>
            
            {Object.keys(userAnswers).length < quizQuestions.length && (
              <p style={{ color: 'red', marginTop: '10px' }}>
                Please answer all questions before submitting.
              </p>
            )}
          </div>
        )}
      </div>
    </MathJaxContext>
  );
}

export default App;

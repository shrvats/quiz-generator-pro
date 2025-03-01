import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { MathJax } from 'better-react-mathjax';

// Backend URL - this should match your actual backend URL
const BACKEND_URL = "https://quiz-generator-pro.onrender.com";

export default function QuizRenderer() {
  // States for questions and quiz
  const [allQuestions, setAllQuestions] = useState([]);
  const [activeQuiz, setActiveQuiz] = useState([]);
  const [numQuestions, setNumQuestions] = useState(10);
  const [selectedAnswers, setSelectedAnswers] = useState({});
  const [showResults, setShowResults] = useState(false);
  const [score, setScore] = useState(0);
  
  // UI states
  const [currentScreen, setCurrentScreen] = useState('upload'); // 'upload', 'configure', 'quiz'
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [backendStatus, setBackendStatus] = useState('Checking...');

  // Check backend health on load
  useEffect(() => {
    fetch(`${BACKEND_URL}/health`)
      .then(res => res.ok ? res.json() : Promise.reject())
      .then(data => setBackendStatus('Connected ✅'))
      .catch(() => setBackendStatus('Disconnected ❌'));
  }, []);

  // Handle file upload
  const handleFileUpload = async (e) => {
    const file = e.target.files[0];
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
          timeout: 180000 // 3 min timeout
        }
      );
      
      console.log("Received questions:", response.data);
      
      if (response.data.length === 0) {
        setError("No questions found in the PDF.");
      } else {
        setAllQuestions(response.data);
        setNumQuestions(Math.min(10, response.data.length));
        setCurrentScreen('configure');
      }
    } catch (err) {
      console.error("Upload error:", err);
      setError(`Upload failed: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  // Start quiz with selected number of questions
  const startQuiz = () => {
    // Get random questions
    const shuffled = [...allQuestions].sort(() => 0.5 - Math.random());
    const selected = shuffled.slice(0, numQuestions);
    
    setActiveQuiz(selected);
    setSelectedAnswers({});
    setShowResults(false);
    setCurrentScreen('quiz');
  };

  // Handle selecting an answer
  const selectAnswer = (questionIndex, option) => {
    setSelectedAnswers(prev => ({
      ...prev,
      [questionIndex]: option
    }));
  };

  // Submit quiz and calculate score
  const submitQuiz = () => {
    let correctCount = 0;
    
    activeQuiz.forEach((question, index) => {
      if (selectedAnswers[index] === question.correct) {
        correctCount++;
      }
    });
    
    setScore(correctCount);
    setShowResults(true);
  };

  // Reset quiz
  const resetQuiz = () => {
    setCurrentScreen('configure');
    setSelectedAnswers({});
    setShowResults(false);
  };

  // Upload screen
  if (currentScreen === 'upload') {
    return (
      <div className="container">
        <div style={{
          background: backendStatus.includes('Connected') ? '#e8f5e9' : '#ffebee',
          padding: '10px',
          borderRadius: '4px',
          marginBottom: '20px'
        }}>
          <p><strong>Backend Status:</strong> {backendStatus}</p>
        </div>
        
        <div className="upload-section">
          <h2>Upload PDF</h2>
          <p>Upload a PDF file containing quiz questions.</p>
          
          <input 
            type="file" 
            accept=".pdf" 
            onChange={handleFileUpload}
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
          
          {loading && <p>Processing PDF... Please wait</p>}
          
          {error && (
            <div style={{
              color: 'red',
              padding: '15px',
              backgroundColor: '#ffebee',
              borderRadius: '4px',
              marginBottom: '20px'
            }}>
              <p><strong>Error:</strong> {error}</p>
            </div>
          )}
        </div>
      </div>
    );
  }

  // Configure screen
  if (currentScreen === 'configure') {
    return (
      <div className="container">
        <h2>Quiz Configuration</h2>
        <p>Successfully extracted {allQuestions.length} questions from your PDF.</p>
        
        <div style={{ margin: '20px 0' }}>
          <label htmlFor="numQuestions" style={{ display: 'block', marginBottom: '10px' }}>
            Number of questions in quiz: <strong>{numQuestions}</strong>
          </label>
          <input 
            type="range" 
            id="numQuestions"
            min="1"
            max={Math.min(25, allQuestions.length)}
            value={numQuestions}
            onChange={(e) => setNumQuestions(parseInt(e.target.value))}
            style={{ width: '100%' }}
          />
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span>1</span>
            <span>{Math.min(25, allQuestions.length)}</span>
          </div>
        </div>
        
        <button 
          onClick={startQuiz}
          style={{
            backgroundColor: '#1a237e',
            color: 'white',
            padding: '12px 24px',
            border: 'none',
            borderRadius: '4px',
            fontSize: '16px',
            cursor: 'pointer'
          }}
        >
          Start Quiz with {numQuestions} Questions
        </button>
      </div>
    );
  }

  // Quiz screen
  return (
    <div className="container">
      <div style={{ 
        display: 'flex', 
        justifyContent: 'space-between', 
        alignItems: 'center',
        marginBottom: '20px',
        padding: '15px',
        backgroundColor: '#f0f0f0',
        borderRadius: '8px'
      }}>
        <h3 style={{ margin: 0 }}>Quiz ({activeQuiz.length} Questions)</h3>
        <div>
          <span style={{ marginRight: '15px' }}>
            Answered: {Object.keys(selectedAnswers).length} of {activeQuiz.length}
          </span>
          <button 
            onClick={submitQuiz}
            disabled={Object.keys(selectedAnswers).length < activeQuiz.length}
            style={{
              backgroundColor: Object.keys(selectedAnswers).length < activeQuiz.length ? '#ccc' : '#1a237e',
              color: 'white',
              padding: '8px 16px',
              border: 'none',
              borderRadius: '4px',
              cursor: Object.keys(selectedAnswers).length < activeQuiz.length ? 'not-allowed' : 'pointer'
            }}
          >
            Submit Quiz
          </button>
        </div>
      </div>
      
      {/* Show results */}
      {showResults && (
        <div style={{ 
          padding: '20px',
          backgroundColor: '#e8f5e9',
          borderRadius: '8px',
          marginBottom: '30px',
          textAlign: 'center'
        }}>
          <h2>Quiz Results</h2>
          <div style={{ fontSize: '24px', margin: '15px 0' }}>
            Your Score: <strong>{score}</strong> out of <strong>{activeQuiz.length}</strong>
            <span style={{ marginLeft: '10px' }}>
              ({Math.round((score / activeQuiz.length) * 100)}%)
            </span>
          </div>
          
          <button 
            onClick={resetQuiz}
            style={{
              backgroundColor: '#1a237e',
              color: 'white',
              padding: '10px 20px',
              border: 'none',
              borderRadius: '4px',
              margin: '10px',
              cursor: 'pointer'
            }}
          >
            Try Again
          </button>
        </div>
      )}
      
      {/* Questions */}
      <div className="quiz-grid">
        {activeQuiz.map((question, idx) => (
          <div key={idx} className="card" style={{ 
            marginBottom: '30px',
            padding: '0',
            background: 'white',
            borderRadius: '8px',
            boxShadow: '0 2px 8px rgba(0,0,0,0.1)',
            overflow: 'hidden'
          }}>
            <div style={{
              padding: '10px 15px',
              backgroundColor: '#f0f0f0',
              borderBottom: '2px solid #1a237e'
            }}>
              <strong>Question {idx + 1}</strong>
              {question.id && <span style={{ marginLeft: '10px', color: '#666' }}>(Q.{question.id})</span>}
            </div>
            
            <div style={{ padding: '15px' }}>
              <div dangerouslySetInnerHTML={{ __html: question.question }} />
              
              {/* Table */}
              {question.has_table && question.table_html && (
                <div 
                  dangerouslySetInnerHTML={{ __html: question.table_html }}
                  style={{ 
                    margin: '15px 0', 
                    overflowX: 'auto',
                    border: '1px solid #ddd',
                    borderRadius: '4px',
                    padding: '10px'
                  }}
                />
              )}
            </div>
            
            {/* Options */}
            <div style={{ padding: '15px' }}>
              {Object.entries(question.options || {}).map(([opt, text]) => (
                <div 
                  key={opt} 
                  onClick={() => selectAnswer(idx, opt)}
                  style={{
                    padding: '10px 15px',
                    margin: '10px 0',
                    border: '1px solid #ddd',
                    borderRadius: '4px',
                    backgroundColor: selectedAnswers[idx] === opt ? '#e3f2fd' : 'white',
                    cursor: 'pointer',
                    transition: 'background-color 0.2s ease'
                  }}
                >
                  <strong>{opt}.</strong> {text}
                </div>
              ))}
            </div>
            
            {/* Show answer section after submission */}
            {showResults && (
              <div style={{
                padding: '15px',
                margin: '10px 15px',
                backgroundColor: '#fff3e0',
                borderRadius: '4px'
              }}>
                <strong>Correct Answer:</strong> {question.correct || "Not specified"}
                
                {question.explanation && (
                  <div style={{ marginTop: '10px' }}>
                    <strong>Explanation:</strong> {question.explanation}
                  </div>
                )}
                
                {question.things_to_remember && question.things_to_remember.length > 0 && (
                  <div style={{
                    marginTop: '15px',
                    padding: '10px',
                    backgroundColor: '#f5f5f5',
                    borderRadius: '4px'
                  }}>
                    <strong>Things to Remember:</strong>
                    <ul style={{ marginTop: '5px', paddingLeft: '20px' }}>
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
      </div>
      
      {/* Submit button at bottom */}
      {!showResults && (
        <div style={{ textAlign: 'center', marginTop: '30px', marginBottom: '50px' }}>
          <button 
            onClick={submitQuiz}
            disabled={Object.keys(selectedAnswers).length < activeQuiz.length}
            style={{
              backgroundColor: Object.keys(selectedAnswers).length < activeQuiz.length ? '#ccc' : '#1a237e',
              color: 'white',
              padding: '12px 24px',
              border: 'none',
              borderRadius: '4px',
              fontSize: '16px',
              cursor: Object.keys(selectedAnswers).length < activeQuiz.length ? 'not-allowed' : 'pointer'
            }}
          >
            Submit Quiz
          </button>
          
          {Object.keys(selectedAnswers).length < activeQuiz.length && (
            <p style={{ color: '#f44336', marginTop: '10px' }}>
              Please answer all questions before submitting.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

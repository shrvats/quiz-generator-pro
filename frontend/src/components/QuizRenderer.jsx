import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { MathJax } from 'better-react-mathjax';

// Backend URL
const BACKEND_URL = "https://quiz-generator-pro.onrender.com";
const MAX_TIMEOUT = 180000; // 3 minutes timeout

export default function QuizRenderer() {
  // Main states
  const [allQuestions, setAllQuestions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [backendStatus, setBackendStatus] = useState('Checking...');
  
  // Quiz mode states
  const [quizMode, setQuizMode] = useState(false);
  const [quizQuestions, setQuizQuestions] = useState([]);
  const [numQuestions, setNumQuestions] = useState(10);
  const [selectedAnswers, setSelectedAnswers] = useState({});
  const [showResults, setShowResults] = useState(false);
  const [score, setScore] = useState(0);
  
  // Processing states
  const [processingTime, setProcessingTime] = useState(0);
  const [processingTimer, setProcessingTimer] = useState(null);
  const [uploadProgress, setUploadProgress] = useState(0);

  // Check backend health on load
  useEffect(() => {
    fetch(`${BACKEND_URL}/health`)
      .then(res => res.ok ? res.json() : Promise.reject(`Status: ${res.status}`))
      .then(data => setBackendStatus('Connected ✅'))
      .catch(err => setBackendStatus(`Failed to connect ❌ (${err})`));
  }, []);

  // Cleanup timer on unmount
  useEffect(() => {
    return () => {
      if (processingTimer) clearInterval(processingTimer);
    };
  }, [processingTimer]);

  // Handle file upload
  const handleFile = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    
    // Reset states
    setLoading(true);
    setError(null);
    setProcessingTime(0);
    setUploadProgress(0);
    setAllQuestions([]);
    setQuizMode(false);
    setQuizQuestions([]);
    setSelectedAnswers({});
    setShowResults(false);
    
    // Start timer
    const timer = setInterval(() => setProcessingTime(prev => prev + 1), 1000);
    setProcessingTimer(timer);
    
    try {
      // Create form data
      const formData = new FormData();
      formData.append('file', file);
      
      // Upload and process file
      const { data } = await axios.post(
        `${BACKEND_URL}/process`,
        formData,
        { 
          headers: { 'Content-Type': 'multipart/form-data' },
          timeout: MAX_TIMEOUT,
          onUploadProgress: (progressEvent) => {
            const percentCompleted = Math.round((progressEvent.loaded * 100) / progressEvent.total);
            setUploadProgress(percentCompleted);
          }
        }
      );
      
      console.log("Received quiz data:", data);
      
      if (data.length === 0) {
        setError("No questions were extracted from the PDF.");
      } else {
        setAllQuestions(data);
        setNumQuestions(Math.min(10, data.length)); // Default to 10 questions or less if fewer available
      }
    } catch (err) {
      console.error('Upload failed:', err);
      setError(`Upload failed: ${err.message || 'Unknown error'}`);
    } finally {
      setLoading(false);
      clearInterval(timer);
      setProcessingTimer(null);
    }
  };

  // Start quiz with selected number of questions
  const startQuiz = () => {
    // Shuffle and take numQuestions from allQuestions
    const shuffled = [...allQuestions].sort(() => 0.5 - Math.random());
    const selected = shuffled.slice(0, numQuestions);
    
    setQuizQuestions(selected);
    setQuizMode(true);
    setSelectedAnswers({});
    setShowResults(false);
  };

  // Handle answer selection
  const handleAnswerSelect = (questionIndex, option) => {
    setSelectedAnswers(prev => ({
      ...prev,
      [questionIndex]: option
    }));
  };

  // Submit quiz and calculate score
  const submitQuiz = () => {
    let correctCount = 0;
    
    quizQuestions.forEach((question, index) => {
      const userAnswer = selectedAnswers[index];
      const correctAnswer = question.correct;
      
      if (userAnswer === correctAnswer) {
        correctCount++;
      }
    });
    
    setScore(correctCount);
    setShowResults(true);
  };

  // Render configuration screen
  const renderConfigScreen = () => (
    <div style={{ backgroundColor: '#f5f5f5', padding: '20px', borderRadius: '8px', marginBottom: '20px' }}>
      <h2>Quiz Configuration</h2>
      <p>Successfully extracted {allQuestions.length} questions from your PDF.</p>
      
      <div style={{ margin: '20px 0' }}>
        <label htmlFor="numQuestions" style={{ display: 'block', marginBottom: '10px' }}>
          Number of questions in quiz (1-{Math.min(25, allQuestions.length)}):
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
          <span>{numQuestions}</span>
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

  // Render quiz questions
  const renderQuizQuestions = () => (
    <div>
      <div style={{ 
        display: 'flex', 
        justifyContent: 'space-between', 
        alignItems: 'center',
        marginBottom: '20px',
        padding: '15px',
        backgroundColor: '#f0f0f0',
        borderRadius: '8px'
      }}>
        <h2 style={{ margin: 0 }}>Quiz ({quizQuestions.length} Questions)</h2>
        <div>
          <span style={{ marginRight: '15px' }}>
            Answered: {Object.keys(selectedAnswers).length} of {quizQuestions.length}
          </span>
          <button 
            onClick={submitQuiz}
            disabled={Object.keys(selectedAnswers).length < quizQuestions.length}
            style={{
              backgroundColor: Object.keys(selectedAnswers).length < quizQuestions.length ? '#ccc' : '#1a237e',
              color: 'white',
              padding: '8px 16px',
              border: 'none',
              borderRadius: '4px',
              cursor: Object.keys(selectedAnswers).length < quizQuestions.length ? 'not-allowed' : 'pointer'
            }}
          >
            Submit Quiz
          </button>
        </div>
      </div>
      
      <div className="quiz-grid">
        {quizQuestions.map((question, idx) => (
          <div key={idx} className="card" style={{ 
            marginBottom: '30px',
            background: 'white',
            borderRadius: '8px',
            boxShadow: '0 2px 8px rgba(0,0,0,0.1)'
          }}>
            <div style={{
              padding: '10px 15px',
              backgroundColor: '#f0f0f0',
              borderTopLeftRadius: '8px',
              borderTopRightRadius: '8px',
              borderBottom: '2px solid #1a237e'
            }}>
              <strong>Question {idx + 1}</strong>
              {question.id && <span style={{ marginLeft: '10px', color: '#666' }}>(Q.{question.id})</span>}
            </div>
            
            <div style={{ padding: '15px' }}>
              {question.question}
              
              {/* Render table if present */}
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
            
            <div style={{ padding: '15px' }}>
              {Object.entries(question.options || {}).length > 0 ? (
                Object.entries(question.options).map(([opt, text]) => (
                  <div 
                    key={opt} 
                    onClick={() => handleAnswerSelect(idx, opt)}
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
                ))
              ) : (
                <p style={{ color: '#757575', fontStyle: 'italic' }}>No options found for this question</p>
              )}
            </div>
            
            {/* Show answer only in results mode */}
            {showResults && (
              <div style={{
                padding: '15px',
                margin: '10px 15px',
                backgroundColor: '#e8f5e9',
                borderRadius: '4px'
              }}>
                <strong>Correct Answer:</strong> {question.correct || "Not specified"}
                
                {/* Show explanation if available */}
                {question.explanation && (
                  <div style={{ marginTop: '10px' }}>
                    <strong>Explanation:</strong> {question.explanation}
                  </div>
                )}
                
                {/* Show "Things to Remember" section if available */}
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
            disabled={Object.keys(selectedAnswers).length < quizQuestions.length}
            style={{
              backgroundColor: Object.keys(selectedAnswers).length < quizQuestions.length ? '#ccc' : '#1a237e',
              color: 'white',
              padding: '12px 24px',
              border: 'none',
              borderRadius: '4px',
              fontSize: '16px',
              cursor: Object.keys(selectedAnswers).length < quizQuestions.length ? 'not-allowed' : 'pointer'
            }}
          >
            Submit Quiz
          </button>
          
          {Object.keys(selectedAnswers).length < quizQuestions.length && (
            <p style={{ color: '#f44336', marginTop: '10px' }}>
              Please answer all questions before submitting.
            </p>
          )}
        </div>
      )}
      
      {/* Results summary */}
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
            Your Score: <strong>{score}</strong> out of <strong>{quizQuestions.length}</strong>
            <span style={{ marginLeft: '10px' }}>
              ({Math.round((score / quizQuestions.length) * 100)}%)
            </span>
          </div>
          
          <div>
            <button 
              onClick={() => {
                setQuizMode(false);
                setShowResults(false);
              }}
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
              Create New Quiz
            </button>
            
            <button 
              onClick={() => {
                setAllQuestions([]);
                setQuizMode(false);
                setShowResults(false);
              }}
              style={{
                backgroundColor: '#f5f5f5',
                color: '#333',
                padding: '10px 20px',
                border: '1px solid #ddd',
                borderRadius: '4px',
                margin: '10px',
                cursor: 'pointer'
              }}
            >
              Upload New PDF
            </button>
          </div>
        </div>
      )}
    </div>
  );

  // Main render function
  return (
    <div className="container">
      <div style={{
        background: backendStatus.includes('Connected') ? '#e8f5e9' : '#ffebee',
        padding: '10px',
        borderRadius: '4px',
        marginBottom: '20px'
      }}>
        <p><strong>Backend Status:</strong> {backendStatus}</p>
        <p><small>Using direct backend connection to {BACKEND_URL}</small></p>
      </div>
      
      {/* Upload Section - Only show if not in quiz mode */}
      {!quizMode && !allQuestions.length && (
        <div style={{
          marginBottom: '2rem',
          padding: '1.5rem',
          background: 'white',
          borderRadius: '8px',
          boxShadow: '0 2px 8px rgba(0,0,0,0.1)'
        }}>
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
                {uploadProgress < 100 ? 
                  `Uploading PDF (${uploadProgress}%)...` : 
                  `Processing PDF... (${processingTime} seconds elapsed)`}
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
                  width: `${uploadProgress < 100 ? uploadProgress : Math.min((processingTime / 60) * 100, 95)}%`,
                  height: '100%',
                  backgroundColor: '#1a237e',
                  transition: 'width 0.5s ease',
                  animation: uploadProgress === 100 ? 'pulse 2s infinite' : 'none'
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
            </div>
          )}
        </div>
      )}
      
      {/* Configuration Screen - Show after successful upload and not in quiz mode */}
      {!quizMode && allQuestions.length > 0 && renderConfigScreen()}
      
      {/* Quiz Screen - Show in quiz mode */}
      {quizMode && renderQuizQuestions()}
    </div>
  );
}

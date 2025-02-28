import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { MathJax } from 'better-react-mathjax';

// Correct backend URL
const BACKEND_URL = "https://quiz-generator-pro.onrender.com";
const MAX_TIMEOUT = 180000; // 3 minutes timeout

export default function QuizRenderer() {
  const [allQuestions, setAllQuestions] = useState([]);
  const [quiz, setQuiz] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [backendStatus, setBackendStatus] = useState('Checking...');
  const [processingTime, setProcessingTime] = useState(0);
  const [processingTimer, setProcessingTimer] = useState(null);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [stage, setStage] = useState('idle'); // idle, uploading, processing, quiz, results
  const [numQuestions, setNumQuestions] = useState(10);
  const [selectedAnswers, setSelectedAnswers] = useState({});
  const [showResults, setShowResults] = useState(false);
  const [score, setScore] = useState(0);

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
    setAllQuestions([]);
    setQuiz([]);
    setSelectedAnswers({});
    setShowResults(false);
    
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
      setAllQuestions(data);
      setStage('configuring');
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

  const startQuiz = () => {
    // If we have fewer questions than requested, use all available
    const n = Math.min(numQuestions, allQuestions.length);
    
    // Shuffle and take n questions
    const shuffled = [...allQuestions].sort(() => 0.5 - Math.random());
    const selected = shuffled.slice(0, n);
    
    setQuiz(selected);
    setStage('quiz');
    setSelectedAnswers({});
    setShowResults(false);
  };

  const handleAnswerSelect = (questionIndex, option) => {
    setSelectedAnswers(prev => ({
      ...prev,
      [questionIndex]: option
    }));
  };

  const submitQuiz = () => {
    let correctCount = 0;
    
    quiz.forEach((question, index) => {
      const userAnswer = selectedAnswers[index];
      // Extract just the letter from correct answer (if it's in that format)
      let correctAnswer = question.correct;
      const letterMatch = correctAnswer.match(/^([A-D])/);
      if (letterMatch) {
        correctAnswer = letterMatch[1];
      }
      
      if (userAnswer && userAnswer === correctAnswer) {
        correctCount++;
      }
    });
    
    setScore(correctCount);
    setShowResults(true);
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

  const renderQuestionContent = (question) => {
    return (
      <>
        <div dangerouslySetInnerHTML={{ __html: question.question }} />
        
        {question.has_math && question.math?.map((formula, i) => (
          <div key={i} style={{ margin: '10px 0' }}>
            <MathJax dynamic>{`\\(${formula}\\)`}</MathJax>
          </div>
        ))}
        
        {question.tables?.map((table, i) => (
          <div key={i} className="table-container" style={{ 
            margin: '15px 0', 
            overflowX: 'auto',
            border: '1px solid #ddd',
            borderRadius: '4px'
          }}>
            <div dangerouslySetInnerHTML={{ __html: table }} />
          </div>
        ))}
      </>
    );
  };

  // Render the configuration screen
  const renderConfigScreen = () => {
    return (
      <div className="config-screen" style={{ 
        backgroundColor: '#f5f5f5', 
        padding: '20px',
        borderRadius: '8px',
        marginBottom: '20px'
      }}>
        <h2>Quiz Configuration</h2>
        <p>Successfully extracted {allQuestions.length} questions from your PDF.</p>
        
        <div style={{ margin: '20px 0' }}>
          <label htmlFor="numQuestions" style={{ display: 'block', marginBottom: '10px' }}>
            Number of questions in quiz (1-25):
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
  };

  // Render quiz questions
  const renderQuiz = () => {
    return (
      <div className="quiz-container">
        <div style={{ 
          display: 'flex', 
          justifyContent: 'space-between', 
          alignItems: 'center',
          marginBottom: '20px',
          padding: '15px',
          backgroundColor: '#f0f0f0',
          borderRadius: '8px'
        }}>
          <h2 style={{ margin: 0 }}>Quiz ({quiz.length} Questions)</h2>
          <div>
            <span style={{ marginRight: '15px' }}>
              Answered: {Object.keys(selectedAnswers).length} of {quiz.length}
            </span>
            <button 
              onClick={submitQuiz}
              disabled={Object.keys(selectedAnswers).length < quiz.length}
              style={{
                backgroundColor: Object.keys(selectedAnswers).length < quiz.length ? '#ccc' : '#1a237e',
                color: 'white',
                padding: '8px 16px',
                border: 'none',
                borderRadius: '4px',
                cursor: Object.keys(selectedAnswers).length < quiz.length ? 'not-allowed' : 'pointer'
              }}
            >
              Submit Quiz
            </button>
          </div>
        </div>
        
        <div className="quiz-grid">
          {quiz.map((question, idx) => (
            <div key={idx} className="card" style={{ marginBottom: '30px' }}>
              <div className="question-header" style={{
                padding: '10px 15px',
                backgroundColor: '#f0f0f0',
                borderTopLeftRadius: '8px',
                borderTopRightRadius: '8px',
                borderBottom: '2px solid #1a237e'
              }}>
                <strong>Question {idx + 1}</strong>
              </div>
              
              <div className="question" style={{ padding: '15px' }}>
                {renderQuestionContent(question)}
              </div>
              
              <div className="options" style={{ padding: '15px' }}>
                {Object.entries(question.options || {}).length > 0 ? (
                  Object.entries(question.options).map(([opt, text]) => (
                    <div 
                      key={opt} 
                      className="option" 
                      style={{
                        padding: '10px 15px',
                        margin: '10px 0',
                        border: '1px solid #ddd',
                        borderRadius: '4px',
                        backgroundColor: selectedAnswers[idx] === opt ? '#e3f2fd' : 'white',
                        cursor: 'pointer',
                        transition: 'background-color 0.2s ease'
                      }}
                      onClick={() => handleAnswerSelect(idx, opt)}
                    >
                      <strong>{opt}.</strong> {text}
                    </div>
                  ))
                ) : (
                  <p style={{ color: '#757575', fontStyle: 'italic' }}>No options found for this question</p>
                )}
              </div>
            </div>
          ))}
        </div>
        
        <div style={{ textAlign: 'center', marginTop: '30px', marginBottom: '50px' }}>
          <button 
            onClick={submitQuiz}
            disabled={Object.keys(selectedAnswers).length < quiz.length}
            style={{
              backgroundColor: Object.keys(selectedAnswers).length < quiz.length ? '#ccc' : '#1a237e',
              color: 'white',
              padding: '12px 24px',
              border: 'none',
              borderRadius: '4px',
              fontSize: '16px',
              cursor: Object.keys(selectedAnswers).length < quiz.length ? 'not-allowed' : 'pointer'
            }}
          >
            Submit Quiz
          </button>
          
          {Object.keys(selectedAnswers).length < quiz.length && (
            <p style={{ color: '#f44336', marginTop: '10px' }}>
              Please answer all questions before submitting.
            </p>
          )}
        </div>
      </div>
    );
  };

  // Render quiz results
  const renderResults = () => {
    return (
      <div className="results-container">
        <div style={{ 
          padding: '20px',
          backgroundColor: '#e8f5e9',
          borderRadius: '8px',
          marginBottom: '30px',
          textAlign: 'center'
        }}>
          <h2>Quiz Results</h2>
          <div style={{ fontSize: '24px', margin: '15px 0' }}>
            Your Score: <strong>{score}</strong> out of <strong>{quiz.length}</strong>
            <span style={{ marginLeft: '10px' }}>
              ({Math.round((score / quiz.length) * 100)}%)
            </span>
          </div>
          
          <button 
            onClick={() => {
              setShowResults(false);
              setStage('configuring');
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
            Try Again
          </button>
          
          <button 
            onClick={() => {
              setAllQuestions([]);
              setQuiz([]);
              setStage('idle');
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
        
        <div className="quiz-grid">
          {quiz.map((question, idx) => {
            const userAnswer = selectedAnswers[idx];
            let correctAnswer = question.correct;
            const letterMatch = correctAnswer.match(/^([A-D])/);
            if (letterMatch) {
              correctAnswer = letterMatch[1];
            }
            
            const isCorrect = userAnswer === correctAnswer;
            
            return (
              <div 
                key={idx} 
                className="card" 
                style={{ 
                  marginBottom: '30px',
                  border: '1px solid',
                  borderColor: isCorrect ? '#4caf50' : '#f44336',
                  borderRadius: '8px'
                }}
              >
                <div className="question-header" style={{
                  padding: '10px 15px',
                  backgroundColor: isCorrect ? '#e8f5e9' : '#ffebee',
                  borderTopLeftRadius: '8px',
                  borderTopRightRadius: '8px',
                  borderBottom: '2px solid',
                  borderBottomColor: isCorrect ? '#4caf50' : '#f44336',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center'
                }}>
                  <strong>Question {idx + 1}</strong>
                  <span style={{ 
                    padding: '3px 8px', 
                    borderRadius: '4px',
                    backgroundColor: isCorrect ? '#4caf50' : '#f44336',
                    color: 'white',
                    fontSize: '14px'
                  }}>
                    {isCorrect ? 'Correct' : 'Incorrect'}
                  </span>
                </div>
                
                <div className="question" style={{ padding: '15px' }}>
                  {renderQuestionContent(question)}
                </div>
                
                <div className="options" style={{ padding: '15px' }}>
                  {Object.entries(question.options || {}).length > 0 ? (
                    Object.entries(question.options).map(([opt, text]) => {
                      const isSelected = userAnswer === opt;
                      const isCorrectOption = opt === correctAnswer;
                      
                      let backgroundColor = 'white';
                      if (isSelected && isCorrectOption) backgroundColor = '#e8f5e9';
                      else if (isSelected && !isCorrectOption) backgroundColor = '#ffebee';
                      else if (!isSelected && isCorrectOption) backgroundColor = '#e8f5e9';
                      
                      return (
                        <div 
                          key={opt} 
                          className="option" 
                          style={{
                            padding: '10px 15px',
                            margin: '10px 0',
                            border: '1px solid #ddd',
                            borderRadius: '4px',
                            backgroundColor,
                            position: 'relative'
                          }}
                        >
                          <strong>{opt}.</strong> {text}
                          
                          {isSelected && isCorrectOption && (
                            <span style={{ 
                              position: 'absolute', 
                              right: '10px',
                              color: '#4caf50'
                            }}>✓</span>
                          )}
                          
                          {isSelected && !isCorrectOption && (
                            <span style={{ 
                              position: 'absolute', 
                              right: '10px',
                              color: '#f44336'
                            }}>✗</span>
                          )}
                          
                          {!isSelected && isCorrectOption && (
                            <span style={{ 
                              position: 'absolute', 
                              right: '10px',
                              color: '#4caf50'
                            }}>✓ (Correct answer)</span>
                          )}
                        </div>
                      );
                    })
                  ) : (
                    <p style={{ color: '#757575', fontStyle: 'italic' }}>No options found for this question</p>
                  )}
                </div>
                
                <div className="answer" style={{
                  padding: '15px',
                  margin: '10px 15px',
                  backgroundColor: '#fff3e0',
                  borderRadius: '4px'
                }}>
                  <strong>Correct Answer:</strong> {question.correct || "Not specified"}
                  {question.explanation && (
                    <div className="explanation" style={{
                      marginTop: '10px',
                      padding: '10px',
                      backgroundColor: '#f5f5f5',
                      borderRadius: '4px'
                    }}>
                      <strong>Things to Remember:</strong> 
                      <div dangerouslySetInnerHTML={{ __html: question.explanation }} />
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    );
  };

  // Main render function
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
      
      {/* Upload Section - Only show if not in quiz mode or results */}
      {(stage === 'idle' || stage === 'uploading' || stage === 'processing' || stage === 'error') && (
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
      )}
      
      {/* Configuration Screen */}
      {stage === 'configuring' && renderConfigScreen()}
      
      {/* Quiz Screen */}
      {stage === 'quiz' && !showResults && renderQuiz()}
      
      {/* Results Screen */}
      {stage === 'quiz' && showResults && renderResults()}
    </div>
  );
}

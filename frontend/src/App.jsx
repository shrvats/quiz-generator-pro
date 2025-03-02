import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { MathJaxContext, MathJax } from 'better-react-mathjax';

// Use the proxy by default to avoid CORS issues
const BACKEND_URL = "/api/proxy";

// QuizRenderer component (inlined to solve import issues)
function QuizRenderer() {
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
  const [quizStats, setQuizStats] = useState({
    totalQuestions: 0,
    answerableQuestions: 0,
    skippedQuestions: 0
  });
  
  // Processing states
  const [processingTime, setProcessingTime] = useState(0);
  const [processingTimer, setProcessingTimer] = useState(null);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [timeoutWarningShown, setTimeoutWarningShown] = useState(false);

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

  // Validate file size and type
  const validateFile = (file) => {
    const MAX_FILE_SIZE = 5 * 1024 * 1024; // 5MB
    
    if (!file.type.includes('pdf')) {
      return {
        valid: false,
        message: 'Please upload a PDF file.'
      };
    }
    
    if (file.size > MAX_FILE_SIZE) {
      return {
        valid: false,
        message: `File too large (${(file.size / 1024 / 1024).toFixed(1)}MB). Please upload a PDF smaller than 5MB.`
      };
    }
    
    return { valid: true };
  };

  // Handle file upload
  const handleFile = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    
    const validation = validateFile(file);
    if (!validation.valid) {
      setError(validation.message);
      return;
    }
    
    setLoading(true);
    setError(null);
    setProcessingTime(0);
    setUploadProgress(0);
    setAllQuestions([]);
    setQuizMode(false);
    setQuizQuestions([]);
    setSelectedAnswers({});
    setShowResults(false);
    setTimeoutWarningShown(false);
    
    const timer = setInterval(() => setProcessingTime(prev => prev + 1), 1000);
    setProcessingTimer(timer);
    
    const timeoutWarning = setTimeout(() => {
      if (loading) {
        setTimeoutWarningShown(true);
      }
    }, 40000);
    
    try {
      const formData = new FormData();
      formData.append('file', file);
      
      const { data } = await axios.post(
        `${BACKEND_URL}/process`,
        formData,
        { 
          headers: { 'Content-Type': 'multipart/form-data' },
          timeout: 55000,
          onUploadProgress: (progressEvent) => {
            const percentCompleted = Math.round((progressEvent.loaded * 100) / progressEvent.total);
            setUploadProgress(percentCompleted);
          }
        }
      );
      
      clearTimeout(timeoutWarning);
      console.log("Received quiz data:", data);
      
      if (data.length === 0) {
        setError("No questions were extracted from the PDF.");
      } else {
        setAllQuestions(data);
        setNumQuestions(Math.min(10, data.length));
      }
    } catch (err) {
      clearTimeout(timeoutWarning);
      console.error('Upload failed:', err);
      
      if (err.code === 'ECONNABORTED' || err.message.includes('timeout')) {
        setError(`Processing timeout: Your PDF may be too large or complex to process within the time limit. Please try a smaller PDF or one with fewer pages.`);
      } else if (err.response && err.response.status === 504) {
        setError(`Gateway Timeout: The server took too long to process your PDF. Try a smaller PDF or one with fewer pages.`);
      } else {
        setError(`Upload failed: ${err.message || 'Unknown error'}`);
      }
    } finally {
      setLoading(false);
      clearInterval(timer);
      setProcessingTimer(null);
    }
  };

  // Start quiz with selected number of questions
  const startQuiz = () => {
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

  // Check if all answerable questions are answered
  const areAllAnswerableQuestionsAnswered = () => {
    let allAnswered = true;
    
    quizQuestions.forEach((question, index) => {
      if (question.options && Object.keys(question.options).length > 0) {
        if (!selectedAnswers[index]) {
          allAnswered = false;
        }
      } else {
        if (!selectedAnswers[index]) {
          allAnswered = false;
        }
      }
    });
    
    return allAnswered;
  };

  // Submit quiz and calculate score
  const submitQuiz = () => {
    let correctCount = 0;
    let totalAnswerable = 0;
    
    quizQuestions.forEach((question, index) => {
      if (!question.options || Object.keys(question.options).length === 0) {
        return;
      }
      
      totalAnswerable++;
      const userAnswer = selectedAnswers[index];
      const correctAnswer = question.correct;
      
      if (userAnswer === correctAnswer && userAnswer !== 'skipped') {
        correctCount++;
      }
    });
    
    setScore(correctCount);
    setQuizStats({
      totalQuestions: quizQuestions.length,
      answerableQuestions: totalAnswerable,
      skippedQuestions: quizQuestions.length - totalAnswerable
    });
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
            disabled={!areAllAnswerableQuestionsAnswered()}
            style={{
              backgroundColor: !areAllAnswerableQuestionsAnswered() ? '#ccc' : '#1a237e',
              color: 'white',
              padding: '8px 16px',
              border: 'none',
              borderRadius: '4px',
              cursor: !areAllAnswerableQuestionsAnswered() ? 'not-allowed' : 'pointer'
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
                <div>
                  <p style={{ color: '#757575', fontStyle: 'italic' }}>No options found for this question</p>
                  <button
                    onClick={() => handleAnswerSelect(idx, 'skipped')}
                    style={{
                      padding: '10px 15px',
                      margin: '10px 0',
                      backgroundColor: selectedAnswers[idx] === 'skipped' ? '#ffebee' : '#f5f5f5',
                      border: '1px solid #ddd',
                      borderRadius: '4px',
                      cursor: 'pointer'
                    }}
                  >
                    Skip this question
                  </button>
                </div>
              )}
            </div>
            
            {showResults && (
              <div style={{
                padding: '15px',
                margin: '10px 15px',
                backgroundColor: '#e8f5e9',
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
      
      {!showResults && (
        <div style={{ textAlign: 'center', marginTop: '30px', marginBottom: '50px' }}>
          <button 
            onClick={submitQuiz}
            disabled={!areAllAnswerableQuestionsAnswered()}
            style={{
              backgroundColor: !areAllAnswerableQuestionsAnswered() ? '#ccc' : '#1a237e',
              color: 'white',
              padding: '12px 24px',
              border: 'none',
              borderRadius: '4px',
              fontSize: '16px',
              cursor: !areAllAnswerableQuestionsAnswered()


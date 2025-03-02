import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { MathJaxContext, MathJax } from 'better-react-mathjax';

// Backend URL - use environment variable or fallback to proxy path
const BACKEND_URL = "/api/proxy";
const MAX_TIMEOUT = 45000; // 45 seconds timeout (well under Vercel's 60s limit)

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
  
  // Section/Reading states
  const [availableSections, setAvailableSections] = useState([]);
  const [selectedSection, setSelectedSection] = useState(null);
  
  // PDF information states
  const [pdfInfo, setPdfInfo] = useState(null);
  const [pageRangeEnabled, setPageRangeEnabled] = useState(false);
  const [startPage, setStartPage] = useState(0);
  const [endPage, setEndPage] = useState(1);
  const [totalPages, setTotalPages] = useState(0);
  const [selectedFile, setSelectedFile] = useState(null);
  
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
    // Smaller max size (3MB) for more reliable processing
    const MAX_FILE_SIZE = 3 * 1024 * 1024;
    
    if (!file.type.includes('pdf')) {
      return {
        valid: false,
        message: 'Please upload a PDF file.'
      };
    }
    
    if (file.size > MAX_FILE_SIZE) {
      return {
        valid: false,
        message: `File too large (${(file.size / 1024 / 1024).toFixed(1)}MB). Please upload a PDF smaller than 3MB.`
      };
    }
    
    return { valid: true };
  };

  // Get PDF info to determine page count
  const getPdfInfo = async (file) => {
    try {
      const formData = new FormData();
      formData.append('file', file);
      
      const { data } = await axios.post(
        `${BACKEND_URL}/pdf-info`,
        formData,
        { 
          headers: { 'Content-Type': 'multipart/form-data' },
          timeout: 15000 // 15 seconds should be enough for metadata
        }
      );
      
      console.log("Received PDF info:", data);
      setPdfInfo(data);
      setTotalPages
(data.total_pages);
      setEndPage(data.total_pages - 1);
      setSelectedFile(file);
      
      return data;
    } catch (err) {
      console.error('Failed to get PDF info:', err);
      setError(`Failed to analyze PDF: ${err.message || 'Unknown error'}`);
      return null;
    }
  };

  // Handle file upload
  const handleFile = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    
    // Validate file
    const validation = validateFile(file);
    if (!validation.valid) {
      setError(validation.message);
      return;
    }
    
    // Reset states
    setError(null);
    setAllQuestions([]);
    setQuizMode(false);
    setQuizQuestions([]);
    setSelectedAnswers({});
    setShowResults(false);
    setTimeoutWarningShown(false);
    setAvailableSections([]);
    setSelectedSection(null);
    
    // Get PDF info first
    await getPdfInfo(file);
  };

  // Process PDF with optional page range
  const processPdf = async () => {
    if (!selectedFile) {
      setError("No file selected");
      return;
    }
    
    // Reset processing states
    setLoading(true);
    setError(null);
    setProcessingTime(0);
    setUploadProgress(0);
    
    // Start timer
    const timer = setInterval(() => setProcessingTime(prev => prev + 1), 1000);
    setProcessingTimer(timer);
    
    // Set timeout warning earlier (30 seconds)
    const timeoutWarning = setTimeout(() => {
      if (loading) {
        setTimeoutWarningShown(true);
      }
    }, 30000);
    
    try {
      // Create form data
      const formData = new FormData();
      formData.append('file', selectedFile);
      
      // Add page range parameters if enabled
      if (pageRangeEnabled) {
        formData.append('start_page', startPage);
        formData.append('end_page', endPage);
      }
      
      // Reduced timeout to prevent browser waiting too long
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
      
      clearTimeout(timeoutWarning);
      console.log("Received quiz data:", data);
      
      if (!data || !data.questions || data.questions.length === 0) {
        setError("No questions were extracted from the PDF.");
      } else {
        setAllQuestions(data.questions);
        setNumQuestions(Math.min(10, data.questions.length));
        
        // Set sections if available
        if (data.sections && data.sections.length > 0) {
          setAvailableSections(data.sections);
        }
      }
    } catch (err) {
      clearTimeout(timeoutWarning);
      console.error('Upload failed:', err);
      
      // Handle different error types
      if (err.code === 'ECONNABORTED' || err.message.includes('timeout')) {
        setError(`Processing timeout: Please try a smaller PDF (under 3MB) or one with fewer pages.`);
      } else if (err.response && err.response.status === 408) {
        setError(`Processing timeout: The server took too long to process your PDF. Try a smaller PDF.`);
      } else {
        setError(`Upload failed: ${err.message || 'Unknown error'}. Try a smaller PDF or check your connection.`);
      }
    } finally {
      setLoading(false);
      clearInterval(timer);
      setProcessingTimer(null);
    }
  };

  // Filter questions by selected section
  const getFilteredQuestions = () => {
    if (!selectedSection || !availableSections.length) {
      return allQuestions; // Return all questions if no section selected
    }
    
    // Find the section object
    const section = availableSections.find(s => s.name === selectedSection);
    
    if (section && section.questions && section.questions.length > 0) {
      return section.questions;
    }
    
    return allQuestions;
  };

  // Start quiz with selected number of questions
  const startQuiz = () => {
    // Get questions filtered by section if applicable
    const filteredQuestions = getFilteredQuestions();
    
    // Shuffle and take numQuestions from filtered questions
    const shuffled = [...filteredQuestions].sort(() => 0.5 - Math.random());
    const selected = shuffled.slice(0, numQuestions);
    
    // Pre-mark questions without options as skipped
    const initialAnswers = {};
    selected.forEach((question, index) => {
      if (!question.options || Object.keys(question.options || {}).length === 0) {
        initialAnswers[index] = 'skipped';
      }
    });
    
    setQuizQuestions(selected);
    setQuizMode(true);
    setSelectedAnswers(initialAnswers);
    setShowResults(false);
  };

  // Handle answer selection
  const handleAnswerSelect = (questionIndex, option) => {
    console.log(`Selected ${option} for question ${questionIndex}`);
    setSelectedAnswers(prev => ({
      ...prev,
      [questionIndex]: option
    }));
  };

  // Check if all questions have been answered or explicitly skipped
  const areAllQuestionsAddressed = () => {
    // If there are no questions, return false
    if (!quizQuestions || quizQuestions.length === 0) return false;
    
    // For each question, check if there's an answer
    for (let i = 0; i < quizQuestions.length; i++) {
      if (selectedAnswers[i] === undefined) {
        return false;
      }
    }
    
    return true;
  };

  // Submit quiz and calculate score
  const submitQuiz = () => {
    console.log("Submitting quiz with answers:", selectedAnswers);
    
    let correctCount = 0;
    let totalAnswerable = 0;
    let skippedCount = 0;
    
    quizQuestions.forEach((question, index) => {
      // Check if question has options
      const hasOptions = question.options && Object.keys(question.options || {}).length > 0;
      
      if (hasOptions) {
        totalAnswerable++;
        const userAnswer = selectedAnswers[index];
        const correctAnswer = question.correct;
        
        if (userAnswer === correctAnswer && userAnswer !== 'skipped') {
          correctCount++;
        }
      } else {
        skippedCount++;
      }
    });
    
    console.log(`Quiz stats: ${correctCount} correct out of ${totalAnswerable} answerable questions. ${skippedCount} questions skipped.`);
    
    // Calculate score based on answerable questions
    setScore(correctCount);
    
    // Store additional stats
    setQuizStats({
      totalQuestions: quizQuestions.length,
      answerableQuestions: totalAnswerable || 1, // Avoid division by zero
      skippedQuestions: skippedCount
    });
    
    // Show results
    setShowResults(true);
  };

  // Render PDF info and page range selection panel
  const renderPdfInfoPanel = () => (
    <div className="upload-section">
      <h2>PDF Information</h2>
      
      {pdfInfo && (
        <div>
          <p><strong>File:</strong> {selectedFile?.name}</p>
          <p><strong>Pages:</strong> {pdfInfo.total_pages}</p>
          <p><strong>Size:</strong> {pdfInfo.file_size_mb} MB</p>
          
          <div style={{ margin: '20px 0' }}>
            <label style={{ display: 'flex', alignItems: 'center', marginBottom: '10px' }}>
              <input 
                type="checkbox" 
                checked={pageRangeEnabled}
                onChange={(e) => setPageRangeEnabled(e.target.checked)}
                style={{ marginRight: '10px' }}
              />
              Process specific page range (useful for large PDFs)
            </label>
            
            {pageRangeEnabled && (
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginTop: '10px' }}>
                <div>
                  <label htmlFor="startPage" style={{ display: 'block', marginBottom: '5px' }}>Start Page:</label>
                  <input 
                    type="number" 
                    id="startPage"
                    min="0"
                    max={totalPages - 1}
                    value={startPage}
                    onChange={(e) => setStartPage(parseInt(e.target.value))}
                    style={{ width: '80px', padding: '8px' }}
                  />
                </div>
                
                <div>
                  <label htmlFor="endPage" style={{ display: 'block', marginBottom: '5px' }}>End Page:</label>
                  <input 
                    type="number" 
                    id="endPage"
                    min={startPage}
                    max={totalPages - 1}
                    value={endPage}
                    onChange={(e) => setEndPage(parseInt(e.target.value))}
                    style={{ width: '80px', padding: '8px' }}
                  />
                </div>
                
                <div style={{ marginTop: '24px', color: '#666' }}>
                  (Processing {pageRangeEnabled ? (endPage - startPage + 1) : totalPages} pages)
                </div>
              </div>
            )}
          </div>
          
          <button 
            onClick={processPdf}
            disabled={loading}
            className="btn primary-btn"
          >
            {loading ? 'Processing...' : 'Process PDF'}
          </button>
          
          <button 
            onClick={() => {
              setSelectedFile(null);
              setPdfInfo(null);
            }}
            disabled={loading}
            className="btn secondary-btn"
            style={{ marginLeft: '10px' }}
          >
            Cancel
          </button>
        </div>
      )}
      
      {loading && (
        <div className="progress-container" style={{ marginTop: '20px' }}>
          <p>
            {uploadProgress < 100 ? 
              `Uploading PDF (${uploadProgress}%)...` : 
              `Processing PDF... (${processingTime} seconds elapsed)`}
              
            {timeoutWarningShown && (
              <span className="timeout-warning"> 
                {' '}Processing taking longer than expected. This may time out.
              </span>
            )}
          </p>
          <div className="progress-bar-container">
            <div 
              className="progress-bar" 
              style={{
                width: `${uploadProgress < 100 ? uploadProgress : Math.min((processingTime / 60) * 100, 95)}%`,
                backgroundColor: timeoutWarningShown ? 'var(--error-red)' : 'var(--primary-blue)',
                animation: uploadProgress === 100 ? 'pulse 2s infinite' : 'none'
              }}
            ></div>
          </div>
        </div>
      )}
    </div>
  );

  // Render configuration screen
  const renderConfigScreen = () => (
    <div className="config-screen">
      <h2>Quiz Configuration</h2>
      <p>Successfully extracted {allQuestions.length} questions from your PDF.</p>
      
      {/* Section selector */}
      {availableSections.length > 0 && (
        <div style={{ marginBottom: '20px' }}>
          <label htmlFor="sectionSelector" style={{ display: 'block', marginBottom: '10px', fontWeight: 'bold' }}>
            Select Reading/Section:
          </label>
          <select 
            id="sectionSelector"
            value={selectedSection || ""}
            onChange={(e) => setSelectedSection(e.target.value || null)}
            className="section-selector"
          >
            <option value="">All Sections</option>
            {availableSections.map((section, idx) => (
              <option key={idx} value={section.name}>
                {section.name} ({section.questions?.length || 0} questions)
              </option>
            ))}
          </select>
        </div>
      )}
      
      {/* Number of questions slider */}
      <div className="slider-container">
        <label htmlFor="numQuestions" style={{ display: 'block', marginBottom: '10px', fontWeight: 'bold' }}>
          Number of questions in quiz (1-{Math.min(25, getFilteredQuestions().length)}):
        </label>
        <input 
          type="range" 
          id="numQuestions"
          min="1"
          max={Math.min(25, getFilteredQuestions().length)}
          value={numQuestions}
          onChange={(e) => setNumQuestions(parseInt(e.target.value))}
          className="range-input"
        />
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span>1</span>
          <span>{numQuestions}</span>
          <span>{Math.min(25, getFilteredQuestions().length)}</span>
        </div>
      </div>
      
      <button 
        onClick={startQuiz}
        className="btn primary-btn"
      >
        Start Quiz with {numQuestions} Questions
        {selectedSection && ` from "${selectedSection}"`}
      </button>
    </div>
  );

  // Render quiz questions
  const renderQuizQuestions = () => (
    <div className="quiz-container">
      <div className="quiz-header">
        <h2>Quiz ({quizQuestions.length} Questions)</h2>
        <div>
          <span style={{ marginRight: '15px' }}>
            Answered: {Object.keys(selectedAnswers).length} of {quizQuestions.length}
          </span>
          <button 
            onClick={submitQuiz}
            disabled={!areAllQuestionsAddressed()}
            className={`btn ${areAllQuestionsAddressed() ? 'primary-btn' : 'disabled-btn'}`}
          >
            Submit Quiz
          </button>
        </div>
      </div>
      
      {/* Instructions for questions without options */}
      <div className="instructions-box">
        <p><strong>Note:</strong> If a question has no options, use the "Skip this question" button.</p>
        <p>Questions without options are automatically marked as skipped.</p>
      </div>
      
      <div className="quiz-grid">
        {quizQuestions.map((question, idx) => (
          <div key={idx} className="card">
            <div className="card-header">
              <strong>Question {idx + 1}</strong>
              {question.id && <span className="question-id">(Q.{question.id})</span>}
              {selectedAnswers[idx] === 'skipped' && 
                <span className="skipped-badge">(Skipped)</span>
              }
            </div>
            
            <div className="card-body">
              {/* Use MathJax for questions with math content */}
              <div className="question">
                {question.contains_math ? (
                  <MathJax>{question.question}</MathJax>
                ) : (
                  <div dangerouslySetInnerHTML={{ __html: question.question }} />
                )}
              </div>
              
              {/* Render table if present */}
              {question.has_table && question.table_html && (
                <div 
                  className="table-container"
                  dangerouslySetInnerHTML={{ __html: question.table_html }}
                />
              )}
              
              {/* Options section */}
              <div className="options">
                {question.options && Object.keys(question.options).length > 0 ? (
                  Object.entries(question.options).map(([opt, text]) => (
                    <div 
                      key={opt} 
                      onClick={() => handleAnswerSelect(idx, opt)}
                      className={`option ${selectedAnswers[idx] === opt ? 'selected-option' : ''}`}
                    >
                      <strong>{opt}.</strong> {" "}
                      {question.contains_math ? 
                        <MathJax>{text}</MathJax> : 
                        <span dangerouslySetInnerHTML={{ __html: text }} />
                      }
                    </div>
                  ))
                ) : (
                  <div className="no-options">
                    <p>No options found for this question</p>
                    <button
                      onClick={() => handleAnswerSelect(idx, 'skipped')}
                      className={`btn skip-btn ${selectedAnswers[idx] === 'skipped' ? 'skip-btn-active' : ''}`}
                    >
                      Skip this question
                    </button>
                  </div>
                )}
              </div>
            </div>
            
            {/* Show answers only in results mode */}
            {showResults && (
              <div className="answer-section">
                {/* Display all options with correct/incorrect highlighting */}
                {question.options && Object.keys(question.options).length > 0 && (
                  <div className="result-options">
                    {Object.entries(question.options).map(([opt, text]) => {
                      const isCorrect = opt === question.correct;
                      const isSelected = selectedAnswers[idx] === opt;
                      const isWrong = isSelected && !isCorrect;
                      
                      return (
                        <div 
                          key={opt} 
                          className={`result-option ${isCorrect ? 'correct-option' : ''} ${isWrong ? 'wrong-option' : ''}`}
                        >
                          <strong>{opt}.</strong> {" "}
                          {question.contains_math ? 
                            <MathJax>{text}</MathJax> : 
                            <span dangerouslySetInnerHTML={{ __html: text }} />
                          }
                          {isCorrect && (
                            <span className="correct-badge">✓ Correct</span>
                          )}
                          {isWrong && (
                            <span className="wrong-badge">✗ Incorrect</span>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
                
                {/* Show explanation */}
                <div className="explanation">
                  <strong>Correct Answer:</strong> {
                    selectedAnswers[idx] === 'skipped' ? 
                    'Question skipped due to missing options' : 
                    (question.correct || "Not specified")
                  }
                  
                  {/* Show explanation if available */}
                  {question.explanation && (
                    <div className="explanation-text">
                      <strong>Explanation:</strong> {question.explanation}
                    </div>
                  )}
                  
                  {/* Show "Things to Remember" section if available */}
                  {question.things_to_remember && question.things_to_remember.length > 0 && (
                    <div className="things-to-remember">
                      <strong>Things to Remember:</strong>
                      <ul>
                        {question.things_to_remember.map((item, i) => (
                          <li key={i}>{item}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
      
      {/* Submit button at bottom */}
      {!showResults && (
        <div className="submit-container">
          <button 
            onClick={submitQuiz}
            disabled={!areAllQuestionsAddressed()}
            className={`btn ${areAllQuestionsAddressed() ? 'primary-btn' : 'disabled-btn'}`}
          >
            Submit Quiz
          </button>
          
          {!areAllQuestionsAddressed() && (
            <p className="validation-error">
              Please answer all questions or skip those without options.
            </p>
          )}
        </div>
      )}
      
      {/* Results summary */}
      {showResults && (
        <div className="results-container">
          <h2>Quiz Results</h2>
          <div className="score-display">
            Your Score: <strong>{score}</strong> out of <strong>{quizStats.answerableQuestions}</strong>
            <span className="percentage">
              ({quizStats.answerableQuestions > 0 ? Math.round((score / quizStats.answerableQuestions) * 100) : 0}%)
            </span>
          </div>
          
          {quizStats.skippedQuestions > 0 && (
            <div className="skipped-info">
              {quizStats.skippedQuestions} question(s) were skipped due to missing options
            </div>
          )}
          
          <div className="action-buttons">
            <button 
              onClick={() => {
                setQuizMode(false);
                setShowResults(false);
              }}
              className="btn primary-btn"
            >
              Create New Quiz
            </button>
            
            <button 
              onClick={() => {
                setAllQuestions([]);
                setQuizMode(false);
                setShowResults(false);
              }}
              className="btn secondary-btn"
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
      <div className={`status-bar ${backendStatus.includes('Connected') ? 'status-connected' : 'status-error'}`}>
        <p><strong>Backend Status:</strong> {backendStatus}</p>
        <p><small>Using proxy to connect to backend</small></p>
      </div>
      
      {/* Upload Section - Only show if not in quiz mode */}
      {!quizMode && !allQuestions.length && (
        <div className="upload-section">
          <h2>Upload PDF</h2>
          <p>Upload a PDF file containing quiz questions. <strong>Maximum size: 3MB</strong></p>
          <p><small>Tips for best results:
            <ul className="tips-list">
              <li>Use smaller PDFs (under 3MB)</li>
              <li>Use PDFs with clear question formatting (Q.1, Q.2, etc.)</li>
              <li>Choose PDFs with clearly marked options (A. B. C. D.)</li>
              <li>For large PDFs, use the page range feature to process specific sections</li>
            </ul>
          </small></p>
          
          {!pdfInfo ? (
            <input 
              type="file" 
              accept=".pdf" 
              onChange={handleFile}
              disabled={loading}
              className="file-input"
            />
          ) : (
            renderPdfInfoPanel()
          )}
          
          {error && (
            <div className="error-message">
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

// Main App component
function App() {
  // Configure MathJax
  const mathJaxConfig = {
    loader: { load: ["input/asciimath", "output/chtml"] },
    asciimath: {
      delimiters: [
        ["$", "$"],
        ["`", "`"]
      ]
    }
  };

  return (
    <div className="app-container">
      <header className="app-header">
        <h1>Quiz Generator Pro</h1>
        <p>Upload a PDF to generate an interactive quiz from financial and mathematical content</p>
      </header>
      
      <main className="app-main">
        <MathJaxContext config={mathJaxConfig}>
          <QuizRenderer />
        </MathJaxContext>
      </main>
      
      <footer className="app-footer">
        <p>Quiz Generator Pro</p>
      </footer>
    </div>
  );
}

export default App;

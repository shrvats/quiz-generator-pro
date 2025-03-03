import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { MathJaxContext, MathJax } from 'better-react-mathjax';

const BACKEND_URL = "/api/proxy";
const MAX_TIMEOUT = 45000; // 45 seconds

function QuizRenderer() {
  const [allQuestions, setAllQuestions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [backendStatus, setBackendStatus] = useState('Checking...');
  
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
  
  const [availableSections, setAvailableSections] = useState([]);
  const [selectedSection, setSelectedSection] = useState(null);
  
  const [pdfInfo, setPdfInfo] = useState(null);
  const [pageRangeEnabled, setPageRangeEnabled] = useState(false);
  const [startPage, setStartPage] = useState(0);
  const [endPage, setEndPage] = useState(1);
  const [totalPages, setTotalPages] = useState(0);
  const [selectedFile, setSelectedFile] = useState(null);
  
  const [processingTime, setProcessingTime] = useState(0);
  const [processingTimer, setProcessingTimer] = useState(null);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [timeoutWarningShown, setTimeoutWarningShown] = useState(false);

  useEffect(() => {
    fetch(`${BACKEND_URL}/health`)
      .then(res => res.ok ? res.json() : Promise.reject(`Status: ${res.status}`))
      .then(() => setBackendStatus('Connected ✅'))
      .catch(err => setBackendStatus(`Failed to connect ❌ (${err})`));
  }, []);

  useEffect(() => {
    return () => {
      if (processingTimer) clearInterval(processingTimer);
    };
  }, [processingTimer]);

  const validateFile = (file) => {
    const MAX_FILE_SIZE = 3 * 1024 * 1024;
    if (!file.type.includes('pdf')) {
      return { valid: false, message: 'Please upload a PDF file.' };
    }
    if (file.size > MAX_FILE_SIZE) {
      return {
        valid: false,
        message: `File too large (${(file.size / 1024 / 1024).toFixed(1)}MB). Please upload a PDF smaller than 3MB.`
      };
    }
    return { valid: true };
  };

  const getPdfInfo = async (file) => {
    try {
      const formData = new FormData();
      formData.append('file', file);
      const { data } = await axios.post(
        `${BACKEND_URL}/pdf-info`,
        formData,
        { 
          headers: { 'Content-Type': 'multipart/form-data' },
          timeout: 15000 
        }
      );
      setPdfInfo(data);
      setTotalPages(data.total_pages);
      setEndPage(data.total_pages - 1);
      setSelectedFile(file);
      return data;
    } catch (err) {
      setError(`Failed to analyze PDF: ${err.message || 'Unknown error'}`);
      return null;
    }
  };

  const handleFile = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const validation = validateFile(file);
    if (!validation.valid) {
      setError(validation.message);
      return;
    }
    setError(null);
    setAllQuestions([]);
    setQuizMode(false);
    setQuizQuestions([]);
    setSelectedAnswers({});
    setShowResults(false);
    setTimeoutWarningShown(false);
    setAvailableSections([]);
    setSelectedSection(null);
    await getPdfInfo(file);
  };
  // Replace this section in your App.jsx file (around line ~110-125)

<div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginTop: '10px' }}>
  <div>
    <label htmlFor="startPage" style={{ display: 'block', marginBottom: '5px' }}>Start Page:</label>
    <input 
      type="number" 
      id="startPage"
      min="0"
      max={totalPages - 1}
      value={startPage}
      onChange={(e) => {
        // Add input validation to prevent NaN
        const value = e.target.value === '' ? 0 : parseInt(e.target.value, 10);
        // Ensure the value is a valid number
        if (!isNaN(value)) {
          setStartPage(Math.max(0, Math.min(value, totalPages - 1)));
        }
      }}
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
      onChange={(e) => {
        // Add input validation to prevent NaN
        const value = e.target.value === '' ? startPage : parseInt(e.target.value, 10);
        // Ensure the value is a valid number and within range
        if (!isNaN(value)) {
          setEndPage(Math.max(startPage, Math.min(value, totalPages - 1)));
        }
      }}
      style={{ width: '80px', padding: '8px' }}
    />
  </div>
  <div style={{ marginTop: '24px', color: '#666' }}>
    (Processing {pageRangeEnabled ? (endPage - startPage + 1) : totalPages} pages)
  </div>
</div>

  const processPdf = async () => {
    if (!selectedFile) {
      setError("No file selected");
      return;
    }
    setLoading(true);
    setError(null);
    setProcessingTime(0);
    setUploadProgress(0);

    const timer = setInterval(() => setProcessingTime(prev => prev + 1), 1000);
    setProcessingTimer(timer);

    const timeoutWarning = setTimeout(() => {
      if (loading) {
        setTimeoutWarningShown(true);
      }
    }, 30000);

    try {
      const formData = new FormData();
      formData.append('file', selectedFile);
      if (pageRangeEnabled) {
        formData.append('start_page', startPage);
        formData.append('end_page', endPage);
      }
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

      if (!data || !data.questions || data.questions.length === 0) {
        setError("No questions were extracted from the PDF.");
      } else {
        setAllQuestions(data.questions);
        setNumQuestions(Math.min(10, data.questions.length));
        if (data.sections && data.sections.length > 0) {
          setAvailableSections(data.sections);
        }
      }
    } catch (err) {
      clearTimeout(timeoutWarning);
      if (err.code === 'ECONNABORTED' || err.message.includes('timeout')) {
        setError(`Processing timeout: Please try a smaller PDF (under 3MB) or fewer pages.`);
      } else if (err.response && err.response.status === 408) {
        setError(`Processing timeout: The server took too long. Try a smaller PDF.`);
      } else {
        setError(`Upload failed: ${err.message || 'Unknown error'}.`);
      }
    } finally {
      setLoading(false);
      clearInterval(timer);
      setProcessingTimer(null);
    }
  };

  const getFilteredQuestions = () => {
    if (!selectedSection || !availableSections.length) {
      return allQuestions;
    }
    const section = availableSections.find(s => s.name === selectedSection);
    if (section && section.questions && section.questions.length > 0) {
      return section.questions;
    }
    return allQuestions;
  };

  const startQuiz = () => {
    const filteredQuestions = getFilteredQuestions();
    const shuffled = [...filteredQuestions].sort(() => 0.5 - Math.random());
    const selected = shuffled.slice(0, numQuestions);
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

  const handleAnswerSelect = (questionIndex, option) => {
    setSelectedAnswers(prev => ({
      ...prev,
      [questionIndex]: option
    }));
  };

  const areAllQuestionsAddressed = () => {
    if (!quizQuestions || quizQuestions.length === 0) return false;
    for (let i = 0; i < quizQuestions.length; i++) {
      if (selectedAnswers[i] === undefined) {
        return false;
      }
    }
    return true;
  };

  const submitQuiz = () => {
    let correctCount = 0;
    let totalAnswerable = 0;
    let skippedCount = 0;

    quizQuestions.forEach((question, index) => {
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

    setScore(correctCount);
    setQuizStats({
      totalQuestions: quizQuestions.length,
      answerableQuestions: totalAnswerable || 1,
      skippedQuestions: skippedCount
    });
    setShowResults(true);
  };

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
            {uploadProgress < 100 
              ? `Uploading PDF (${uploadProgress}%)...` 
              : `Processing PDF... (${processingTime} seconds elapsed)`
            }
            {timeoutWarningShown && (
              <span className="timeout-warning"> 
                {' '}Taking longer than expected. This may time out.
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

  const renderConfigScreen = () => (
    <div className="config-screen">
      <h2>Quiz Configuration</h2>
      <p>Successfully extracted {allQuestions.length} questions from your PDF.</p>
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
              <div className="question">
                {question.contains_math ? (
                  <MathJax>{question.question}</MathJax>
                ) : (
                  <div dangerouslySetInnerHTML={{ __html: question.question }} />
                )}
              </div>

              {/* Only render table if it truly exists and isn't empty */}
              {question.has_table && question.table_html && question.table_html.trim() !== '' && (
                <div 
                  className="table-container"
                  dangerouslySetInnerHTML={{ __html: question.table_html }}
                />
              )}

              {/* Updated options section with skip button even if options exist */}
              <div className="options">
                {question.options && Object.keys(question.options).length > 0 ? (
                  <>
                    {Object.entries(question.options).map(([opt, text]) => (
                      <div 
                        key={opt} 
                        onClick={() => handleAnswerSelect(idx, opt)}
                        className={`option ${selectedAnswers[idx] === opt ? 'selected-option' : ''}`}
                      >
                        <strong>{opt}.</strong>{' '}
                        {question.contains_math ? 
                          <MathJax>{text}</MathJax> : 
                          <span dangerouslySetInnerHTML={{ __html: text }} />
                        }
                      </div>
                    ))}
                    <button
                      onClick={() => handleAnswerSelect(idx, 'skipped')}
                      className={`btn skip-btn ${selectedAnswers[idx] === 'skipped' ? 'skip-btn-active' : ''}`}
                    >
                      Skip this question
                    </button>
                  </>
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
            {showResults && (
              <div className="answer-section">
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
                          <strong>{opt}.</strong>{' '}
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
                <div className="explanation">
                  <strong>Correct Answer:</strong>{' '}
                  {selectedAnswers[idx] === 'skipped' 
                    ? 'Question skipped due to missing options' 
                    : (question.correct || "Not specified")
                  }
                  {question.explanation && (
                    <div className="explanation-text">
                      <strong>Explanation:</strong> {question.explanation}
                    </div>
                  )}
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
              Please answer all questions or skip them.
            </p>
          )}
        </div>
      )}
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

  return (
    <div className="container">
      <div className={`status-bar ${backendStatus.includes('Connected') ? 'status-connected' : 'status-error'}`}>
        <p><strong>Backend Status:</strong> {backendStatus}</p>
        <p><small>Using proxy to connect to backend</small></p>
      </div>
      {!quizMode && !allQuestions.length && (
        <div className="upload-section">
          <h2>Upload PDF</h2>
          <p>Upload a PDF file containing quiz questions. <strong>Maximum size: 3MB</strong></p>
          <p><small>Tips for best results:
            <ul className="tips-list">
              <li>Use smaller PDFs (under 3MB)</li>
              <li>Use PDFs with clear question formatting (Q.1, Q.2, etc.)</li>
              <li>Choose PDFs with clearly marked options (A. B. C. D.)</li>
              <li>For large PDFs, use the page range feature</li>
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
      {!quizMode && allQuestions.length > 0 && renderConfigScreen()}
      {quizMode && renderQuizQuestions()}
    </div>
  );
}

function App() {
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

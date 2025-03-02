import React from 'react';
import QuizRenderer from './QuizRenderer.jsx'; // Added .jsx extension
import { MathJaxContext } from 'better-react-mathjax';

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
        <p>Upload a PDF to generate an interactive quiz</p>
      </header>
      
      <main className="app-main">
        <MathJaxContext config={mathJaxConfig}>
          <QuizRenderer />
        </MathJaxContext>
      </main>
      
      <footer className="app-footer">
        <p>© 2025 Quiz Generator Pro</p>
      </footer>
    </div>
  );
}

export default App;

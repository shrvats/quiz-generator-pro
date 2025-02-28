import React from 'react';
import { MathJaxContext } from 'better-react-mathjax';
import QuizRenderer from './components/QuizRenderer';

export default function App() {
  return (
    <MathJaxContext>
      <div className="container">
        <h1 style={{ color: '#1a237e', textAlign: 'center' }}>
          PDF Quiz Generator
        </h1>
        <p style={{ textAlign: 'center', marginBottom: '20px' }}>
          Upload a PDF with quiz questions to convert it into an interactive quiz
        </p>
        <QuizRenderer />
      </div>
    </MathJaxContext>
  );
}

import React from 'react'; // Added React import
import { MathJaxContext } from 'better-react-mathjax';
import QuizRenderer from './components/QuizRenderer';

export default function App() {
  return (
    <MathJaxContext>
      <div className="container">
        <h1 style={{ color: '#1a237e', textAlign: 'center' }}>
          PDF Quiz Generator
        </h1>
        <QuizRenderer />
      </div>
    </MathJaxContext>
  );
}

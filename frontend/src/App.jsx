import React from 'react';
import { MathJaxContext } from 'better-react-mathjax';

// Import both components for testing
import QuizRenderer from './components/QuizRenderer';
import DebugQuizRenderer from './components/DebugQuizRenderer'; // Make sure to save the debug component with this name
import PathFinder from './components/PathFinder';

export default function App() {
  // Current timestamp to verify this file is being used
  const buildTime = new Date().toISOString();
  
  console.log("App.jsx rendered at:", buildTime);
  
  return (
    <MathJaxContext>
      <div className="container">
        <h1 style={{ 
          color: 'red', // Changed to red to verify update
          textAlign: 'center',
          border: '3px solid blue',
          padding: '10px',
          margin: '10px'
        }}>
          PDF Quiz Generator (Debug Build: {buildTime})
        </h1>
        
        {/* Path finder to help debug */}
        <PathFinder />
        
        {/* Use Debug version instead of regular version */}
        <DebugQuizRenderer />
        
        {/* Comment out the original component
        <QuizRenderer />
        */}
      </div>
    </MathJaxContext>
  );
}

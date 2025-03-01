import React, { useState, useEffect } from 'react';

// This is a minimal component that should visibly change your UI
export default function QuizRenderer() {
  const [debugMessage, setDebugMessage] = useState("Initial State");
  
  // On mount, change the message to verify component updates work
  useEffect(() => {
    console.log("DEBUG COMPONENT MOUNTED");
    setTimeout(() => {
      setDebugMessage("Updated via useEffect");
      console.log("DEBUG STATE UPDATED");
    }, 2000);
  }, []);

  return (
    <div style={{
      border: '5px solid red',
      padding: '20px',
      margin: '20px',
      background: 'yellow',
      color: 'black',
      fontSize: '24px',
      textAlign: 'center'
    }}>
      <h1>DEBUG VERSION</h1>
      <p>Message: {debugMessage}</p>
      <button 
        onClick={() => setDebugMessage("Updated via Click: " + new Date().toLocaleTimeString())}
        style={{
          padding: '10px 20px',
          fontSize: '18px',
          background: 'blue',
          color: 'white',
          border: 'none',
          borderRadius: '5px',
          cursor: 'pointer'
        }}
      >
        Click to Update
      </button>
    </div>
  );
}

import React, { useEffect, useState } from 'react';

// This component helps find the proper path structure of your app
export default function PathFinder() {
  const [fileStructure, setFileStructure] = useState({});
  
  useEffect(() => {
    // Log important information about the environment
    console.log("====== PATH FINDER ======");
    console.log("Environment:", process.env.NODE_ENV);
    console.log("Window Location:", window.location.href);
    console.log("Document Path:", document.location.pathname);
    
    // Try to determine component structure
    try {
      // Log the component's own source location if possible
      console.log("Component Module ID:", module.id);
    } catch (e) {
      console.log("Could not access module info:", e.message);
    }
    
    // Try to log import.meta if available
    try {
      console.log("Import Meta URL:", import.meta.url);
    } catch (e) {
      console.log("Import meta not available:", e.message);
    }
    
    // Log available global objects that might help with debugging
    console.log("Available on window:", Object.keys(window).filter(k => k.startsWith('__')));
    console.log("=========================");
  }, []);
  
  return (
    <div style={{
      border: '4px dashed green',
      padding: '15px',
      margin: '15px',
      background: '#f0f0f0'
    }}>
      <h2>Path Finder Component</h2>
      <p>Check your browser console for path information</p>
      <p>Component location: <code>/src/components/PathFinder.jsx</code></p>
    </div>
  );
}

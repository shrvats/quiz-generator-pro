import fetch from 'node-fetch';
import { createReadStream } from 'fs';
import FormData from 'form-data';
import multer from 'multer';
import { NextResponse } from 'next/server';

// Configure multer for file uploads
const upload = multer({ 
  storage: multer.memoryStorage(),
  limits: { fileSize: 10 * 1024 * 1024 } // 10MB limit
});

// Middleware to handle multipart form data
const runMiddleware = (req, res, fn) => {
  return new Promise((resolve, reject) => {
    fn(req, res, (result) => {
      if (result instanceof Error) {
        return reject(result);
      }
      return resolve(result);
    });
  });
};

export default async function handler(req, res) {
  // Get the path parameters
  const { path } = req.query;
  
  // Build the target URL - using the environment variable if set
  const backendUrl = process.env.QUIZ_BACKEND_URL || 'https://quiz-backend-pro.onrender.com';
  const targetUrl = `${backendUrl}/${path.join('/')}`;
  
  // Set a timeout of 50 seconds to allow for clean response handling
  // before the 60-second Vercel function limit is reached
  const TIMEOUT_MS = 50000;
  
  // Set CORS headers
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');
  
  // Handle preflight requests
  if (req.method === 'OPTIONS') {
    res.status(200).end();
    return;
  }
  
  try {
    let response;
    
    // Handle file uploads specially
    if (req.headers['content-type']?.includes('multipart/form-data')) {
      // Use multer to parse the form data
      await runMiddleware(req, res, upload.single('file'));
      
      // Create a new form data object to send to the backend
      const formData = new FormData();
      if (req.file) {
        formData.append('file', req.file.buffer, {
          filename: req.file.originalname,
          contentType: req.file.mimetype
        });
      }
      
      // Forward the file to the backend with timeout
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), TIMEOUT_MS);
      
      response = await fetch(targetUrl, {
        method: 'POST',
        body: formData,
        headers: formData.getHeaders(),
        signal: controller.signal
      });
      
      clearTimeout(timeoutId);
    } else {
      // For non-file requests, forward as normal
      const fetchOptions = {
        method: req.method,
        headers: {
          'Content-Type': req.headers['content-type'] || 'application/json'
        }
      };
      
      // Add body for non-GET requests
      if (req.method !== 'GET' && req.method !== 'HEAD') {
        fetchOptions.body = JSON.stringify(req.body);
      }
      
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), TIMEOUT_MS);
      
      fetchOptions.signal = controller.signal;
      response = await fetch(targetUrl, fetchOptions);
      
      clearTimeout(timeoutId);
    }

    // Get content type and data from the response
    const contentType = response.headers.get('content-type');
    let data;
    
    if (contentType?.includes('application/json')) {
      data = await response.json();
    } else {
      data = await response.text();
    }
    
    // Set the appropriate status and send the response
    res.status(response.status);
    
    if (contentType?.includes('application/json')) {
      res.json(data);
    } else {
      res.send(data);
    }
  } catch (error) {
    console.error('Proxy error:', error);
    
    // Check if this is a timeout/abort error
    if (error.name === 'AbortError') {
      res.status(504).json({
        error: 'Gateway Timeout',
        details: 'The PDF processing took too long. Please try a smaller PDF or one with fewer pages.'
      });
    } else {
      res.status(500).json({
        error: 'Failed to fetch from API',
        details: error.message
      });
    }
  }
}

export const config = {
  api: {
    bodyParser: false, // Disable the default body parser
    externalResolver: true
  }
};

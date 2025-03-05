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
  
  // Log request details
  console.log(`[PROXY] Request to path: ${path?.join('/')}`);
  console.log(`[PROXY] Method: ${req.method}`);
  console.log(`[PROXY] Content-Type: ${req.headers['content-type']}`);
  
  // Build the target URL - using the environment variable if set
  const backendUrl = process.env.QUIZ_BACKEND_URL || 'https://quiz-generator-pro.onrender.com';
  const targetUrl = `${backendUrl}/${path?.join('/')}`;
  console.log(`[PROXY] Target URL: ${targetUrl}`);
  
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
    let startTime = Date.now();
    
    // Handle file uploads specially
    if (req.headers['content-type']?.includes('multipart/form-data')) {
      console.log('[PROXY] Processing file upload request');
      
      try {
        // Use multer to parse the form data
        await runMiddleware(req, res, upload.single('file'));
        console.log('[PROXY] Multer processed the file upload');
        
        // Create a new form data object to send to the backend
        const formData = new FormData();
        if (req.file) {
          console.log(`[PROXY] File received: ${req.file.originalname}, size: ${req.file.size} bytes`);
          formData.append('file', req.file.buffer, {
            filename: req.file.originalname,
            contentType: req.file.mimetype
          });
        } else {
          console.log('[PROXY] No file found in request');
        }
        
        // Forward the file to the backend with timeout
        console.log('[PROXY] Sending file to backend...');
        const controller = new AbortController();
        const timeoutId = setTimeout(() => {
          console.log(`[PROXY] Request timed out after ${TIMEOUT_MS}ms`);
          controller.abort();
        }, TIMEOUT_MS);
        
        response = await fetch(targetUrl, {
          method: 'POST',
          body: formData,
          headers: formData.getHeaders(),
          signal: controller.signal
        });
        
        clearTimeout(timeoutId);
        console.log(`[PROXY] Backend responded in ${Date.now() - startTime}ms with status ${response.status}`);
      } catch (uploadError) {
        console.error('[PROXY] Error in file upload handling:', uploadError);
        throw uploadError;
      }
    } else {
      // For non-file requests, forward as normal
      console.log('[PROXY] Processing regular request');
      
      const fetchOptions = {
        method: req.method,
        headers: {
          'Content-Type': req.headers['content-type'] || 'application/json'
        }
      };
      
      // Add body for non-GET requests
      if (req.method !== 'GET' && req.method !== 'HEAD') {
        fetchOptions.body = JSON.stringify(req.body);
        console.log(`[PROXY] Request body: ${fetchOptions.body}`);
      }
      
      const controller = new AbortController();
      const timeoutId = setTimeout(() => {
        console.log(`[PROXY] Request timed out after ${TIMEOUT_MS}ms`);
        controller.abort();
      }, TIMEOUT_MS);
      
      fetchOptions.signal = controller.signal;
      console.log('[PROXY] Sending request to backend...');
      response = await fetch(targetUrl, fetchOptions);
      
      clearTimeout(timeoutId);
      console.log(`[PROXY] Backend responded in ${Date.now() - startTime}ms with status ${response.status}`);
    }

    // Get content type and data from the response
    const contentType = response.headers.get('content-type');
    console.log(`[PROXY] Response content type: ${contentType}`);
    
    let data;
    try {
      if (contentType?.includes('application/json')) {
        data = await response.json();
        console.log('[PROXY] Parsed JSON response');
      } else {
        data = await response.text();
        console.log(`[PROXY] Received text response (${data.length} chars)`);
      }
    } catch (parseError) {
      console.error('[PROXY] Error parsing response:', parseError);
      data = 'Error parsing response';
    }
    
    // Set the appropriate status and send the response
    console.log(`[PROXY] Sending response with status ${response.status}`);
    res.status(response.status);
    
    if (contentType?.includes('application/json')) {
      res.json(data);
    } else {
      res.send(data);
    }
    
    console.log(`[PROXY] Request completed in ${Date.now() - startTime}ms`);
  } catch (error) {
    console.error('[PROXY] Error details:', {
      name: error.name,
      message: error.message,
      stack: error.stack,
      path: path?.join('/'),
      method: req.method
    });
    
    // Check if this is a timeout/abort error
    if (error.name === 'AbortError') {
      res.status(504).json({
        error: 'Gateway Timeout',
        details: 'The request to the backend server timed out. This could be due to high server load or a complex operation.'
      });
    } else {
      res.status(500).json({
        error: 'Failed to fetch from API',
        details: error.message,
        name: error.name
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

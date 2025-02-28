// File path: /api/proxy/[...path].js
export default async function handler(req, res) {
  // Log the request information
  console.log(`Proxy request: ${req.method} ${req.url}`);
  
  // Handle CORS preflight
  if (req.method === 'OPTIONS') {
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');
    res.status(200).end();
    return;
  }
  
  try {
    // Extract the target path by removing '/api/proxy'
    const targetPath = req.url.replace(/^\/api\/proxy\/?/, '/');
    const targetUrl = `https://quiz-backend-pro.onrender.com${targetPath}`;
    
    console.log(`Forwarding to: ${targetUrl}`);
    
    // Forward the request to the backend
    const fetchOptions = {
      method: req.method,
      headers: {
        'Content-Type': req.headers['content-type'] || 'application/json'
      }
    };
    
    // Add body for non-GET requests
    if (req.method !== 'GET' && req.method !== 'HEAD') {
      const bodyParser = require('body-parser');
      await new Promise((resolve, reject) => {
        bodyParser.raw({ type: '*/*', limit: '10mb' })(req, res, (err) => {
          if (err) reject(err);
          else resolve();
        });
      });
      
      fetchOptions.body = req.body;
    }
    
    // Make the fetch request
    const response = await fetch(targetUrl, fetchOptions);
    const data = await response.text();
    
    // Forward the response
    res.status(response.status);
    
    // Set CORS headers
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');
    
    // Forward content type
    const contentType = response.headers.get('content-type');
    if (contentType) {
      res.setHeader('Content-Type', contentType);
    }
    
    res.send(data);
  } catch (error) {
    console.error('Proxy error:', error);
    res.status(500).json({ 
      error: 'Proxy Error', 
      message: error.message,
      stack: process.env.NODE_ENV === 'development' ? error.stack : undefined
    });
  }
}

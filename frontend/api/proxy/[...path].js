// File: api/proxy/[...path].js
export default async function handler(req, res) {
  // Set CORS headers
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  // Handle OPTIONS request
  if (req.method === 'OPTIONS') {
    res.status(200).end();
    return;
  }

  try {
    // Get path from request
    const path = req.query.path || [];
    const targetPath = '/' + path.join('/');
    
    // Use the correct URL
    const url = `https://quiz-generator-pro.onrender.com${targetPath}`;
    
    console.log(`Proxying ${req.method} request to: ${url}`);

    // Create fetch options
    const fetchOptions = {
      method: req.method,
      headers: {}
    };

    // Set content type for non-GET requests
    if (req.method !== 'GET' && req.headers['content-type']) {
      fetchOptions.headers['Content-Type'] = req.headers['content-type'];
    }

    // Handle file uploads for POST requests with multipart/form-data
    if (req.method === 'POST' && 
        req.headers['content-type'] && 
        req.headers['content-type'].includes('multipart/form-data')) {
      
      // For file uploads, we need to get the raw body
      const chunks = [];
      for await (const chunk of req) {
        chunks.push(typeof chunk === 'string' ? Buffer.from(chunk) : chunk);
      }
      const buffer = Buffer.concat(chunks);
      
      // Add boundary to content type
      const contentType = req.headers['content-type'];
      fetchOptions.headers['Content-Type'] = contentType;
      
      // Set the buffer as the request body
      fetchOptions.body = buffer;
    } else if (req.method !== 'GET' && req.body) {
      // For regular JSON requests
      fetchOptions.body = JSON.stringify(req.body);
    }

    // Forward request to backend
    const response = await fetch(url, fetchOptions);
    
    // Get response as text
    const text = await response.text();
    
    // Send response
    res.status(response.status);
    
    // Set content type if available
    const contentType = response.headers.get('content-type');
    if (contentType) {
      res.setHeader('Content-Type', contentType);
    }
    
    // Send response body
    res.send(text);
  } catch (error) {
    console.error('Proxy error:', error);
    res.status(500).json({ 
      error: 'Proxy Error', 
      message: error.message,
      url: `https://quiz-generator-pro.onrender.com${req.url.replace(/^\/api\/proxy/, '')}`
    });
  }
}

// File: pages/api/proxy/[...path].js
export default async function handler(req, res) {
  // Set CORS headers
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');

  // Handle OPTIONS request (preflight)
  if (req.method === 'OPTIONS') {
    res.status(200).end();
    return;
  }

  try {
    // Get path from request
    const path = req.query.path || [];
    const targetPath = '/' + path.join('/');
    const url = `https://quiz-backend-pro.onrender.com${targetPath}`;

    console.log(`Proxying ${req.method} request to: ${url}`);

    // Create fetch options
    const fetchOptions = {
      method: req.method,
      headers: {
        'Content-Type': req.headers['content-type'] || 'application/json',
      },
    };

    // Add body for non-GET methods
    if (req.method !== 'GET' && req.body) {
      fetchOptions.body = req.body;
    }

    // Forward request to target server
    const response = await fetch(url, fetchOptions);
    
    // Read the response body
    const contentType = response.headers.get("content-type");
    let body;
    
    if (contentType && contentType.includes("application/json")) {
      body = await response.json();
    } else {
      body = await response.text();
    }

    // Send response back to client
    res.status(response.status);
    res.setHeader('Content-Type', contentType || 'text/plain');
    
    if (typeof body === 'object') {
      res.json(body);
    } else {
      res.send(body);
    }

  } catch (error) {
    console.error('Proxy error:', error);
    res.status(500).json({ error: 'Proxy Error', message: error.message });
  }
}

export const config = {
  api: {
    bodyParser: false,
    externalResolver: true,
  },
};

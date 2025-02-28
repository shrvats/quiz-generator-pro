// frontend/api/proxy/[...path].js
export default function handler(req, res) {
  // Log the incoming request for debugging
  console.log(`Proxy request: ${req.method} ${req.url}`);
  
  // Direct response instead of using middleware
  const targetUrl = `https://quiz-backend-pro.onrender.com${req.url.replace('/api/proxy', '')}`;
  
  // Set CORS headers
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  
  // Handle OPTIONS requests directly
  if (req.method === 'OPTIONS') {
    res.status(200).end();
    return;
  }
  
  // For GET requests, fetch and return
  if (req.method === 'GET') {
    fetch(targetUrl)
      .then(response => response.text())
      .then(data => {
        try {
          // Try to parse as JSON
          const jsonData = JSON.parse(data);
          res.status(200).json(jsonData);
        } catch (e) {
          // If not JSON, return as text
          res.status(200).send(data);
        }
      })
      .catch(error => {
        console.error('Proxy error:', error);
        res.status(500).json({ error: 'Proxy request failed' });
      });
    return;
  }
  
  // For POST requests, forward the body
  if (req.method === 'POST') {
    // Get raw body from request
    let body = [];
    req.on('data', (chunk) => {
      body.push(chunk);
    }).on('end', () => {
      body = Buffer.concat(body);
      
      // Forward to backend with increased timeout
      fetch(targetUrl, {
        method: 'POST',
        headers: {
          'Content-Type': req.headers['content-type'] || 'application/json'
        },
        body: body,
        // Increase timeout to 2 minutes
        timeout: 120000
      })
      .then(response => response.text())
      .then(data => {
        try {
          const jsonData = JSON.parse(data);
          res.status(200).json(jsonData);
        } catch (e) {
          res.status(200).send(data);
        }
      })
      .catch(error => {
        console.error('Proxy POST error:', error);
        res.status(500).json({ error: 'Proxy request failed' });
      });
    });
    return;
  }
  
  // Default response for unsupported methods
  res.status(405).json({ error: 'Method not allowed' });
}

export const config = {
  api: {
    bodyParser: false,
    externalResolver: true,
  }
};

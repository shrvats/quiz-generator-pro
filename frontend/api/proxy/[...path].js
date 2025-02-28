// File path: /api/proxy/[...path].js
import { createProxy } from 'http-proxy';

// Create a proxy server instance
const proxy = createProxy();

export default function handler(req, res) {
  return new Promise((resolve, reject) => {
    // Don't forward the '/api/proxy' part of the path
    const target = 'https://quiz-backend-pro.onrender.com';
    const pathname = req.url.replace(/^\/api\/proxy/, '');
    
    // Log request details (helpful for debugging)
    console.log(`Proxying request: ${req.method} ${pathname} to ${target}`);
    
    // Rewrite the URL
    req.url = pathname;

    // Add CORS headers
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');
    
    // Handle OPTIONS requests (for CORS preflight)
    if (req.method === 'OPTIONS') {
      res.status(200).end();
      return resolve();
    }

    // Forward the request to the target server
    proxy.web(req, res, { 
      target,
      changeOrigin: true,
      selfHandleResponse: false
    }, (err) => {
      if (err) {
        console.error('Proxy error:', err);
        res.status(500).json({ error: `Proxy error: ${err.message}` });
        resolve();
      }
    });
    
    // Handle proxy completion
    res.on('finish', () => {
      resolve();
    });
  });
}

export const config = {
  api: {
    bodyParser: false,
    externalResolver: true,
  }
};

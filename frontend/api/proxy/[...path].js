// Replace this section in your frontend/api/proxy/[...path].js file
export default async function handler(request) {
  try {
    // Extract path from the URL
    const url = new URL(request.url);
    const pathSegments = url.pathname.split('/');
    // Remove "/api/proxy" from the path
    const path = pathSegments.slice(3).join('/');
    
    // Target backend URL
    const backendUrl = 'https://quiz-generator-pro.onrender.com';
    const targetUrl = `${backendUrl}/${path}`;
    
    // Add timeout control for requests
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 55000); // 55 second timeout
    
    try {
      // Forward the request with timeout control
      const response = await fetch(targetUrl, {
        method: request.method,
        headers: request.headers,
        body: ['GET', 'HEAD'].includes(request.method) ? undefined : request.body,
        signal: controller.signal,
        duplex: 'half' // Important for streaming body content
      });
      
      clearTimeout(timeoutId);
      // Return the response directly
      return response;
    } catch (error) {
      clearTimeout(timeoutId);
      // Handle AbortError (timeout) specifically
      if (error.name === 'AbortError') {
        return new Response(JSON.stringify({
          error: 'Gateway Timeout',
          details: 'The PDF processing took too long. Please try a smaller PDF or one with fewer pages.'
        }), {
          status: 504,
          headers: {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type, Authorization'
          }
        });
      }
      
      // Handle other errors
      throw error;
    }
  } catch (error) {
    console.error('Proxy error:', error);
    return new Response(JSON.stringify({
      error: 'Failed to fetch from API',
      details: error.message
    }), {
      status: 500,
      headers: {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type, Authorization'
      }
    });
  }
}

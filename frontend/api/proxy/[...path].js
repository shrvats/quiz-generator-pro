export const config = {
  runtime: 'edge',
};

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
    
    // Forward the request as is, including all headers and the body
    const response = await fetch(targetUrl, {
      method: request.method,
      headers: request.headers,
      body: ['GET', 'HEAD'].includes(request.method) ? undefined : request.body,
      duplex: 'half' // Important for streaming body content
    });
    
    // Return the response directly
    return response;
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

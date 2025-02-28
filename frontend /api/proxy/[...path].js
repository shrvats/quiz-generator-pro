import { createProxyMiddleware } from 'http-proxy-middleware';

export default createProxyMiddleware({
  target: 'https://quiz-backend-pro.onrender.com',
  changeOrigin: true,
  pathRewrite: (path) => path.replace(/^\/api\/proxy/, ''),
  onProxyRes: (proxyRes) => {
    proxyRes.headers['Access-Control-Allow-Origin'] = '*';
    proxyRes.headers['Access-Control-Allow-Methods'] = '*';
    proxyRes.headers['Access-Control-Allow-Headers'] = '*';
  }
});

export const config = {
  api: {
    bodyParser: false,
    externalResolver: true,
  }
};

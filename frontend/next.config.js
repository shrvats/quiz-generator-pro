const nextConfig = {
  async rewrites() {
    return [
      {
        source: '/api/proxy/:path*',
        destination: 'https://quiz-generator-pro.onrender.com/:path*'
      }
    ]
  },
  webpack(config) {
    return config;
  }
}

module.exports = nextConfig;

module.exports = {
  async rewrites() {
    return [
      {
        source: '/api/proxy/:path*',
        destination: 'https://quiz-generator-pro.onrender.com/:path*'
      }
    ]
  }
}

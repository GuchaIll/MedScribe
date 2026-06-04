/**
 * CRA dev-server proxy configuration.
 *
 * When running locally: proxy forwards /api/* → http://localhost:8080 (default).
 * When running in Docker Compose: set REACT_APP_API_TARGET=http://gateway:8080
 * so the proxy can reach the gateway container by its service name.
 */
const { createProxyMiddleware } = require('http-proxy-middleware');

module.exports = function (app) {
  const target = process.env.REACT_APP_API_TARGET || 'http://localhost:8080';

  app.use(
    '/api',
    createProxyMiddleware({
      target,
      changeOrigin: true,
    })
  );
};

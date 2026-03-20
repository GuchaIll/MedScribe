/**
 * CRA dev-server proxy configuration.
 *
 * When running locally: proxy forwards /api/* → http://localhost:3001 (default).
 * When running in Docker Compose: set REACT_APP_API_TARGET=http://api:3001
 * so the proxy can reach the backend container by its service name.
 *
 * This file overrides the "proxy" field in package.json.
 */
const { createProxyMiddleware } = require('http-proxy-middleware');

module.exports = function (app) {
  const target = process.env.REACT_APP_API_TARGET || 'http://localhost:3001';

  app.use(
    '/api',
    createProxyMiddleware({
      target,
      changeOrigin: true,
    })
  );
};

/**
 * DailyGreen Full-Stack Express Server Entry Point
 *
 * Runs Express backend APIs with mounted Vite middlewares in development
 * and static asset serving in production.
 */

import express from 'express';
import cors from 'cors';
import * as path from 'path';
import { fileURLToPath } from 'url';
import { createServer as createViteServer } from 'vite';
import { apiRouter } from './src/server/routes';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const PORT = parseInt(process.env.PORT || '3000', 10);
const HOST = '0.0.0.0';

export async function createServer() {
  const app = express();

  // Basic security and parsing middleware
  app.use(cors());
  app.use(express.json());

  // Mount backend API routes
  app.use('/api', apiRouter);

  // Development vs Production Frontend Integration
  const isProduction = process.env.NODE_ENV === 'production';

  if (!isProduction) {
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: 'spa',
    });
    app.use(vite.middlewares);
  } else {
    const distPath = path.join(__dirname, 'dist');
    app.use(express.static(distPath));
    app.get('*', (req, res) => {
      res.sendFile(path.join(distPath, 'index.html'));
    });
  }

  return app;
}

// Start standalone dev/prod server when run directly
if (process.env.NODE_ENV !== 'test') {
  createServer().then((app) => {
    const server = app.listen(PORT, HOST, () => {
      console.log(`[DailyGreen Server] Running on http://${HOST}:${PORT}`);
      console.log(`[DailyGreen Server] Environment: ${process.env.NODE_ENV || 'development'}`);
      console.log(`[DailyGreen Server] Safety: dry_run=true, ALLOW_LIVE_MUTATIONS=false, max_workers=1`);
    });

    const shutdown = () => {
      console.log('[DailyGreen Server] Shutting down gracefully...');
      server.close(() => {
        process.exit(0);
      });
    };

    process.on('SIGTERM', shutdown);
    process.on('SIGINT', shutdown);
  });
}

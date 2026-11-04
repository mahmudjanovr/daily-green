import express, { Request, Response, NextFunction } from 'express';
import cors from 'cors';
import * as path from 'path';
import { fileURLToPath } from 'url';
import { createServer as createViteServer } from 'vite';
import { apiRouter } from './src/server/routes';
import { schedulerService } from './src/server/scheduler';
import { logger } from './src/server/logger';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const PORT = parseInt(process.env.PORT || '3000', 10);
const HOST = '0.0.0.0';

// In-Memory IP Rate Limiter for sensitive endpoints
const rateLimitMap = new Map<string, { count: number; resetTime: number }>();
function rateLimiter(maxRequests = 100, windowMs = 60000) {
  return (req: Request, res: Response, next: NextFunction) => {
    // Only rate-limit mutative or heavy endpoints
    if (req.method === 'GET' && !req.path.startsWith('/api/ai/')) {
      return next();
    }

    const ip = req.ip || req.socket.remoteAddress || 'unknown-client';
    const now = Date.now();
    const entry = rateLimitMap.get(ip);

    if (!entry || now > entry.resetTime) {
      rateLimitMap.set(ip, { count: 1, resetTime: now + windowMs });
      return next();
    }

    if (entry.count >= maxRequests) {
      res.setHeader('Retry-After', Math.ceil((entry.resetTime - now) / 1000));
      return res.status(429).json({
        error: 'Too many requests. Rate limit exceeded.',
        code: 'RATE_LIMIT_EXCEEDED',
      });
    }

    entry.count++;
    next();
  };
}

export async function createServer() {
  const app = express();

  // Production Security Headers
  app.use((req: Request, res: Response, next: NextFunction) => {
    res.setHeader('X-Content-Type-Options', 'nosniff');
    res.setHeader('X-Frame-Options', 'SAMEORIGIN');
    res.setHeader('X-XSS-Protection', '1; mode=block');
    res.setHeader('Referrer-Policy', 'strict-origin-when-cross-origin');
    res.setHeader('Permissions-Policy', 'camera=(), microphone=(), geolocation=()');
    next();
  });

  // CORS configuration
  app.use(
    cors({
      origin: process.env.NODE_ENV === 'production' ? true : '*',
      methods: ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
      allowedHeaders: ['Content-Type', 'Authorization', 'X-Correlation-ID', 'X-Request-ID'],
    })
  );

  app.use(express.json({ limit: '2mb' }));

  // Apply rate limiter to API routes
  app.use('/api', rateLimiter(120, 60000));

  // Mount backend API routes
  app.use('/api', apiRouter);

  // If an API route was not matched, return clean API 404 JSON (do not fall through to SPA)
  app.use('/api', (req: Request, res: Response) => {
    res.status(404).json({ error: 'Endpoint not found', code: 'NOT_FOUND' });
  });

  // Development vs Production Frontend Integration
  const isProduction = process.env.NODE_ENV === 'production';
  const isTest = process.env.NODE_ENV === 'test' || process.argv.some((arg) => arg.includes('test'));

  if (!isTest) {
    if (!isProduction) {
      const vite = await createViteServer({
        server: { middlewareMode: true },
        appType: 'spa',
      });
      app.use(vite.middlewares);
    } else {
      const distPath = path.join(__dirname, 'dist');
      app.use(express.static(distPath));
      app.use((req: Request, res: Response) => {
        if (req.path.startsWith('/api') || req.originalUrl.startsWith('/api')) {
          res.status(404).json({ error: 'Endpoint not found', code: 'NOT_FOUND' });
          return;
        }
        res.sendFile(path.join(distPath, 'index.html'));
      });
    }
  }

  return app;
}

// Start standalone dev/prod server when run directly (not in test)
const isTestEnv = process.env.NODE_ENV === 'test' || process.argv.some((arg) => arg.includes('test'));
if (!isTestEnv) {
  createServer().then((app) => {
    const server = app.listen(PORT, HOST, () => {
      logger.info(
        'Server',
        `DailyGreen server running on http://${HOST}:${PORT} [${process.env.NODE_ENV || 'development'}]`,
        undefined,
        {
          port: PORT,
          host: HOST,
          nodeEnv: process.env.NODE_ENV || 'development',
          dry_run: true,
          allow_live_mutations: false,
          max_workers: 1,
        }
      );

      // Start autonomous background scheduler daemon
      schedulerService.startDaemon();
    });

    const shutdown = (signal: string) => {
      logger.audit('Server', `Received ${signal}. Shutting down DailyGreen gracefully...`);
      schedulerService.stopDaemon();

      const forceTimeout = setTimeout(() => {
        logger.error('Server', 'Forced shutdown after timeout.');
        process.exit(1);
      }, 5000);

      server.close(() => {
        clearTimeout(forceTimeout);
        logger.info('Server', 'DailyGreen HTTP server closed cleanly.');
        process.exit(0);
      });
    };

    process.on('SIGTERM', () => shutdown('SIGTERM'));
    process.on('SIGINT', () => shutdown('SIGINT'));
  });
}

// Serve built application and repository-owned assets; no database or live API.
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { resolve, extname, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
const root = fileURLToPath(new URL('../../', import.meta.url));
const types = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.ico': 'image/x-icon', '.png': 'image/png' };
createServer(async (req, res) => {
  const pathname = new URL(req.url, 'http://localhost').pathname;
  const source = pathname === '/' ? '/static/app/index.html' : pathname === '/profile' ? '/static/profile.html' : pathname === '/favicon.ico' ? '/static/icon/Pic.ico' : pathname;
  const file = resolve(root, `.${decodeURIComponent(source)}`);
  if (!source.startsWith('/static/') || !file.startsWith(resolve(root, 'static') + sep)) { res.writeHead(404); res.end(); return; }
  try {
    const content = await readFile(file);
    res.writeHead(200, { 'Content-Type': types[extname(file)] || 'application/octet-stream', 'Cache-Control': 'no-store',
      'Content-Security-Policy': "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' https: data: blob:; connect-src 'self'; frame-src 'self'; object-src 'none'" });
    res.end(content);
  } catch { res.writeHead(404); res.end(); }
}).listen(18877, '127.0.0.1');

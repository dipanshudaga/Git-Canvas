#!/usr/bin/env node
'use strict';
// Map Git: a small local server. It serves the page and passes GitHub API
// requests on, with your own GitHub sign-in added. The sign-in never reaches the browser.
const http = require('http');
const fs = require('fs');
const path = require('path');
const { execFile, spawn } = require('child_process');

const ROOT = path.join(__dirname, '..');
const API = (process.env.MAPGIT_API || 'https://api.github.com').replace(/\/$/, '');
const VERSION = require(path.join(ROOT, 'package.json')).version;
const ASSETS = { '/': ['index.html', 'text/html; charset=utf-8'], '/index.html': ['index.html', 'text/html; charset=utf-8'], '/favicon.svg': ['favicon.svg', 'image/svg+xml'], '/favicon.png': ['favicon.png', 'image/png'], '/apple-touch-icon.png': ['apple-touch-icon.png', 'image/png'] };

const HELP = `Map Git ${VERSION}
See a GitHub repository as a map of branches and commits.

Usage:
  mapgit [owner/repo | github-url] [options]

With no repository, Map Git opens the GitHub remote of the current
folder. If the folder has none, it opens an empty canvas.

Options:
  -p, --port <number>   Port to use (default 4747)
      --no-open         Do not open the browser
  -v, --version         Show the version
  -h, --help            Show this help

Sign-in:
  Map Git uses the GitHub CLI login (run "gh auth login") or the
  GITHUB_TOKEN environment variable. A sign-in opens private repositories
  and raises the GitHub limit from 60 to 5,000 requests each hour.
`;

function parse(argv) {
  const o = { port: 4747, open: true, repo: '' };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '-h' || a === '--help') o.help = true;
    else if (a === '-v' || a === '--version') o.version = true;
    else if (a === '--no-open') o.open = false;
    else if (a === '-p' || a === '--port') o.port = Number(argv[++i]);
    else if (a.startsWith('--port=')) o.port = Number(a.slice(7));
    else if (a.startsWith('-')) { o.bad = a; }
    else o.repo = a;
  }
  return o;
}

function repoName(v) {
  const m = /^(?:https?:\/\/)?(?:www\.)?(?:github\.com\/)?([\w.-]+)\/([\w.-]+?)(?:\.git)?(?:\/.*)?$/.exec(String(v || '').trim());
  return m ? m[1] + '/' + m[2] : '';
}

// Parse a GitHub remote address: https, ssh://, or git@github.com:owner/repo(.git)
function remoteRepo(url) {
  const m = /^(?:(?:https?|ssh|git):\/\/(?:[^@\/]+@)?|[^@\/\s]+@)github\.com[:\/]([\w.-]+)\/([\w.-]+?)(?:\.git)?\/?$/i.exec(String(url || '').trim());
  return m ? m[1] + '/' + m[2] : '';
}

// The GitHub repository of the current folder, if it has one (prefers the "origin" remote).
function folderRepo() {
  return new Promise(resolve => {
    execFile('git', ['remote', '-v'], { timeout: 3000, windowsHide: true }, (err, out) => {
      if (err) return resolve('');
      const remotes = {};
      for (const line of String(out).split('\n')) { const m = /^(\S+)\s+(\S+)\s+\(fetch\)/.exec(line); if (m) remotes[m[1]] = m[2]; }
      const order = ['origin', ...Object.keys(remotes).filter(k => k !== 'origin')];
      for (const k of order) { const r = remoteRepo(remotes[k]); if (r) return resolve(r); }
      resolve('');
    });
  });
}

function findToken() {
  return new Promise(resolve => {
    const env = process.env.GITHUB_TOKEN || process.env.GH_TOKEN;
    if (env) return resolve(env.trim());
    execFile('gh', ['auth', 'token'], { timeout: 5000, windowsHide: true }, (err, out) => resolve(err ? '' : String(out).trim()));
  });
}

function createServer(token, port) {
  const own = new Set([`127.0.0.1:${port}`, `localhost:${port}`]);
  return http.createServer(async (req, res) => {
    const send = (code, type, body, extra = {}) => { res.writeHead(code, { 'Content-Type': type, 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff', ...extra }); res.end(body); };
    try {
      // Only this computer's own page may use the server (blocks other sites and DNS tricks).
      if (!own.has(req.headers.host || '')) return send(403, 'text/plain', 'Forbidden');
      if (req.headers.origin && ![...own].some(h => req.headers.origin === 'http://' + h)) return send(403, 'text/plain', 'Forbidden');
      const url = new URL(req.url, 'http://x');
      const p = url.pathname;
      if (p === '/api/auth' && req.method === 'GET') return send(200, 'application/json', JSON.stringify({ authed: !!token }));
      if (p === '/gh/graphql' && req.method === 'POST' || p.startsWith('/gh/') && req.method === 'GET') {
        const body = req.method === 'POST' ? await new Promise((ok, no) => { const c = []; let n = 0; req.on('data', d => { n += d.length; if (n > 1e6) { no(new Error('too big')); req.destroy(); } else c.push(d); }); req.on('end', () => ok(Buffer.concat(c))); req.on('error', no); }) : undefined;
        const headers = { Accept: 'application/vnd.github+json', 'User-Agent': 'mapgit/' + VERSION };
        if (token) headers.Authorization = 'Bearer ' + token;
        if (body) headers['Content-Type'] = 'application/json';
        let up;
        try { up = await fetch(API + p.slice(3) + url.search, { method: req.method, headers, body }); }
        catch { return send(502, 'application/json', JSON.stringify({ message: 'Cannot reach GitHub' })); }
        const keep = {};
        const type = up.headers.get('content-type') || 'application/json'; for (const h of ['x-ratelimit-remaining', 'x-ratelimit-limit', 'x-ratelimit-reset']) { const v = up.headers.get(h); if (v) keep[h] = v; }
        return send(up.status, type, Buffer.from(await up.arrayBuffer()), { ...keep, 'Cache-Control': 'no-store' });
      }
      const a = req.method === 'GET' && ASSETS[p];
      if (a) return send(200, a[1], fs.readFileSync(path.join(ROOT, a[0])));
      return send(404, 'text/plain', 'Not found');
    } catch (e) { send(500, 'text/plain', 'Error'); }
  });
}

function listen(server, port, tries = 10) {
  return new Promise((ok, no) => {
    const tryPort = (n, left) => {
      const onErr = e => { server.removeListener('listening', onOk); if (e.code === 'EADDRINUSE' && left > 0) tryPort(n + 1, left - 1); else no(e); };
      const onOk = () => { server.removeListener('error', onErr); ok(n); };
      server.once('error', onErr); server.once('listening', onOk); server.listen(n, '127.0.0.1');
    };
    tryPort(port, tries);
  });
}

function openBrowser(url) {
  const [cmd, args] = process.platform === 'darwin' ? ['open', [url]] : process.platform === 'win32' ? ['cmd', ['/c', 'start', '', url]] : ['xdg-open', [url]];
  try { const c = spawn(cmd, args, { stdio: 'ignore', detached: true, windowsHide: true }); c.on('error', () => {}); c.unref(); } catch { /* the address is printed anyway */ }
}

async function main() {
  const o = parse(process.argv.slice(2));
  if (o.help) return void process.stdout.write(HELP);
  if (o.version) return void console.log(VERSION);
  if (o.bad) { console.error(`Unknown option: ${o.bad}\n\n${HELP}`); process.exit(2); }
  if (!Number.isInteger(o.port) || o.port < 1 || o.port > 65535) { console.error('The port must be a number from 1 to 65535.'); process.exit(2); }
  let name = o.repo ? repoName(o.repo) : '', fromFolder = false;
  if (!o.repo) { name = await folderRepo(); fromFolder = !!name; }
  if (o.repo && !name) { console.error(`"${o.repo}" is not a GitHub repository. Use owner/repo or a github.com link.`); process.exit(2); }
  if (Number(process.versions.node.split('.')[0]) < 18) { console.error('Map Git needs Node.js 18 or later.'); process.exit(1); }

  const token = await findToken();
  // The port may move up if it is busy, so the server learns its final port after it starts.
  let server, port = o.port;
  for (let i = 0; i < 10; i++) {
    server = createServer(token, port);
    try { await listen(server, port, 0); break; }
    catch (e) { if (e.code === 'EADDRINUSE' && i < 9) { port++; continue; } console.error(`Cannot start the server: ${e.message}`); process.exit(1); }
  }
  const url = `http://127.0.0.1:${port}/` + (name ? `?repo=${name}` : '');
  console.log(`Map Git is running at ${url}`);
  if (fromFolder) console.log(`Opening ${name}, the GitHub remote of this folder.`);
  console.log(token ? 'Signed in to GitHub. Private repositories and 5,000 requests each hour are available.' : 'Not signed in to GitHub. Public repositories only, and 60 requests each hour.\nTo sign in, run "gh auth login", then start Map Git again.');
  console.log('Press Ctrl+C to stop.');
  if (o.open) openBrowser(url);
  const stop = () => { server.close(); process.exit(0); };
  process.on('SIGINT', stop); process.on('SIGTERM', stop);
}

if (require.main === module) main(); else module.exports = { parse, repoName, remoteRepo, folderRepo, createServer };

'use strict';

const { spawn } = require('node:child_process');
const { mkdtemp, rm, writeFile } = require('node:fs/promises');
const path = require('node:path');

const originalFetch = globalThis.fetch;
const statusMarker = '\n__RSSHUB_INSTAGRAM_STATUS__';
const maxOutputBytes = 20 * 1024 * 1024;
const profileInfoPath = '/api/v1/users/web_profile_info/';
const profileFeedPath = '/api/v1/feed/user/';
const businessSchemaError = 'Asset asset://laser.provider/ig_business_category_subvertical has been deleted. You cannot use this schema';
const instagramHandlePattern = /^[A-Za-z0-9._]{1,30}$/;

function requestUrl(input) {
  if (input && typeof input.url === 'string') {
    return input.url;
  }
  return String(input);
}

function isInstagramApiRequest(url) {
  try {
    const parsed = new URL(url);
    return parsed.protocol === 'https:' && parsed.hostname === 'www.instagram.com';
  } catch {
    return false;
  }
}

function requestHeaders(input, init) {
  const headers = new Headers(input && input.headers ? input.headers : undefined);
  if (init?.headers) {
    new Headers(init.headers).forEach((value, name) => headers.set(name, value));
  }
  return headers;
}

function profileInfoUsername(url) {
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== 'https:' || parsed.hostname !== 'www.instagram.com' || parsed.pathname !== profileInfoPath) {
      return null;
    }
    const username = parsed.searchParams.get('username');
    return username && instagramHandlePattern.test(username) ? username : null;
  } catch {
    return null;
  }
}

function isBusinessProfileSchemaFailure(status, body) {
  return status === 400 && typeof body === 'string' && body.includes(businessSchemaError);
}

function profileInfoFallbackBody(body, username) {
  if (!username || !instagramHandlePattern.test(username)) {
    return null;
  }

  let payload;
  try {
    payload = JSON.parse(body);
  } catch {
    return null;
  }

  if (!payload || typeof payload !== 'object' || !Array.isArray(payload.items)) {
    return null;
  }
  const user = payload.user;
  if (!user || typeof user !== 'object' || Array.isArray(user)) {
    return null;
  }
  if (!('id' in user) || !['string', 'number'].includes(typeof user.id) || String(user.id).trim() === '') {
    return null;
  }

  return JSON.stringify({
    data: {
      user: {
        ...user,
        username: typeof user.username === 'string' && user.username ? user.username : username,
      },
    },
  });
}

async function curlFetch(input, init) {
  const url = requestUrl(input);
  const method = String(init?.method || input?.method || 'GET').toUpperCase();
  if (init?.body) {
    return originalFetch(input, init);
  }

  const headers = requestHeaders(input, init);
  const cookie = headers.get('cookie');
  if (cookie) {
    headers.delete('cookie');
  }

  const csrfToken = headers.get('x-csrftoken');
  if (!cookie || !csrfToken || ['undefined', 'null'].includes(csrfToken.trim().toLowerCase())) {
    headers.delete('x-csrftoken');
  }

  let tempDir;
  if (cookie) {
    tempDir = await mkdtemp('/tmp/rsshub-instagram-');
    const configCookie = cookie.replaceAll('\\', '\\\\').replaceAll('"', '\\"');
    await writeFile(path.join(tempDir, 'curl.conf'), 'header = "cookie: ' + configCookie + '"\n', {
      encoding: 'utf8',
      mode: 0o600,
    });
  }

  const args = [
    '--silent',
    '--show-error',
    '--location',
    '--insecure',
    '--max-time',
    '60',
    '--request',
    method,
  ];

  if (tempDir) {
    args.push('--config', path.join(tempDir, 'curl.conf'));
  }

  headers.forEach((value, name) => {
    if (!['accept-encoding', 'connection', 'content-length', 'host', 'proxy-connection', 'transfer-encoding'].includes(name)) {
      args.push('--header', name + ': ' + value);
    }
  });

  args.push('--write-out', statusMarker + '%{http_code}', '--url', url);

  return new Promise((resolve, reject) => {
    const child = spawn('curl', args, {
      env: {
        ...process.env,
        ALL_PROXY: process.env.PROXY_URI || '',
        HTTPS_PROXY: process.env.PROXY_URI || '',
        HTTP_PROXY: process.env.PROXY_URI || '',
        all_proxy: process.env.PROXY_URI || '',
        https_proxy: process.env.PROXY_URI || '',
        http_proxy: process.env.PROXY_URI || '',
        NO_PROXY: '',
        no_proxy: '',
      },
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    const chunks = [];
    let outputBytes = 0;
    let settled = false;

    const cleanup = () => tempDir && rm(tempDir, { recursive: true, force: true }).catch(() => {});
    const fail = () => {
      if (settled) return;
      settled = true;
      child.kill('SIGTERM');
      cleanup();
      reject(new Error('Instagram curl fetch failed'));
    };

    child.stdout.on('data', (chunk) => {
      outputBytes += chunk.length;
      if (outputBytes > maxOutputBytes) {
        fail();
        return;
      }
      chunks.push(chunk);
    });
    child.stderr.resume();
    child.on('error', fail);
    child.on('close', (code) => {
      if (settled) return;
      settled = true;
      cleanup();
      const output = Buffer.concat(chunks).toString('utf8');
      const markerIndex = output.lastIndexOf(statusMarker);
      if (code !== 0 || markerIndex < 0) {
        reject(new Error('Instagram curl fetch failed'));
        return;
      }

      const status = Number(output.slice(markerIndex + statusMarker.length).trim());
      if (!Number.isInteger(status)) {
        reject(new Error('Instagram curl returned an invalid status'));
        return;
      }

      resolve(new Response(output.slice(0, markerIndex), {
        status,
        headers: { 'content-type': 'application/json' },
      }));
    });
  });
}

async function recoverBusinessProfile(response, url, headers) {
  const body = await response.clone().text();
  const username = profileInfoUsername(url);
  if (!isBusinessProfileSchemaFailure(response.status, body) || !username) {
    return response;
  }

  const feedUrl = `https://www.instagram.com${profileFeedPath}${encodeURIComponent(username)}/username/?count=30`;
  const feedResponse = await curlFetch(feedUrl, { headers });
  if (!feedResponse.ok) {
    return response;
  }

  const feedBody = await feedResponse.text();
  const fallbackBody = profileInfoFallbackBody(feedBody, username);
  if (!fallbackBody) {
    return response;
  }

  return new Response(fallbackBody, {
    status: 200,
    headers: { 'content-type': 'application/json' },
  });
}

async function routedInstagramFetch(input, init) {
  const url = requestUrl(input);
  const headers = requestHeaders(input, init);
  const response = await curlFetch(input, init);
  if (profileInfoUsername(url)) {
    return recoverBusinessProfile(response, url, headers);
  }
  return response;
}

function routedFetch(input, init) {
  let url;
  try {
    url = requestUrl(input);
  } catch {
    return originalFetch(input, init);
  }

  return isInstagramApiRequest(url) ? routedInstagramFetch(input, init) : originalFetch(input, init);
}

globalThis.fetch = routedFetch;

try {
  const undici = require('undici');
  undici.fetch = routedFetch;
} catch {
  // RSSHub's bundled fetch remains available if undici is unavailable.
}

module.exports = {
  businessSchemaError,
  isBusinessProfileSchemaFailure,
  isInstagramApiRequest,
  profileInfoFallbackBody,
  profileInfoUsername,
};

/* Тонкая обёртка над fetch: единый разбор ошибок и хранение токена. */

const TOKEN_KEY = 'rospit_token';
// ключ времён BioEat: переносим токен один раз, чтобы никого не разлогинить
const LEGACY_TOKEN_KEY = 'bioeat_token';

try {
  const legacy = localStorage.getItem(LEGACY_TOKEN_KEY);
  if (legacy) {
    if (!localStorage.getItem(TOKEN_KEY)) localStorage.setItem(TOKEN_KEY, legacy);
    localStorage.removeItem(LEGACY_TOKEN_KEY);
  }
} catch { /* приватный режим Safari */ }

export const auth = {
  get token() {
    try { return localStorage.getItem(TOKEN_KEY) || ''; } catch { return ''; }
  },
  set token(value) {
    try {
      if (value) localStorage.setItem(TOKEN_KEY, value);
      else localStorage.removeItem(TOKEN_KEY);
    } catch { /* приватный режим Safari */ }
  },
};

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function request(method, path, body, options = {}) {
  const headers = { Accept: 'application/json' };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (auth.token) headers.Authorization = `Bearer ${auth.token}`;

  let response;
  try {
    response = await fetch(path, {
      method,
      headers,
      credentials: 'same-origin',
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError('Нет связи с сервером. Проверьте подключение.', 0);
  }

  if (response.status === 204) return null;

  const isJson = (response.headers.get('content-type') || '').includes('application/json');
  const payload = isJson ? await response.json().catch(() => null) : await response.text();

  if (!response.ok) {
    const detail = (payload && payload.detail) || 'Что-то пошло не так';
    const message = typeof detail === 'string' ? detail : JSON.stringify(detail);
    if (response.status === 401 && !options.silent) auth.token = '';
    throw new ApiError(message, response.status);
  }
  return payload;
}

const api = {
  get: (path, opts) => request('GET', path, undefined, opts),
  post: (path, body, opts) => request('POST', path, body ?? {}, opts),
  put: (path, body, opts) => request('PUT', path, body ?? {}, opts),
  patch: (path, body, opts) => request('PATCH', path, body ?? {}, opts),
  del: (path, opts) => request('DELETE', path, undefined, opts),
};

export default api;

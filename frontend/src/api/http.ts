export class APIError extends Error {
  constructor(public readonly status: number, message: string) { super(message); this.name = 'APIError'; }
}

export function queryString(values: object): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined && value !== null && value !== '') params.set(key, String(value));
  }
  const result = params.toString();
  return result ? `?${result}` : '';
}

export async function requestJSON<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData) && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
  const response = await fetch(path, { ...options, headers, credentials: 'same-origin' });
  if (!response.ok) {
    let detail = `请求失败 (${response.status})`;
    try {
      const error = await response.json();
      if (typeof error.detail === 'string') detail = error.detail;
    } catch { /* Keep a safe message for non-JSON errors. */ }
    if (response.status === 401 && !['/auth/me', '/auth/logout'].includes(path)) window.dispatchEvent(new Event('picmanager-session-expired'));
    throw new APIError(response.status, detail);
  }
  return response.status === 204 ? undefined as T : response.json();
}

export function safeAvatar(value?: string): string {
  if (!value) return '/favicon.ico';
  try {
    const url = new URL(value, window.location.origin);
    return ['http:', 'https:'].includes(url.protocol) ? url.href : '/favicon.ico';
  } catch { return '/favicon.ico'; }
}

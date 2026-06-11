/** Thin client for the FastAPI backend. */

// Follow the page's hostname (localhost vs 127.0.0.1 are different origins —
// using the same host keeps CORS consistent however the app was opened).
export const API_BASE =
  import.meta.env.VITE_API_BASE ??
  (typeof window !== 'undefined'
    ? `http://${window.location.hostname}:8000`
    : 'http://localhost:8000');

async function handle(resp: Response) {
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const body = await resp.json();
      detail = body.detail ?? JSON.stringify(body);
    } catch {
      /* keep statusText */
    }
    throw new Error(`${resp.status}: ${detail}`);
  }
  return resp.json();
}

export const get = (path: string) => fetch(`${API_BASE}${path}`).then(handle);

export const post = (path: string, body?: unknown) =>
  fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined
  }).then(handle);

export const put = (path: string, body: unknown) =>
  fetch(`${API_BASE}${path}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  }).then(handle);

export const patch = (path: string, body: unknown) =>
  fetch(`${API_BASE}${path}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  }).then(handle);

export const del = (path: string) =>
  fetch(`${API_BASE}${path}`, { method: 'DELETE' }).then(handle);

export const upload = (path: string, form: FormData) =>
  fetch(`${API_BASE}${path}`, { method: 'POST', body: form }).then(handle);

/** Map a stored file_path (absolute or relative) onto the /storage mount. */
export function mediaUrl(filePath: string | null | undefined): string | null {
  if (!filePath) return null;
  const i = filePath.indexOf('storage/');
  if (i < 0) return null;
  return `${API_BASE}/${filePath.slice(i)}`;
}

export const isImage = (p: string | null | undefined) =>
  !!p && /\.(png|jpe?g|webp|gif)$/i.test(p);
export const isVideo = (p: string | null | undefined) =>
  !!p && /\.(mp4|webm|mov)$/i.test(p);

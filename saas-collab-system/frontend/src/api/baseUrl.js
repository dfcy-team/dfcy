/**
 * Normalize the optional API origin/prefix used by axios and auth calls.
 * A root value (`/`) must become an empty prefix so `/api/...` remains a
 * normal same-origin path instead of the protocol-relative `//api/...`.
 */
export function normalizeApiBaseUrl(value) {
  return String(value ?? '').trim().replace(/\/+$/, '');
}

export const apiBaseUrl = normalizeApiBaseUrl(import.meta.env.VITE_API_BASE_URL);

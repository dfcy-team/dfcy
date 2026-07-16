const SESSION_KEY = 'saas-collab.auth.session.v1';

function storage() {
  return typeof window === 'undefined' ? null : window.sessionStorage;
}

export function readAuthSession() {
  const value = storage()?.getItem(SESSION_KEY);
  if (!value) return null;

  try {
    const session = JSON.parse(value);
    if (!session?.access || !session?.refresh) return null;
    return session;
  } catch {
    clearAuthSession();
    return null;
  }
}

export function writeAuthSession({ access, refresh }) {
  if (!access || !refresh) throw new Error('Access and refresh tokens are required.');
  storage()?.setItem(SESSION_KEY, JSON.stringify({ access, refresh }));
}

export function updateAccessToken(access) {
  const session = readAuthSession();
  if (!session || !access) return false;
  writeAuthSession({ ...session, access });
  return true;
}

export function clearAuthSession() {
  storage()?.removeItem(SESSION_KEY);
}

export function getAccessToken() {
  return readAuthSession()?.access || '';
}

export function getRefreshToken() {
  return readAuthSession()?.refresh || '';
}

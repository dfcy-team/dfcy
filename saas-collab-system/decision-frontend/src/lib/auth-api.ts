"use client";

const SESSION_KEY = "saas-collab.auth.session.v1";

type Session = { access: string; refresh: string };
export type CurrentUser = {
  username: string;
  tenant_id: number;
  user_type: string;
  is_superuser?: boolean;
  roles?: string[];
  permissions?: string[];
};

export type ApiEnvelope<T> = {
  success: boolean;
  code: string;
  message: string;
  data: T;
};

function readSession(): Session | null {
  try {
    const value = window.sessionStorage.getItem(SESSION_KEY);
    const session = value ? JSON.parse(value) as Session : null;
    return session?.access && session?.refresh ? session : null;
  } catch {
    return null;
  }
}

function writeSession(session: Session) {
  window.sessionStorage.setItem(SESSION_KEY, JSON.stringify(session));
}

export function clearSession() {
  window.sessionStorage.removeItem(SESSION_KEY);
}

async function refreshAccess(session: Session): Promise<Session | null> {
  const response = await fetch("/api/internal/auth/refresh/", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ refresh: session.refresh }),
  });
  if (!response.ok) return null;
  const body = await response.json() as { access?: string; data?: { access?: string } };
  const access = body.access || body.data?.access;
  if (!access) return null;
  const updated = { ...session, access };
  writeSession(updated);
  return updated;
}

export async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<ApiEnvelope<T>> {
  let session = readSession();
  if (!session) throw new Error("AUTH_REQUIRED");
  const send = (access: string) => fetch(path, {
    ...init,
    cache: "no-store",
    headers: { ...init.headers, Authorization: `Bearer ${access}` },
  });
  let response = await send(session.access);
  if (response.status === 401) {
    session = await refreshAccess(session);
    if (!session) {
      clearSession();
      throw new Error("AUTH_REQUIRED");
    }
    response = await send(session.access);
  }
  const body = await response.json() as ApiEnvelope<T>;
  if (!response.ok || !body.success) throw new Error(body.message || body.code || "请求失败");
  return body;
}

export const fetchCurrentUser = () => apiRequest<CurrentUser>("/api/internal/auth/me/");

export function can(user: CurrentUser | null, permission: string) {
  return Boolean(user?.is_superuser || user?.permissions?.includes(permission));
}

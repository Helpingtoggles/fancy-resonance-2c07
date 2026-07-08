"use client";

/** Typed fetch client for the HHRN backend. Tokens live in localStorage;
 * 401s clear the session and bounce to /login. */

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

const TOKEN_KEY = "hhrn.access_token";
const REFRESH_KEY = "hhrn.refresh_token";
const USER_KEY = "hhrn.user";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function getStoredUser(): { id: string; email: string; full_name: string; role: string } | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(USER_KEY);
  return raw ? JSON.parse(raw) : null;
}

export function clearSession() {
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(REFRESH_KEY);
  window.localStorage.removeItem(USER_KEY);
}

export async function api<T = unknown>(
  path: string,
  options: RequestInit & { skipAuth?: boolean } = {},
): Promise<T> {
  const headers: Record<string, string> = {
    ...((options.headers as Record<string, string>) || {}),
  };
  if (!(options.body instanceof FormData) && options.body) {
    headers["Content-Type"] = "application/json";
  }
  const token = getToken();
  if (token && !options.skipAuth) headers["Authorization"] = `Bearer ${token}`;

  const resp = await fetch(path, { ...options, headers });
  if (resp.status === 401 && !options.skipAuth) {
    clearSession();
    if (typeof window !== "undefined") window.location.href = "/login";
    throw new ApiError(401, "Session expired");
  }
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const body = await resp.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(resp.status, detail);
  }
  return resp.json() as Promise<T>;
}

export async function login(email: string, password: string) {
  const tokens = await api<{ access_token: string; refresh_token: string }>(
    "/api/v1/auth/login",
    { method: "POST", body: JSON.stringify({ email, password }), skipAuth: true },
  );
  window.localStorage.setItem(TOKEN_KEY, tokens.access_token);
  window.localStorage.setItem(REFRESH_KEY, tokens.refresh_token);
  const user = await api<{ id: string; email: string; full_name: string; role: string }>(
    "/api/v1/auth/me",
  );
  window.localStorage.setItem(USER_KEY, JSON.stringify(user));
  return user;
}

/** Roles allowed to write final values / sign. Mirrors backend SIGNING_ROLES. */
export const SIGNING_ROLES = ["rn_reviewer"];
export const CLINICAL_ROLES = ["rn_reviewer", "clinician"];

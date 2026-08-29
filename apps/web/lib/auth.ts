"use client";

const TOKEN_KEY = "whaleguard.access_token";
const CSRF_KEY = "whaleguard.csrf_token";
const USER_KEY = "whaleguard.user";

export type SessionUser = {
  id?: string;
  username: string;
  display_name?: string;
  role?: string;
};

export function saveSession(accessToken: string, csrfToken: string | undefined, user: SessionUser) {
  localStorage.setItem(TOKEN_KEY, accessToken);
  if (csrfToken) localStorage.setItem(CSRF_KEY, csrfToken);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
  window.dispatchEvent(new Event("whaleguard:session"));
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(CSRF_KEY);
  localStorage.removeItem(USER_KEY);
  window.dispatchEvent(new Event("whaleguard:session"));
}

export function getToken() {
  return typeof window === "undefined" ? null : localStorage.getItem(TOKEN_KEY);
}

export function getCsrfToken() {
  return typeof window === "undefined" ? null : localStorage.getItem(CSRF_KEY);
}

export function getStoredUser(): SessionUser | null {
  if (typeof window === "undefined") return null;
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as SessionUser;
  } catch {
    return null;
  }
}

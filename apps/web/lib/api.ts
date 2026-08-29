"use client";

import { clearSession, getCsrfToken, getToken } from "@/lib/auth";
import type { ApiPage, ApiRecord } from "@/lib/types";
import { apiEntitySchema, loginResponseSchema } from "@/lib/schemas";
import type { z } from "zod";

export const API_BASE = (process.env.NEXT_PUBLIC_API_URL || process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000/api/v1").replace(/\/$/, "");

export class ApiError extends Error {
  status: number;
  detail?: unknown;

  constructor(message: string, status: number, detail?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

type RequestOptions = Omit<RequestInit, "body"> & {
  body?: unknown;
  auth?: boolean;
  timeoutMs?: number;
};

function errorMessage(payload: unknown, status: number) {
  if (status === 401) return "登录已失效，请重新登录";
  if (status === 403) return "当前角色没有执行此操作的权限";
  if (payload && typeof payload === "object" && "detail" in payload) {
    const detail = (payload as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) return detail.map((item) => (typeof item === "object" && item && "msg" in item ? String(item.msg) : String(item))).join("；");
  }
  return `请求失败（HTTP ${status}）`;
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), options.timeoutMs ?? 15000);
  const headers = new Headers(options.headers);
  const token = getToken();
  const csrf = getCsrfToken();
  const auth = options.auth !== false;
  if (auth && token) headers.set("Authorization", `Bearer ${token}`);
  if (auth && csrf && options.method && !["GET", "HEAD", "OPTIONS"].includes(options.method.toUpperCase())) {
    headers.set("X-CSRF-Token", csrf);
  }
  let body: BodyInit | undefined;
  if (options.body instanceof FormData || typeof options.body === "string") {
    body = options.body;
  } else if (options.body !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(options.body);
  }
  headers.set("Accept", "application/json");
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      ...options,
      body,
      headers,
      signal: controller.signal,
      cache: "no-store",
    });
    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json") ? await response.json() : await response.text();
    if (!response.ok) {
      if (auth && response.status === 401) {
        clearSession();
        const current = `${window.location.pathname}${window.location.search}`;
        // A hard navigation also discards any authenticated in-memory query cache.
        // eslint-disable-next-line @next/next/no-location-assign-relative-destination
        window.location.assign(`/login?next=${encodeURIComponent(current)}`);
      }
      throw new ApiError(errorMessage(payload, response.status), response.status, payload);
    }
    return payload as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error instanceof DOMException && error.name === "AbortError") throw new ApiError("请求超时，请检查 API 服务", 408);
    throw new ApiError(error instanceof Error ? error.message : "无法连接 API 服务", 0);
  } finally {
    clearTimeout(timer);
  }
}

export async function login(username: string, password: string) {
  const raw = await apiRequest<unknown>("/auth/login", {
    method: "POST",
    body: { username, password },
    auth: false,
  });
  return loginResponseSchema.parse(raw);
}

export function toPage<T extends ApiRecord>(value: unknown): ApiPage<T> {
  if (Array.isArray(value)) {
    return { items: value as T[], total: value.length, page: 1, page_size: value.length || 20, pages: 1 };
  }
  if (value && typeof value === "object" && "items" in value) {
    const page = value as Partial<ApiPage<T>>;
    const items = Array.isArray(page.items) ? page.items : [];
    return {
      items,
      total: typeof page.total === "number" ? page.total : items.length,
      page: typeof page.page === "number" ? page.page : 1,
      page_size: typeof page.page_size === "number" ? page.page_size : 20,
      pages: typeof page.pages === "number" ? page.pages : 1,
    };
  }
  return { items: [], total: 0, page: 1, page_size: 20, pages: 1 };
}

export async function fetchPage<T extends ApiRecord>(path: string) {
  return toPage<T>(await apiRequest<unknown>(path));
}

export type ApiEntity = z.infer<typeof apiEntitySchema>;

/**
 * Base API client for the MedScribe gateway.
 *
 * `/api/*` is proxied to the backend by Vite (see vite.config.ts). In docker
 * compose VITE_API_TARGET points at the `gateway` service; locally it falls back
 * to http://localhost:8080.
 */

const BASE = "/api";

export class ApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

export type FetchOptions = Omit<RequestInit, "headers"> & {
  headers?: Record<string, string>;
};

/** JSON-by-default fetch wrapper. Returns parsed JSON for JSON responses, otherwise the raw Response. */
export async function apiFetch<T = unknown>(path: string, options: FetchOptions = {}): Promise<T> {
  const headers =
    options.body instanceof FormData
      ? { ...(options.headers ?? {}) }
      : { "Content-Type": "application/json", ...(options.headers ?? {}) };
  const res = await fetch(`${BASE}${path}`, {
    headers,
    ...options,
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new ApiError(res.status, `API ${res.status}: ${body}`);
  }
  const ct = res.headers.get("content-type") ?? "";
  if (ct.includes("application/json")) return res.json() as Promise<T>;
  return res as unknown as T;
}

/** Raw fetch for endpoints that return non-JSON bodies (blobs, text, etc). */
export function apiRawFetch(path: string, options: RequestInit = {}): Promise<Response> {
  return fetch(`${BASE}${path}`, options);
}

export { BASE as API_BASE };

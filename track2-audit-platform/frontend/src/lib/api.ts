import type { ApiResponse, HealthStatus } from "./types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "";

export async function fetchApi<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<ApiResponse<T>> {
  const url = `${API_BASE_URL}${endpoint}`;
  const headers = new Headers(options.headers);

  if (!headers.has("Content-Type") && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(url, {
    ...options,
    headers,
  });

  const data = await response.json();

  if (!response.ok) {
    const errorMsg = data?.error?.message || `HTTP error ${response.status}`;
    const err = new Error(errorMsg);
    (err as unknown as { status: number; payload: unknown }).status = response.status;
    (err as unknown as { status: number; payload: unknown }).payload = data;
    throw err;
  }

  return data as ApiResponse<T>;
}

export async function getHealth(): Promise<ApiResponse<HealthStatus>> {
  return fetchApi<HealthStatus>("/api/v1/health");
}

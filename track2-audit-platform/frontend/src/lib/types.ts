export interface ApiResponse<T> {
  data: T;
  meta: Record<string, unknown>;
  request_id: string;
}

export interface ApiErrorDetail {
  code: string;
  message: string;
  details?: unknown;
}

export interface ApiErrorResponse {
  error: ApiErrorDetail;
  request_id: string;
}

export interface HealthStatus {
  status: string;
  app: string;
  version: string;
  timestamp: string;
  db_backend: string;
}

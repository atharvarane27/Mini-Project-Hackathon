import { describe, it, expect } from "vitest";
import type { ApiResponse, HealthStatus } from "../src/lib/types";

describe("Frontend Health Contract", () => {
  it("should match standard ApiResponse envelope structure", () => {
    const mockHealth: ApiResponse<HealthStatus> = {
      data: {
        status: "ok",
        app: "AuditForge",
        version: "0.1.0",
        timestamp: "2026-10-29T12:00:00Z",
        db_backend: "supabase",
      },
      meta: {},
      request_id: "req-12345",
    };

    expect(mockHealth.data.status).toBe("ok");
    expect(mockHealth.data.app).toBe("AuditForge");
    expect(mockHealth.request_id).toBe("req-12345");
  });
});

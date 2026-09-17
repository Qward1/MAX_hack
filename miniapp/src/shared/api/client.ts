import type { components } from "./schema";
import { maxBridge } from "../max/bridge";

export type Capabilities = components["schemas"]["CapabilitiesResponse"];
export type Me = components["schemas"]["MeResponse"];
export type IncidentList = components["schemas"]["IncidentList"];
// Tolerate future enum values at the read boundary; fields come from generated schema.
export type IncidentSummary = Omit<
  components["schemas"]["IncidentSummary"],
  "status" | "category"
> & { status: string; category: string };
export type IncidentDetail = Omit<
  components["schemas"]["IncidentDetail"],
  "status" | "category"
> & { status: string; category: string };
export type ReportCreate = components["schemas"]["ReportCreate"];
export type Problem = components["schemas"]["Problem"];

type Session = components["schemas"]["SessionResponse"];

export class ApiProblem extends Error {
  constructor(public readonly problem: Problem) {
    super(problem.detail);
  }
}

export function problemStatus(error: unknown): number | undefined {
  return error instanceof ApiProblem ? error.problem.status : undefined;
}
export function retryable(error: unknown): boolean {
  if (!(error instanceof ApiProblem)) return true;
  return error.problem.retryable === true && ![401, 403, 404].includes(error.problem.status);
}

export interface DomSignalApi {
  capabilities(signal?: AbortSignal): Promise<Capabilities>;
  authenticate(capabilities: Capabilities, signal?: AbortSignal): Promise<void>;
  me(signal?: AbortSignal): Promise<Me>;
  incidents(
    houseId: string,
    signal?: AbortSignal,
    offset?: number,
  ): Promise<IncidentList>;
  incident(id: string, signal?: AbortSignal, houseId?: string): Promise<IncidentDetail>;
  createReport(
    payload: ReportCreate,
    idempotencyKey: string,
  ): Promise<IncidentDetail>;
}

export class ApiClient implements DomSignalApi {
  private token: string | null = null;

  async capabilities(signal?: AbortSignal): Promise<Capabilities> {
    return this.request<Capabilities>("/api/v1/capabilities", { signal });
  }

  async authenticate(
    capabilities: Capabilities,
    signal?: AbortSignal,
  ): Promise<void> {
    if (this.token) return;
    const initData = maxBridge.initData;
    let session: Session;
    if (initData) {
      session = await this.request<Session>("/api/v1/auth/max", {
        method: "POST",
        body: JSON.stringify({ init_data: initData }),
        signal,
      });
    } else if (
      capabilities.environment !== "production" &&
      capabilities.features.test_auth
    ) {
      session = await this.request<Session>("/api/v1/auth/test-session", {
        method: "POST",
        body: JSON.stringify({ actor: "demo" }),
        signal,
      });
    } else {
      throw new ApiProblem({
        status: 401,
        type: "about:blank",
        code: "authentication_required",
        title: "Войдите через MAX",
        detail: "Откройте мини-приложение заново в MAX.",
        trace_id: "",
        retryable: false,
      });
    }
    if (!signal?.aborted) this.token = session.access_token;
  }

  me(signal?: AbortSignal): Promise<Me> {
    return this.request<Me>("/api/v1/me", { signal });
  }

  incidents(
    houseId: string,
    signal?: AbortSignal,
    offset = 0,
  ): Promise<IncidentList> {
    return this.request<IncidentList>(
      `/api/v1/houses/${encodeURIComponent(houseId)}/incidents?limit=100&offset=${offset}`,
      { signal },
    );
  }

  incident(id: string, signal?: AbortSignal, houseId?: string): Promise<IncidentDetail> {
    return this.request<IncidentDetail>(
      `/api/v1/incidents/${encodeURIComponent(id)}${houseId !== undefined ? `?house_id=${encodeURIComponent(houseId)}` : ""}`,
      { signal },
    );
  }

  async createReport(
    payload: ReportCreate,
    idempotencyKey: string,
  ): Promise<IncidentDetail> {
    const created = await this.request<components["schemas"]["ReportCreated"]>(
      "/api/v1/reports",
      {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey },
        body: JSON.stringify(payload),
      },
    );
    return created.incident;
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const headers = new Headers(init.headers);
    headers.set("Content-Type", "application/json");
    if (this.token) headers.set("Authorization", `Bearer ${this.token}`);
    const controller = new AbortController();
    const abort = () => controller.abort();
    if (init.signal?.aborted) abort();
    init.signal?.addEventListener("abort", abort, { once: true });
    const timeout = window.setTimeout(abort, 20000);
    try {
      const response = await fetch(path, {
        ...init,
        headers,
        signal: controller.signal,
        cache: "no-store",
      });
      if (!response.ok) {
        const fallback: Problem = {
          type: "about:blank",
          title: "Ошибка запроса",
          status: response.status,
          detail: "Сервис временно недоступен.",
          code: "http_error",
          trace_id: response.headers.get("X-Request-ID") ?? "unknown",
          retryable: response.status >= 500 || [408, 429, 409].includes(response.status),
        };
        let problem = fallback;
        try {
          const body = await response.json();
          if (body && typeof body === "object")
            problem = { ...fallback, ...body, status: response.status };
        } catch {
          // Keep the safe generic problem when the proxy returned non-JSON.
        }
        if (response.status === 401) this.token = null;
        throw new ApiProblem(problem);
      }
      return (await response.json()) as T;
    } finally {
      window.clearTimeout(timeout);
      init.signal?.removeEventListener("abort", abort);
    }
  }
}

export const apiClient = new ApiClient();

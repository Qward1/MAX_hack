import type { components } from "./schema";
import type { ResidentTicketApi } from "./tickets";

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
export type ReportCreated = components["schemas"]["ReportCreated"];
export type Problem = components["schemas"]["Problem"];
export type NotificationLaunch = components["schemas"]["NotificationLaunch"];
export type ActionCard = components["schemas"]["ActionCard"];
export type ActionCardAction = components["schemas"]["ActionCardAction"];
export type RouteChannel = components["schemas"]["RouteChannel"];
export type SafetyBlock = components["schemas"]["SafetyBlock"];
export type RouteOutcomeView = components["schemas"]["RouteOutcomeView"];
export type ReportPreview = components["schemas"]["ReportPreview"];
export type ReportSubmitRequest = components["schemas"]["ReportSubmitRequest"];
export type ReportSubmitted = components["schemas"]["ReportSubmitted"];
export type DuplicateCandidate = components["schemas"]["DuplicateCandidate"];
export type AppealDraftView = components["schemas"]["AppealDraftView"];
export type AppealDraftCreate = components["schemas"]["AppealDraftCreate"];
export type OpenHouse = components["schemas"]["OpenHouse"];

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

export interface DomSignalApi extends ResidentTicketApi {
  notificationLaunch(ref: string, signal?: AbortSignal): Promise<NotificationLaunch>;
  capabilities(signal?: AbortSignal): Promise<Capabilities>;
  authenticate(capabilities: Capabilities, signal?: AbortSignal): Promise<void>;
  me(signal?: AbortSignal): Promise<Me>;
  /** Дома с открытым доступом: их может выбрать любой вошедший через MAX. */
  openHouses(signal?: AbortSignal): Promise<OpenHouse[]>;
  joinOpenHouse(houseId: string): Promise<OpenHouse>;
  incidents(
    houseId: string,
    signal?: AbortSignal,
    offset?: number,
  ): Promise<IncidentList>;
  incident(id: string, signal?: AbortSignal, houseId?: string): Promise<IncidentDetail>;
  createReport(
    payload: ReportCreate,
    idempotencyKey: string,
  ): Promise<ReportCreated>;
  previewReport(
    houseId: string,
    description: string,
    signal?: AbortSignal,
  ): Promise<ReportPreview>;
  submitReport(
    houseId: string,
    payload: ReportSubmitRequest,
    idempotencyKey: string,
  ): Promise<ReportSubmitted>;
  joinIncident(incidentId: string, idempotencyKey: string): Promise<IncidentDetail>;
  routeOutcome(outcomeId: string, signal?: AbortSignal): Promise<RouteOutcomeView>;
  createAppealDraft(payload: AppealDraftCreate): Promise<AppealDraftView>;
  appealDraft(draftId: string, signal?: AbortSignal): Promise<AppealDraftView>;
  saveAppealDraft(
    draftId: string,
    payload: { text: string; version: number },
  ): Promise<AppealDraftView>;
  markAppealFiled(
    draftId: string,
    reference: string | null,
  ): Promise<AppealDraftView>;
}

export class ApiClient implements DomSignalApi {
  private token: string | null = null;
  private csrf: string | null = null;
  constructor(private readonly surface: "resident" | "employee" = "resident") {}

  useSession(token: string) { this.token = token.trim() || null; }

  async employeeSession() {
    const state = await this.request<components["schemas"]["EmployeeSession"]>("/api/v1/auth/employee/session");
    this.csrf = state.csrf_token;
    return state;
  }

  async employeeStep(path: string, payload: object = {}) {
    const state = await this.request<components["schemas"]["EmployeeSession"]>(`/api/v1/auth/employee/${path}`, {
      method: "POST", body: JSON.stringify(payload),
    });
    this.csrf = state.csrf_token;
    return state;
  }

  employeeEnroll() {
    return this.request<components["schemas"]["EmployeeEnrollment"]>("/api/v1/auth/employee/mfa/enroll", {
      method: "POST", body: "{}",
    });
  }

  async employeeLogout() {
    await this.request("/api/v1/auth/employee/logout", { method: "POST", body: "{}" });
    this.csrf = null;
    this.token = null;
  }

  notificationLaunch(ref: string, signal?: AbortSignal): Promise<NotificationLaunch> {
    return this.request(`/api/v1/notification-launch/${encodeURIComponent(ref)}`, { signal });
  }

  async capabilities(signal?: AbortSignal): Promise<Capabilities> {
    return this.request<Capabilities>("/api/v1/capabilities", { signal });
  }

  async authenticate(
    capabilities: Capabilities,
    signal?: AbortSignal,
  ): Promise<void> {
    if (this.token) return;
    if (this.surface === "employee" && !(capabilities.environment !== "production" &&
        capabilities.features.test_auth && new URLSearchParams(window.location.search).has("test_actor"))) {
      const state = await this.employeeSession();
      if (state.stage === "authenticated") return;
      throw new ApiProblem({ status: 401, type: "about:blank", code: "authentication_required",
        title: "Вход сотрудника", detail: "Войдите в кабинет", trace_id: "", retryable: false });
    }
    const initData = this.surface === "resident"
      ? (await import("../max/bridge")).maxBridge.initData : null;
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
        body: JSON.stringify({ actor: new URLSearchParams(window.location.search).get("test_actor")
          ?? (this.surface === "employee" ? "a16-admin" : "demo") }),
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

  async openHouses(signal?: AbortSignal): Promise<OpenHouse[]> {
    const list = await this.request<components["schemas"]["OpenHouseList"]>(
      "/api/v1/open-houses", { signal },
    );
    return list.items;
  }

  joinOpenHouse(houseId: string): Promise<OpenHouse> {
    return this.request<OpenHouse>(
      `/api/v1/open-houses/${encodeURIComponent(houseId)}/join`,
      { method: "POST", body: "{}" },
    );
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

  createReport(
    payload: ReportCreate,
    idempotencyKey: string,
  ): Promise<ReportCreated> {
    // The whole response is returned: the deterministic next-step card lives
    // beside the incident and must not be dropped at the client boundary.
    return this.request<ReportCreated>("/api/v1/reports", {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: JSON.stringify(payload),
    });
  }

  previewReport(
    houseId: string,
    description: string,
    signal?: AbortSignal,
  ): Promise<ReportPreview> {
    return this.request<ReportPreview>(
      `/api/v1/houses/${encodeURIComponent(houseId)}/reports/preview`,
      { method: "POST", body: JSON.stringify({ description }), signal },
    );
  }

  submitReport(
    houseId: string,
    payload: ReportSubmitRequest,
    idempotencyKey: string,
  ): Promise<ReportSubmitted> {
    return this.request<ReportSubmitted>(
      `/api/v1/houses/${encodeURIComponent(houseId)}/reports/submit`,
      {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey },
        body: JSON.stringify(payload),
      },
    );
  }

  joinIncident(incidentId: string, idempotencyKey: string): Promise<IncidentDetail> {
    return this.request<IncidentDetail>(
      `/api/v1/incidents/${encodeURIComponent(incidentId)}/join`,
      { method: "POST", headers: { "Idempotency-Key": idempotencyKey }, body: "{}" },
    );
  }

  routeOutcome(outcomeId: string, signal?: AbortSignal): Promise<RouteOutcomeView> {
    return this.request<RouteOutcomeView>(
      `/api/v1/route-outcomes/${encodeURIComponent(outcomeId)}`,
      { signal },
    );
  }

  createAppealDraft(payload: AppealDraftCreate): Promise<AppealDraftView> {
    return this.request<AppealDraftView>("/api/v1/appeal-drafts", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  appealDraft(draftId: string, signal?: AbortSignal): Promise<AppealDraftView> {
    return this.request<AppealDraftView>(
      `/api/v1/appeal-drafts/${encodeURIComponent(draftId)}`,
      { signal },
    );
  }

  saveAppealDraft(
    draftId: string,
    payload: { text: string; version: number },
  ): Promise<AppealDraftView> {
    return this.request<AppealDraftView>(
      `/api/v1/appeal-drafts/${encodeURIComponent(draftId)}`,
      { method: "PATCH", body: JSON.stringify(payload) },
    );
  }

  markAppealFiled(
    draftId: string,
    reference: string | null,
  ): Promise<AppealDraftView> {
    return this.request<AppealDraftView>(
      `/api/v1/appeal-drafts/${encodeURIComponent(draftId)}/mark-filed`,
      { method: "POST", body: JSON.stringify({ reference }) },
    );
  }

  workStatus: ResidentTicketApi["workStatus"] = (id, signal) =>
    this.request(`/api/v1/incidents/${encodeURIComponent(id)}/work-status`, { signal });

  observe: ResidentTicketApi["observe"] = (id, payload, key) =>
    this.request(`/api/v1/work-attempts/${encodeURIComponent(id)}/observations`, {
      method: "POST", body: JSON.stringify(payload), headers: { "Idempotency-Key": key },
    });

  async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const headers = new Headers(init.headers);
    headers.set("Content-Type", "application/json");
    if (this.token) headers.set("Authorization", `Bearer ${this.token}`);
    if (this.surface === "employee" && this.csrf && init.method === "POST")
      headers.set("X-CSRF-Token", this.csrf);
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
        credentials: this.surface === "employee" ? "same-origin" : "omit",
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
        if (this.surface === "employee" && [401, 403].includes(response.status) &&
            !path.startsWith("/api/v1/auth/"))
          window.dispatchEvent(new CustomEvent("employee-access-lost", { detail: response.status }));
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

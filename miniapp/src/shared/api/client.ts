import type { components } from './schema';

export type Capabilities = components['schemas']['CapabilitiesResponse'];
export type Me = components['schemas']['MeResponse'];
export type IncidentList = components['schemas']['IncidentList'];
export type IncidentDetail = components['schemas']['IncidentDetail'];
export type ReportCreate = components['schemas']['ReportCreate'];
export type Problem = components['schemas']['Problem'];

type Session = components['schemas']['SessionResponse'];

export class ApiProblem extends Error {
  constructor(public readonly problem: Problem) {
    super(problem.detail);
  }
}

export interface DomSignalApi {
  capabilities(): Promise<Capabilities>;
  authenticate(capabilities: Capabilities): Promise<void>;
  me(): Promise<Me>;
  incidents(houseId: string): Promise<IncidentList>;
  incident(id: string): Promise<IncidentDetail>;
  createReport(payload: ReportCreate, idempotencyKey: string): Promise<IncidentDetail>;
}

export class ApiClient implements DomSignalApi {
  private token: string | null = null;

  async capabilities(): Promise<Capabilities> {
    return this.request<Capabilities>('/api/v1/capabilities');
  }

  async authenticate(capabilities: Capabilities): Promise<void> {
    const initData = window.WebApp?.initData;
    let session: Session;
    if (initData) {
      session = await this.request<Session>('/api/v1/auth/max', {
        method: 'POST',
        body: JSON.stringify({ init_data: initData }),
      });
    } else if (capabilities.features.test_auth) {
      session = await this.request<Session>('/api/v1/auth/test-session', {
        method: 'POST',
        body: JSON.stringify({ actor: 'demo' }),
      });
    } else {
      throw new Error('Откройте мини-приложение внутри MAX, чтобы войти.');
    }
    this.token = session.access_token;
  }

  me(): Promise<Me> {
    return this.request<Me>('/api/v1/me');
  }

  incidents(houseId: string): Promise<IncidentList> {
    return this.request<IncidentList>(`/api/v1/houses/${houseId}/incidents`);
  }

  incident(id: string): Promise<IncidentDetail> {
    return this.request<IncidentDetail>(`/api/v1/incidents/${id}`);
  }

  async createReport(payload: ReportCreate, idempotencyKey: string): Promise<IncidentDetail> {
    const created = await this.request<components['schemas']['ReportCreated']>(
      '/api/v1/reports',
      {
        method: 'POST',
        headers: { 'Idempotency-Key': idempotencyKey },
        body: JSON.stringify(payload),
      },
    );
    return created.incident;
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const headers = new Headers(init.headers);
    headers.set('Content-Type', 'application/json');
    if (this.token) headers.set('Authorization', `Bearer ${this.token}`);
    const response = await fetch(path, { ...init, headers });
    if (!response.ok) {
      const fallback: Problem = {
        type: 'about:blank',
        title: 'Ошибка запроса',
        status: response.status,
        detail: 'Сервис временно недоступен.',
        code: 'http_error',
        request_id: response.headers.get('X-Request-ID') ?? 'unknown',
      };
      let problem = fallback;
      try {
        problem = (await response.json()) as Problem;
      } catch {
        // Keep the safe generic problem when the proxy returned non-JSON.
      }
      throw new ApiProblem(problem);
    }
    return (await response.json()) as T;
  }
}

export const apiClient = new ApiClient();

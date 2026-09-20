import { vi } from "vitest";
import {
  ApiProblem,
  type Capabilities,
  type DomSignalApi,
  type IncidentDetail,
} from "../shared/api/client";
export const house = {
  id: "00000000-0000-0000-0000-000000000101",
  name: "Демо-дом",
  address: "Тестовая улица, 1",
  role: "resident" as const,
  is_demo: true,
};
export const capabilities: Capabilities = {
  contract_version: "c0.1",
  environment: "test",
  features: {
    test_auth: true,
    report_create: true,
    incident_board: true,
    incident_detail: true,
    ai_analysis: false,
    max_live: false,
    group_mode: false,
    miniapp: true,
    photo_analysis: false,
    voice: false,
    admin: false,
    routes: false,
    appeals: false,
    reminders: false,
    media: false,
  },
};
export const incident: IncidentDetail = {
  id: "00000000-0000-0000-0000-000000000201",
  house_id: house.id,
  title: "Не работает лифт",
  category: "elevator",
  status: "open",
  description: "Лифт остановился на первом этаже.",
  created_at: "2026-09-17T10:00:00Z",
  report_count: 4,
  allowed_actions: [],
  participant_count: 1,
  updated_at: null,
  due_at: null,
  location: null,
  is_demo: true,
  provenance: { origin: "demo" },
  reports: [
    {
      id: "r1",
      description: "Не открываются двери",
      created_at: "2026-09-17T10:00:00Z",
    },
  ],
  rule: {
    origin: "demo",
    verification_status: "demo",
    source_title: "Тестовый источник",
    source_url: "",
    due_at: null,
    note: "Ответственный и срок не проверены.",
  },
};
export function apiWith(items: IncidentDetail[] = [incident]): DomSignalApi {
  return {
    notificationLaunch: vi.fn(),
    capabilities: vi.fn().mockResolvedValue(capabilities),
    authenticate: vi.fn().mockResolvedValue(undefined),
    me: vi
      .fn()
      .mockResolvedValue({
        id: "user",
        display_name: "Житель",
        houses: [house],
        capabilities: capabilities.features,
      }),
    incidents: vi
      .fn()
      .mockResolvedValue({
        items,
        page: { limit: 100, offset: 0, total: items.length },
      }),
    incident: vi
      .fn()
      .mockImplementation(async (id) => items.find((item) => item.id === id)),
    createReport: vi.fn().mockResolvedValue(incident),
    workStatus: vi.fn().mockResolvedValue({ ticket_id: null }),
    observe: vi.fn(),
  };
}
export function error(status: number) {
  return new ApiProblem({
    status,
    type: "about:blank",
    title: "PRIVATE",
    detail: "PRIVATE",
    code: "failure",
    trace_id: "trace-123",
    retryable: status >= 500 || status === 409,
  });
}
export function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

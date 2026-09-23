import { vi } from "vitest";
import {
  ApiProblem,
  type ActionCard,
  type AppealDraftView,
  type Capabilities,
  type DomSignalApi,
  type IncidentDetail,
  type ReportPreview,
  type RouteOutcomeView,
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
    routes: true,
    appeals: true,
    passive_capture: false,
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
export const route = {
  route_type: "municipality" as const,
  organization_id: "kazan_city",
  organization_name: "Исполком Казани",
  channels: [
    {
      id: "pos_gosuslugi",
      channel_type: "official_web" as const,
      label: "Госуслуги. Решаем вместе",
      url: null,
      phone: null,
      entry_hint: "Госуслуги → Решаем вместе → Подать обращение",
      routes_to_competent_authority: true,
      facts: [
        {
          text: "По закону письменное обращение «рассматривается в течение 30 дней со дня регистрации письменного обращения».",
          source_title: "Федеральный закон № 59-ФЗ, ст. 12 ч. 1",
          source_url: "https://example.org/law",
        },
      ],
      verification_status: "verified" as const,
      verified_at: "2026-09-20",
      source_title: "Правила сервиса",
      source_url: "https://example.org/pos",
      stale: false,
    },
  ],
  basis: {
    rule_id: "street_lighting",
    text: "Уличное освещение обслуживает муниципалитет.",
    source_title: "Правила благоустройства",
    source_url: "https://example.org/rules",
    verified_at: "2026-09-20",
    verification_status: "verified" as const,
  },
  directory_version: "demo-1",
  directory_verified_at: "2026-09-20",
  automatic_integration: false,
  can_create_ticket: false,
  can_prepare_appeal: true,
  requires_operator_choice: false,
  alternatives: [],
  match: "rule" as const,
  hidden_unverified_channels: 0,
  stale: false,
};
export const actionCard: ActionCard = {
  route,
  audience: "resident",
  source: "explicit",
  title: "Проблема, вероятно, относится не к вашей УК",
  explanation: "Вероятно, отвечает: Исполком Казани.",
  safety: null,
  facts: route.channels[0].facts,
  actions: [
    {
      type: "open_official_channel",
      label: "Перейти: Госуслуги. Решаем вместе",
      enabled: false,
      reason: "Точная ссылка входа ещё не заполнена в справочнике.",
      url: null,
      phone: null,
    },
    {
      type: "prepare_appeal",
      label: "Подготовить текст обращения",
      enabled: true,
      reason: null,
      url: null,
      phone: null,
    },
    {
      type: "report_to_uk_anyway",
      label: "Всё равно сообщить в УК",
      enabled: true,
      reason: null,
      url: null,
      phone: null,
    },
  ],
  disclaimer:
    "ДомСигнал не отправляет обращения за вас — вы отправляете его сами в официальном сервисе.",
  demo_notice: "Тестовые данные",
  existing_ticket_ref: null,
  generated_by: "rules",
};
export const outcome: RouteOutcomeView = {
  id: "00000000-0000-0000-0000-0000000003a1",
  house_id: house.id,
  created_at: "2026-09-20T10:00:00Z",
  decision: "external",
  route_type: "municipality",
  action_card: actionCard,
  incident_id: null,
  appeal_draft_id: null,
  directory_changed: false,
};
export const draft: AppealDraftView = {
  id: "00000000-0000-0000-0000-0000000004a1",
  house_id: house.id,
  route_outcome_id: outcome.id,
  text: "Адресат: Исполком Казани\n\nСуть проблемы или предложения:\nу остановки не горят фонари",
  version: 1,
  created_at: "2026-09-20T10:01:00Z",
  updated_at: "2026-09-20T10:01:00Z",
  ai_assisted: true,
  organization_name: "Исполком Казани",
  channel: route.channels[0],
  filed_at: null,
  filed_reference: null,
  provenance: {
    origin: "product_derived",
    note: "Текст собран ДомСигналом из проверенного справочника и слов жителя.",
    recorded_at: "2026-09-20T10:01:00Z",
  },
  allowed_actions: [
    { code: "edit_draft", enabled: true, reason: null },
    { code: "copy_draft", enabled: true, reason: null },
    {
      code: "open_official_channel",
      enabled: false,
      reason: "Точная ссылка входа ещё не заполнена в справочнике.",
    },
    { code: "mark_filed", enabled: true, reason: null },
  ],
};
export const preview: ReportPreview = {
  analysis: {
    subtype: "street_lighting.failure",
    category: "lighting",
    location_scope: "municipal_territory",
    entrance: null,
    floor: null,
    since: null,
    danger_kinds: [],
    mode: "rules",
    confident: true,
    reason: "rule_match",
  },
  action_card: actionCard,
  duplicates: [],
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
    createReport: vi
      .fn()
      .mockResolvedValue({ report_id: "rep-1", incident, action_card: actionCard }),
    previewReport: vi.fn().mockResolvedValue(preview),
    submitReport: vi.fn().mockResolvedValue({
      route_outcome_id: outcome.id,
      decision: "external",
      analysis: preview.analysis,
      action_card: actionCard,
      report: null,
    }),
    joinIncident: vi.fn().mockResolvedValue(incident),
    routeOutcome: vi.fn().mockResolvedValue(outcome),
    createAppealDraft: vi.fn().mockResolvedValue(draft),
    appealDraft: vi.fn().mockResolvedValue(draft),
    saveAppealDraft: vi.fn().mockResolvedValue({ ...draft, version: 2 }),
    markAppealFiled: vi.fn().mockResolvedValue({
      ...draft,
      filed_at: "2026-09-20T11:00:00Z",
      allowed_actions: [
        { code: "edit_draft", enabled: false, reason: "Вы уже отметили подачу этого обращения." },
        { code: "copy_draft", enabled: true, reason: null },
        {
          code: "open_official_channel",
          enabled: false,
          reason: "Точная ссылка входа ещё не заполнена в справочнике.",
        },
        { code: "mark_filed", enabled: false, reason: "Подача уже отмечена." },
      ],
    }),
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

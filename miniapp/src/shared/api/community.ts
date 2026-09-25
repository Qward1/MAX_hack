import type { components } from "./schema";

type Schemas = components["schemas"];
export type HouseOverview = Schemas["HouseOverview"];
export type CompletedWorkList = Schemas["CompletedWorkList"];
export type CompletedWork = Schemas["CompletedWork"];
export type AnnouncementList = Schemas["AnnouncementList"];
export type AnnouncementItem = Schemas["AnnouncementItem"];
export type PollView = Schemas["PollView"];
export type ActivityList = Schemas["ActivityList"];
export type ActivityItem = Schemas["ActivityItem"];
export type ResidentPreferences = Schemas["ResidentPreferences"];
export type ReceptionOverview = Schemas["ReceptionOverview"];
export type VerifiedSource = Schemas["VerifiedSource"];

/** Запросы D3 для жителя: навигатор дома, объявления, опросы, «Мои обращения», приём. */
export interface CommunityApi {
  houseOverview(houseId: string, signal?: AbortSignal): Promise<HouseOverview>;
  completedWorks(
    houseId: string,
    days: 30 | 90,
    offset: number,
    signal?: AbortSignal,
  ): Promise<CompletedWorkList>;
  announcements(houseId: string, offset: number, signal?: AbortSignal): Promise<AnnouncementList>;
  poll(pollId: string, signal?: AbortSignal): Promise<PollView>;
  vote(pollId: string, optionIds: string[]): Promise<PollView>;
  myActivity(offset: number, signal?: AbortSignal): Promise<ActivityList>;
  setPreferences(optOut: boolean): Promise<ResidentPreferences>;
  reception(houseId: string, signal?: AbortSignal): Promise<ReceptionOverview>;
  book(houseId: string, slotId: string, topic: string): Promise<ReceptionOverview>;
  cancelBooking(houseId: string, bookingId: string): Promise<ReceptionOverview>;
}

type Requester = { request<T>(path: string, init?: RequestInit): Promise<T> };

const PAGE = 20;
const id = encodeURIComponent;

/** Реализация поверх уже вошедшего клиента: тот же токен и та же обработка ошибок. */
export function communityApi(client: Requester): CommunityApi {
  const post = <T,>(path: string, body: unknown) =>
    client.request<T>(path, { method: "POST", body: JSON.stringify(body) });
  return {
    houseOverview: (houseId, signal) =>
      client.request(`/api/v1/houses/${id(houseId)}/overview`, { signal }),
    completedWorks: (houseId, days, offset, signal) =>
      client.request(
        `/api/v1/houses/${id(houseId)}/completed-works?days=${days}&limit=${PAGE}&offset=${offset}`,
        { signal },
      ),
    announcements: (houseId, offset, signal) =>
      client.request(
        `/api/v1/houses/${id(houseId)}/announcements?limit=${PAGE}&offset=${offset}`,
        { signal },
      ),
    poll: (pollId, signal) => client.request(`/api/v1/polls/${id(pollId)}`, { signal }),
    vote: (pollId, optionIds) => post(`/api/v1/polls/${id(pollId)}/vote`, { option_ids: optionIds }),
    myActivity: (offset, signal) =>
      client.request(`/api/v1/me/activity?limit=${PAGE}&offset=${offset}`, { signal }),
    setPreferences: (optOut) => post("/api/v1/me/preferences", { broadcast_opt_out: optOut }),
    reception: (houseId, signal) =>
      client.request(`/api/v1/houses/${id(houseId)}/reception`, { signal }),
    book: (houseId, slotId, topic) =>
      post(`/api/v1/houses/${id(houseId)}/reception/bookings`, { slot_id: slotId, topic }),
    cancelBooking: (houseId, bookingId) =>
      post(`/api/v1/houses/${id(houseId)}/reception/bookings/${id(bookingId)}/cancel`, {}),
  };
}

export const PAGE_SIZE = PAGE;

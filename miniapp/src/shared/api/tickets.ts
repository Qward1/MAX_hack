import type { components } from "./schema";
import { ApiClient } from "./client";

type Schema = components["schemas"];
export type Ticket = Omit<
  Schema["TicketView"],
  "status" | "allowed_actions"
> & {
  status: string;
  allowed_actions: unknown;
};
export type WorkStatus = Omit<
  Schema["ResidentWorkStatus"],
  "status" | "allowed_actions"
> & {
  status: string | null;
  allowed_actions: unknown;
};
export type Attempt = Schema["AttemptView"];
export type TicketEvent = Schema["EventView"];
export type TicketAction = Schema["TicketAction"];
export type Observation = Schema["ObservationRecorded"];
export type PageMeta = Schema["PageMeta"];
export type TicketPage = { items: Ticket[]; page: PageMeta };
export type TicketCommand =
  | Schema["TicketCommand"]
  | Schema["AssignCommand"]
  | Schema["WorkAttemptCreate"]
  | Schema["ReasonCommand"];
export interface ResidentTicketApi {
  workStatus(id: string, signal?: AbortSignal): Promise<WorkStatus>;
  observe(
    id: string,
    payload: Schema["ObservationCreate"],
    key: string,
  ): Promise<Observation>;
}
export class TicketClient extends ApiClient {
  constructor() {
    super("employee");
  }
  tickets(
    house: string,
    filter: string,
    me: string,
    offset: number,
    signal?: AbortSignal,
  ) {
    const query = new URLSearchParams({
      house_id: house,
      limit: "20",
      offset: String(offset),
    });
    if (
      ["new", "in_progress", "verification_pending", "closed"].includes(filter)
    )
      query.set("status", filter);
    if (filter === "mine") query.set("assignee_id", me);
    return this.request<TicketPage>(`/api/v1/tickets?${query}`, { signal });
  }
  ticket(id: string, signal?: AbortSignal) {
    return this.request<Ticket>(`/api/v1/tickets/${encodeURIComponent(id)}`, {
      signal,
    });
  }
  command(
    id: string,
    action: TicketAction,
    payload: TicketCommand,
    key: string,
  ) {
    return this.request<Schema["TicketMutation"]>(
      `/api/v1/tickets/${encodeURIComponent(id)}/${action}`,
      {
        method: "POST",
        body: JSON.stringify(payload),
        headers: { "Idempotency-Key": key },
      },
    );
  }
  assignees(id: string, offset: number, signal?: AbortSignal) {
    return this.request<Schema["AssigneeList"]>(
      `/api/v1/tickets/${encodeURIComponent(id)}/assignees?limit=100&offset=${offset}`,
      { signal },
    );
  }
  attempts(id: string, offset: number, signal?: AbortSignal) {
    return this.request<Schema["AttemptList"]>(
      `/api/v1/tickets/${encodeURIComponent(id)}/work-attempts?limit=20&offset=${offset}`,
      { signal },
    );
  }
  events(id: string, offset: number, signal?: AbortSignal) {
    return this.request<Schema["EventList"]>(
      `/api/v1/tickets/${encodeURIComponent(id)}/events?limit=20&offset=${offset}`,
      { signal },
    );
  }
}
export const ticketClient = new TicketClient();

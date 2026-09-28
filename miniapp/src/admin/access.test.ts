import { afterEach, describe, expect, it, vi } from "vitest";
import { ticketClient } from "../shared/api/tickets";

/**
 * B-08 / D-04: какой отказ сбрасывает вход сотрудника. 401 — вход потерян;
 * 403 раздела кабинета УК — «раздел недоступен», меню и вход остаются.
 */
function reply(status: number) {
  return vi.fn(async () => new Response(JSON.stringify({ status, code: "x", detail: "нет" }), { status }));
}

describe("employee access events", () => {
  afterEach(() => vi.unstubAllGlobals());

  it.each([
    ["/api/v1/companies/c1/staff", 403, false],
    ["/api/v1/companies/c1/staff", 401, true],
    ["/api/v1/platform/bootstrap", 403, true],
  ])("%s → %i: сброс входа %s", async (path, status, expected) => {
    vi.stubGlobal("fetch", reply(status));
    const lost = vi.fn();
    window.addEventListener("employee-access-lost", lost);
    await expect(ticketClient.request(path)).rejects.toBeTruthy();
    window.removeEventListener("employee-access-lost", lost);
    expect(lost).toHaveBeenCalledTimes(expected ? 1 : 0);
  });
});

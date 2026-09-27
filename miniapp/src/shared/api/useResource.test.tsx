import { act, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useResource } from "./useResource";

/** F1 §2.3: экран обновляется сам — опрос, пока вкладка видима, и тихое перечитывание. */
function Probe({ load, poll }: { load: () => Promise<number>; poll: number | false }) {
  const resource = useResource("probe", load, { poll });
  return <p>{resource.loading ? "loading" : `value ${resource.data}`}</p>;
}

function visibility(state: "visible" | "hidden") {
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => state });
}

describe("useResource auto refresh", () => {
  afterEach(() => {
    vi.useRealTimers();
    visibility("visible");
  });

  it("polls while visible, keeps data on screen and stops on a hidden tab", async () => {
    vi.useFakeTimers();
    visibility("visible");
    let value = 0;
    const load = vi.fn(async () => ++value);
    const view = render(<Probe load={load} poll={5000} />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10);
    });
    expect(view.getByText("value 1")).toBeTruthy();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(load).toHaveBeenCalledTimes(2);
    expect(view.getByText("value 2")).toBeTruthy(); // без «loading» между чтениями
    visibility("hidden");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(20000);
    });
    expect(load).toHaveBeenCalledTimes(2);
  });

  it("does not poll without the option", async () => {
    vi.useFakeTimers();
    visibility("visible");
    const load = vi.fn(async () => 1);
    render(<Probe load={load} poll={false} />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60000);
    });
    expect(load).toHaveBeenCalledTimes(1);
  });
});

import { describe, expect, it, vi } from "vitest";
import { createMaxBridge, safeUrl } from "./bridge";

describe("MAX boundary", () => {
  it("reads a bounded opaque start_param as a selector", () => {
    const ref = "w_" + "a".repeat(32);
    expect(createMaxBridge(() => ({ initData: `start_param=${ref}` })).startParam).toBe(ref);
    expect(createMaxBridge(() => ({ initData: "start_param=tenant-permissions" })).startParam).toBeNull();
    expect(createMaxBridge(() => undefined).startParam).toBeNull();
  });
  it("passes every launch ref the resolver accepts, including chat posts and mailings (D3)", () => {
    for (const prefix of ["w", "r", "t", "p", "n"]) {
      const ref = `${prefix}_${"b".repeat(32)}`;
      expect(createMaxBridge(() => ({ initData: `start_param=${ref}` })).startParam).toBe(ref);
    }
    // `c_` из кнопки чата сервер уже учёл при входе; экрану это не цель.
    expect(createMaxBridge(() => ({ initData: `start_param=c_${"b".repeat(32)}` })).startParam).toBeNull();
    expect(createMaxBridge(() => ({ initData: `start_param=t_${"b".repeat(31)}` })).startParam).toBeNull();
  });
  it("works outside MAX without global access errors", () => {
    const bridge = createMaxBridge(() => undefined);
    expect(bridge.platform).toBe("browser");
    expect(bridge.initData).toBe("");
    expect(bridge.clientVersion).toBeNull();
    expect(bridge.capabilities.backButton).toBe(false);
    bridge.subscribeBack(vi.fn())();
    expect(bridge.openLink("https://example.org")).toBe(false);
  });
  it("detects methods rather than guessing from platform", () => {
    const bridge = createMaxBridge(() => ({ platform: "android" }));
    expect(bridge.capabilities.openMaxLink).toBe(false);
    expect(bridge.capabilities.nativeSharing).toBe(false);
  });
  it("does not claim web supports native sharing even when a JS stub exists", () => {
    const bridge = createMaxBridge(() => ({
      platform: "web",
      shareContent: vi.fn(),
    }));
    expect(bridge.capabilities.nativeSharing).toBe(false);
  });
  it("detects mobile sharing and client metadata", () => {
    const bridge = createMaxBridge(() => ({
      platform: "ios",
      version: "26.19.1",
      initData: "test-only",
      shareContent: vi.fn(),
    }));
    expect(bridge.capabilities.nativeSharing).toBe(true);
    expect(bridge.clientVersion).toBe("26.19.1");
  });
  it("subscribes and unsubscribes the identical callback", () => {
    const callback = vi.fn();
    const BackButton = {
      show: vi.fn(),
      hide: vi.fn(),
      onClick: vi.fn(),
      offClick: vi.fn(),
    };
    const bridge = createMaxBridge(() => ({ BackButton }));
    const unsubscribe = bridge.subscribeBack(callback);
    expect(BackButton.show).toHaveBeenCalledOnce();
    expect(BackButton.onClick).toHaveBeenCalledWith(callback);
    unsubscribe();
    expect(BackButton.offClick).toHaveBeenCalledWith(callback);
    expect(BackButton.hide).toHaveBeenCalledOnce();
  });
  it("does not subscribe when offClick is missing", () => {
    const onClick = vi.fn();
    const bridge = createMaxBridge(() => ({
      BackButton: { show: vi.fn(), onClick },
    }));
    bridge.subscribeBack(vi.fn())();
    expect(onClick).not.toHaveBeenCalled();
  });
  it("falls back if a bridge method throws", () => {
    const bridge = createMaxBridge(() => ({
      platform: "web",
      openLink: () => {
        throw new Error("unsupported");
      },
    }));
    expect(bridge.openLink("https://example.org")).toBe(false);
  });
  it("opens supported links and rejects unsafe schemes", () => {
    const openLink = vi.fn();
    const openMaxLink = vi.fn();
    const bridge = createMaxBridge(() => ({
      platform: "web",
      openLink,
      openMaxLink,
    }));
    expect(bridge.openLink("https://example.org")).toBe(true);
    expect(bridge.openMaxLink("https://max.ru/bot")).toBe(true);
    expect(openMaxLink).toHaveBeenCalledWith("https://max.ru/bot");
    expect(bridge.openLink("javascript:alert(1)")).toBe(false);
    expect(openLink).toHaveBeenCalledOnce();
  });
  it("retains normal anchor navigation when CDN exists outside a MAX host", () => {
    const openLink = vi.fn();
    expect(
      createMaxBridge(() => ({ openLink })).openLink("https://example.org"),
    ).toBe(false);
    expect(openLink).not.toHaveBeenCalled();
  });
  it.each([
    "javascript:alert(1)",
    "data:text/html,a",
    "https://user:password@example.org",
    "/relative",
    "",
  ])("rejects unsafe source %s", (value) => {
    expect(safeUrl(value)).toBeNull();
  });
});

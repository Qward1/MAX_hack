// Official API: https://dev.max.ru/docs/webapps/bridge (checked 2026-09-17).
// Keep all MAX globals here. Presence of the JS bridge is not authentication.
export interface MaxWebApp {
  initData?: string;
  platform?: string;
  version?: string;
  BackButton?: {
    show?: () => void;
    hide?: () => void;
    onClick?: (callback: () => void) => void;
    offClick?: (callback: () => void) => void;
  };
  openLink?: (url: string) => void;
  openMaxLink?: (url: string) => void;
  shareContent?: (params: {
    text?: string;
    link?: string;
  }) => Promise<unknown> | void;
}

/**
 * Ссылки запуска, которые разрешает резолвер: `w_` — работа по заявке, `r_` —
 * карточка маршрута, `t_` — пост о заявке в чате, `p_` — пост объявления или
 * опроса в чате, `n_` — личное сообщение рассылки (D3). Ссылка `c_…` из
 * кнопки в чате уже учтена при входе (сервер проверил участие в этом чате),
 * остальные параметры ничего не значат. Одно правило для моста и экрана.
 */
export const LAUNCH_REF = /^[wrtpn]_[A-Za-z0-9_-]{32}$/;

export function safeUrl(value: string | null | undefined): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return ["https:", "http:"].includes(url.protocol) &&
      !url.username &&
      !url.password
      ? url.href
      : null;
  } catch {
    return null;
  }
}

export function createMaxBridge(
  read: () => MaxWebApp | undefined = () => window.WebApp,
) {
  return {
    get platform() {
      return read()?.platform ?? "browser";
    },
    get clientVersion() {
      return read()?.version ?? null;
    },
    get initData() {
      return read()?.initData ?? "";
    },
    get startParam() {
      // Selector only. The authenticated server resolver rechecks actor and current access.
      const value = new URLSearchParams(read()?.initData ?? "").get("start_param");
      return value && LAUNCH_REF.test(value) ? value : null;
    },
    get capabilities() {
      const app = read();
      const back = app?.BackButton;
      return {
        bridge: Boolean(app),
        backButton: [
          back?.show,
          back?.hide,
          back?.onClick,
          back?.offClick,
        ].every((fn) => typeof fn === "function"),
        openLink: typeof app?.openLink === "function",
        openMaxLink: typeof app?.openMaxLink === "function",
        // shareContent is documented only for iOS/Android; bridge JS may expose a stub on web.
        nativeSharing:
          ["ios", "android"].includes(app?.platform ?? "") &&
          typeof app?.shareContent === "function",
      };
    },
    subscribeBack(callback: () => void): () => void {
      const back = read()?.BackButton;
      if (!this.capabilities.backButton || !back) return () => {};
      const cleanup = () => {
        try {
          back.offClick?.(callback);
        } catch {
          /* Browser navigation remains available. */
        }
        try {
          back.hide?.();
        } catch {
          /* Client may have closed. */
        }
      };
      try {
        back.onClick?.(callback);
        back.show?.();
      } catch {
        cleanup();
      }
      return cleanup;
    },
    // Return false if no usable bridge method; caller retains a normal, accessible link.
    openLink(value: string, max = false): boolean {
      const url = safeUrl(value);
      if (!url) return false;
      const app = read();
      // The CDN also exposes methods in an ordinary browser, where there is no host.
      if (!["ios", "android", "desktop", "web"].includes(app?.platform ?? ""))
        return false;
      const method =
        max && new URL(url).hostname === "max.ru"
          ? app?.openMaxLink
          : app?.openLink;
      try {
        if (typeof method !== "function") return false;
        method.call(app, url);
        return true;
      } catch {
        return false;
      }
    },
    openMaxLink(value: string): boolean {
      return this.openLink(value, true);
    },
  };
}

export const maxBridge = createMaxBridge();

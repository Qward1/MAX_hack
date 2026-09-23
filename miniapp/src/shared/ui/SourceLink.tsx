import { maxBridge, safeUrl } from "../max/bridge";

/** Ссылка на источник факта; без проверенного адреса — только его название. */
export function SourceLink({ url, title }: { url?: string | null; title?: string | null }) {
  const safe = safeUrl(url);
  if (!safe) return title ? <span className="muted">Источник: {title}</span> : null;
  return (
    <a
      href={safe}
      target="_blank"
      rel="noopener noreferrer"
      onClick={(event) => {
        if (maxBridge.openLink(safe)) event.preventDefault();
      }}
    >
      Источник: {title || "официальная страница"} ↗
    </a>
  );
}

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

/**
 * Источник факта одной строкой: длинное юридическое название обрезано и не
 * спорит с самим фактом, полностью — с датой проверки и ссылкой — по раскрытию.
 * Название целиком остаётся в тексте строки: экранный диктор читает его полностью.
 */
export function SourceDisclosure({
  url,
  title,
  verified,
  label = "Источник",
}: {
  url?: string | null;
  title?: string | null;
  /** День проверки, уже отформатированный (formatDay). */
  verified?: string | null;
  label?: string;
}) {
  const safe = safeUrl(url);
  if (!title && !safe) return null;
  const name = title || "официальная страница";
  return (
    <details className="ds-source-line">
      <summary>
        <span className="ds-source-text">
          {label}: {name}
        </span>
      </summary>
      <div className="ds-source-body">
        {safe ? (
          <a
            href={safe}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(event) => {
              if (maxBridge.openLink(safe)) event.preventDefault();
            }}
          >
            {name}{" "}
            <span aria-hidden="true">↗</span>{" "}
            <span className="ds-visually-hidden">(откроется отдельно)</span>
          </a>
        ) : (
          <p>{name}</p>
        )}
        {verified && <p className="ds-meta">Проверено: {verified}</p>}
      </div>
    </details>
  );
}

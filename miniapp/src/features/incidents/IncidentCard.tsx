import type { IncidentSummary } from "../../shared/api/client";
import { countLabel, formatWhen } from "../../shared/ui/format";
import { StatusBadge } from "../../shared/ui/semantic";
import { categoryLabel } from "./presentation";

export function placeText(location: IncidentSummary["location"]): string | null {
  if (!location) return null;
  return (
    [location.entrance && `подъезд ${location.entrance}`, location.floor && `этаж ${location.floor}`, location.label]
      .filter(Boolean)
      .join(", ") || null
  );
}

/**
 * Строка проблемы в списке: поля всегда на одних местах — название и статус,
 * описание в две строки, место, сколько соседей и когда обновлено.
 * Вся строка — ссылка на проблему: заголовок цветом текста, справа шеврон.
 * `mine` — своё сообщение жителя и ход его заявки (из «Мои обращения»).
 */
export function IncidentRow({
  incident,
  href,
  onNavigate,
  detailAvailable = true,
  mine,
}: {
  incident: IncidentSummary;
  href: string;
  onNavigate: (href: string) => void;
  detailAvailable?: boolean;
  mine?: string;
}) {
  const updated = formatWhen(incident.updated_at ?? incident.created_at);
  const meta = [
    categoryLabel(incident.category),
    placeText(incident.location),
    incident.participant_count !== null ? countLabel(incident.participant_count, ["сосед", "соседа", "соседей"]) : null,
    updated && `обновлено ${updated}`,
  ].filter(Boolean);
  const body = (
    <>
      <span className="ds-row-head">
        <span className="ds-row-title">{incident.title || "Проблема дома"}</span>
        <StatusBadge status={incident.status} />
      </span>
      {incident.description && <span className="ds-row-text">{incident.description}</span>}
      <span className="ds-meta">{meta.join(" · ")}</span>
      {mine && <span className="ds-row-mine">{mine}</span>}
      {incident.status === "reported" && (
        <span className="ds-meta">Регистрацию во внешней системе ДомСигнал не подтверждает.</span>
      )}
    </>
  );
  if (!detailAvailable) return <div className="ds-row">{body}</div>;
  return (
    <a
      className="ds-row"
      href={href}
      onClick={(event) => {
        if (!event.ctrlKey && !event.metaKey && !event.shiftKey && event.button === 0) {
          event.preventDefault();
          onNavigate(href);
        }
      }}
    >
      {body}
    </a>
  );
}

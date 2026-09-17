import { Button, Flex, Panel, Typography } from "@maxhub/max-ui";
import type { IncidentSummary } from "../../shared/api/client";
import { SourceChip, StatusBadge } from "../../shared/ui/semantic";
import { categoryLabel } from "./presentation";

export function IncidentCard({
  incident,
  href,
  onNavigate,
  detailAvailable = true,
}: {
  incident: IncidentSummary;
  href: string;
  onNavigate: (href: string) => void;
  detailAvailable?: boolean;
}) {
  return (
    <Panel className="incident-card">
      <Flex gap={12} wrap="wrap" justify="space-between">
        <Typography.Text variant="label" color="secondary">
          {categoryLabel(incident.category)}
        </Typography.Text>
        <StatusBadge status={incident.status} />
      </Flex>
      <Typography.Title asChild>
        <h3>{incident.title || "Проблема дома"}</h3>
      </Typography.Title>
      <p className="card-description muted">
        {incident.description || "Описание пока не добавлено"}
      </p>
      {incident.status === "reported" && (
        <p className="muted">Внешняя регистрация не подтверждена.</p>
      )}
      <SourceChip source={incident.provenance} />
      <p className="muted">Участников: {incident.participant_count ?? "нет данных"}</p>
      <Flex
        className="card-footer"
        align="center"
        justify="space-between"
        gap={12}
        wrap="wrap"
      >
        <Typography.Text variant="detail">
          Сообщений: {incident.report_count ?? "нет данных"}
        </Typography.Text>
        {detailAvailable && (
          <Button asChild size="small" variant="secondary">
            <a
              href={href}
              aria-label={`Открыть: ${incident.title}`}
              onClick={(event) => {
                if (
                  !event.ctrlKey &&
                  !event.metaKey &&
                  !event.shiftKey &&
                  event.button === 0
                ) {
                  event.preventDefault();
                  onNavigate(href);
                }
              }}
            >
              Открыть ↗
            </a>
          </Button>
        )}
      </Flex>
    </Panel>
  );
}

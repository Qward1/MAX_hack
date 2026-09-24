import { Button, Panel, Typography } from "@maxhub/max-ui";
import { useState } from "react";
import {
  type DomSignalApi,
  type OpenHouse,
  problemStatus,
} from "../../shared/api/client";
import { StatePanel } from "../../shared/ui/semantic";

/** Человеческая причина, почему не удалось выбрать дом. */
export function joinError(error: unknown): string {
  const status = problemStatus(error);
  if (status === 404) return "Этот дом больше нельзя выбрать. Обновите список.";
  if (status === 401)
    return "Сессия истекла. Закройте мини-приложение и откройте его снова в MAX.";
  if (status === 429) return "Слишком много попыток. Подождите минуту и повторите.";
  return "Не удалось выбрать дом. Проверьте соединение и попробуйте ещё раз.";
}

/**
 * Пустое состояние без тупика: как попасть в свой дом.
 *
 * Основной путь — кнопка «Открыть ДомСигнал» из сообщения бота в домовом чате:
 * сервер проверит участие в чате. Второй путь — дома с открытым доступом,
 * если управляющая компания его включила.
 */
export function NoHouse({
  client,
  houses,
  loadError,
  busy,
  onRefresh,
  onJoined,
}: {
  client: DomSignalApi;
  houses: OpenHouse[];
  loadError: boolean;
  busy: boolean;
  onRefresh: () => void;
  onJoined: (houseId: string) => void;
}) {
  const [joining, setJoining] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  async function join(house: OpenHouse) {
    setJoining(house.id);
    setError(null);
    try {
      await client.joinOpenHouse(house.id);
      onJoined(house.id);
    } catch (reason) {
      setError(joinError(reason));
    } finally {
      setJoining(null);
    }
  }
  return (
    <>
      <Panel className="detail-section no-house">
        <Typography.Title asChild>
          <h2>Пока нет доступных домов</h2>
        </Typography.Title>
        <p>
          <strong>Откройте ДомСигнал кнопкой из вашего домового чата.</strong>
        </p>
        <p className="muted">
          Кнопка «Открыть ДомСигнал» есть в сообщении бота в чате дома. Мы проверим, что
          вы участник чата, и дом появится здесь.
        </p>
        <Button variant="secondary" disabled={busy} onClick={onRefresh}>
          Обновить
        </Button>
      </Panel>
      {loadError ? (
        <StatePanel
          title="Не удалось загрузить список домов"
          detail="Проверьте соединение и попробуйте ещё раз."
          action="Повторить"
          onAction={onRefresh}
        />
      ) : (
        houses.length > 0 && (
          <Panel className="detail-section open-houses">
            <Typography.Title asChild>
              <h2>Выберите дом</h2>
            </Typography.Title>
            <p className="muted">
              Эти дома открыты для всех жителей: выберите свой, чтобы сообщать о
              проблемах и видеть доску дома.
            </p>
            <ul className="open-house-list" aria-label="Дома, которые можно выбрать">
              {houses.map((house) => (
                <li key={house.id}>
                  <span>{house.address}</span>
                  <Button
                    disabled={joining !== null || busy}
                    aria-label={`Присоединиться: ${house.address}`}
                    onClick={() => void join(house)}
                  >
                    {joining === house.id ? "Присоединяем…" : "Присоединиться"}
                  </Button>
                </li>
              ))}
            </ul>
            {joining && (
              <p role="status" className="refresh-notice">
                Подключаем дом…
              </p>
            )}
            {error && (
              <p role="alert" className="refresh-notice">
                {error}
              </p>
            )}
          </Panel>
        )
      )}
    </>
  );
}

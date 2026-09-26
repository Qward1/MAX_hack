import { useState } from "react";
import { type DomSignalApi, type OpenHouse, problemStatus } from "../../shared/api/client";
import { Button } from "../../shared/ui/Button";
import { Notice, StatePanel } from "../../shared/ui/semantic";

/** Человеческая причина, почему не удалось выбрать дом. */
export function joinError(error: unknown): string {
  const status = problemStatus(error);
  if (status === 404) return "Этот дом больше нельзя выбрать. Обновите список.";
  if (status === 401) return "Сессия истекла. Закройте мини-приложение и откройте его снова в MAX.";
  if (status === 429) return "Слишком много попыток. Подождите минуту и повторите.";
  return "Не удалось выбрать дом. Проверьте интернет и попробуйте ещё раз.";
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
      <section className="ds-section no-house" aria-labelledby="no-house-chat">
        <h2 id="no-house-chat">Откройте ДомСигнал кнопкой из вашего домового чата.</h2>
        <p>
          В домовом чате есть сообщение бота с кнопкой «Открыть ДомСигнал». Мы проверим, что вы участник чата, и
          дом появится здесь.
        </p>
        <div className="ds-actions">
          <Button disabled={busy} loading={busy} loadingLabel="Проверяем…" onClick={onRefresh}>
            Проверить снова
          </Button>
        </div>
      </section>
      {loadError ? (
        <StatePanel
          kind="error"
          title="Не удалось загрузить список домов"
          detail="Проверьте интернет и попробуйте ещё раз."
          action="Повторить"
          onAction={onRefresh}
        />
      ) : (
        houses.length > 0 && (
          <section className="ds-group open-houses" aria-labelledby="open-houses-title">
            <h2 id="open-houses-title">Дома с открытым доступом</h2>
            <p className="ds-subtle">
              Их управляющая компания разрешила выбрать дом без домового чата. Выберите свой, чтобы сообщать о
              проблемах и видеть проблемы дома.
            </p>
            <ul className="ds-list" aria-label="Дома, которые можно выбрать">
              {houses.map((house) => (
                <li key={house.id} className="ds-row">
                  <span className="ds-row-head">
                    <span className="ds-row-title">{house.address}</span>
                    <Button
                      small
                      disabled={joining !== null || busy}
                      loading={joining === house.id}
                      loadingLabel="Выбираем…"
                      aria-label={`Выбрать дом: ${house.address}`}
                      onClick={() => void join(house)}
                    >
                      Выбрать дом
                    </Button>
                  </span>
                </li>
              ))}
            </ul>
            {error && (
              <Notice tone="danger" role="alert">
                <p>{error}</p>
              </Notice>
            )}
          </section>
        )
      )}
    </>
  );
}

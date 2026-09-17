import { Button, Textarea, Typography } from "@maxhub/max-ui";
import { type FormEvent, useRef, useState } from "react";
import { ApiProblem, retryable, type DomSignalApi, type ReportCreate } from "../../shared/api/client";
import { categoryLabels } from "./presentation";

// Preserved FND-01 manual report flow. B-02 does not add analysis or appeal screens.
export function ReportForm({
  houseId,
  client,
  onCreated,
}: {
  houseId: string;
  client: DomSignalApi;
  onCreated: () => void;
}) {
  const [category, setCategory] =
    useState<ReportCreate["category"]>("elevator");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [saving, setSaving] = useState(false);
  const pending = useRef(false);
  const attempt = useRef<{ body: string; key: string } | null>(null);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (pending.current) return;
    pending.current = true;
    setSaving(true);
    setError(null);
    const payload: ReportCreate = {
      house_id: houseId,
      category,
      description,
      classification_mode: "manual",
    };
    const body = JSON.stringify(payload);
    if (attempt.current?.body !== body)
      attempt.current = { body, key: crypto.randomUUID() };
    try {
      await client.createReport(payload, attempt.current.key);
      onCreated();
    } catch (failure) {
      setError(failure);
    } finally {
      pending.current = false;
      setSaving(false);
    }
  }
  return (
    <form className="report-form" onSubmit={(event) => void submit(event)}>
      <Typography.Title asChild>
        <h2>Что случилось?</h2>
      </Typography.Title>
      <label>
        Категория
        <select
          disabled={saving}
          value={category}
          onChange={(event) => {
            setCategory(event.target.value as ReportCreate["category"]);
            setError(null);
          }}
        >
          {Object.entries(categoryLabels).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <label>
        Описание
        <Textarea
          disabled={saving}
          value={description}
          onChange={(event) => {
            setDescription(event.target.value);
            setError(null);
          }}
          minLength={5}
          maxLength={2000}
          required
          placeholder="Например: лифт не реагирует на кнопку на первом этаже"
        />
      </label>
      <p className="muted">
        Категория выбрана вручную. Маршрут и обращение ещё не формируются.
      </p>
      {Boolean(error) && (
        <p role="alert">
          Не удалось сохранить сигнал. Текст сохранён в форме.{" "}
          {error instanceof ApiProblem && error.problem.field_errors?.length
            ? "Проверьте поля формы."
            : retryable(error)
              ? "Попробуйте ещё раз."
              : "Обновите данные и проверьте доступ перед отправкой."}
        </p>
      )}
      <Button type="submit" disabled={saving || description.trim().length < 5 || (Boolean(error) && !retryable(error))}>
        {saving ? "Сохраняем…" : "Сохранить сигнал"}
      </Button>
    </form>
  );
}

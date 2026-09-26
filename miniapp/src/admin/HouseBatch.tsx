import { type ReactNode, useId, useState } from "react";
import { Button } from "../shared/ui/Button";
import { countLabel } from "../shared/ui/format";
import { Feedback, dateInput, formValue, submitted, useAction, type Schema } from "./administration";

/** D5 (аудит Р-1): сколько адресов принимает одна пачка. */
export const HOUSE_BATCH_LIMIT = 200;

const SUBMIT_OUTCOMES: Record<Schema["HouseBatchSubmitItem"]["outcome"], string> = {
  created: "Заявка создана",
  duplicate: "Повтор в списке",
  already_open: "Заявка уже на рассмотрении",
  already_managed: "Дом уже под управлением УК",
};

const APPROVE_OUTCOMES: Record<Schema["HouseBatchDecision"]["outcome"], string> = {
  approved: "Одобрено",
  already_approved: "Уже одобрено",
  conflict: "Не одобрено",
  not_found: "Заявка не найдена",
  failed: "Не одобрено",
};

/** Адреса из вставленного текста: по одному на строку, пустые строки пропускаются. */
export function parseAddresses(text: string): string[] {
  return text.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
}

/** Администратор УК вставляет список до 200 адресов — каждый становится заявкой на дом. */
export function AddressListForm({ base, onDone }: { base: string; onDone: () => void }) {
  const id = useId();
  const [key, setKey] = useState(() => crypto.randomUUID());
  const [text, setText] = useState("");
  const [result, setResult] = useState<Schema["HouseBatchSubmitted"] | null>(null);
  const action = useAction(onDone);
  const addresses = parseAddresses(text);
  const tooMany = addresses.length > HOUSE_BATCH_LIMIT;
  const blocked = addresses.length === 0 ? "Вставьте хотя бы один адрес" : tooMany ? "Не больше 200 адресов за раз" : null;
  return <section className="ds-section admin-detail" aria-labelledby={`${id}-title`}>
    <h2 id={`${id}-title`}>Список адресов</h2>
    <p className="muted">Вставьте до {HOUSE_BATCH_LIMIT} адресов, по одному на строку. Каждый адрес станет заявкой на дом; доступ к дому
      появится после решения платформы. Квота считается по чатам, не по домам.</p>
    <form className="ds-form" onSubmit={async e => {
      const data = submitted(e);
      const answer = await action.run<Schema["HouseBatchSubmitted"]>(`${base}/house-management-requests/batch`, {
        addresses, requested_valid_from: new Date(`${formValue(data, "date")}T00:00:00`).toISOString(),
        basis_text: formValue(data, "basis"),
      }, key);
      if (answer) { setResult(answer); setText(""); setKey(crypto.randomUUID()); }
    }}>
      <div className="ds-field"><label htmlFor={`${id}-list`}>Адреса домов</label>
        <textarea id={`${id}-list`} rows={8} value={text} onChange={e => setText(e.target.value)} required
          aria-describedby={`${id}-count`} />
        <p id={`${id}-count`} className="muted" aria-live="polite">
          {tooMany ? `Слишком много: ${addresses.length}. Разделите список на части до ${HOUSE_BATCH_LIMIT}.`
            : countLabel(addresses.length, ["адрес", "адреса", "адресов"])}</p></div>
      <div className="ds-field"><label htmlFor={`${id}-date`}>Дата начала управления</label>
        <input id={`${id}-date`} name="date" type="date" required defaultValue={dateInput(new Date())} /></div>
      <div className="ds-field"><label htmlFor={`${id}-basis`}>Основание</label>
        <textarea id={`${id}-basis`} name="basis" required maxLength={2000} /></div>
      <Feedback error={action.error || undefined} />
      <Button type="submit" variant="primary" loading={action.busy} loadingLabel="Создаём заявки…" disabled={!!blocked} reason={blocked}>
        Подать заявки на дома</Button>
    </form>
    {result && <div role="status" className="ds-section">
      <p><strong>Создано заявок: {result.created}.</strong> Пропущено: {result.skipped}.</p>
      {result.skipped > 0 && <ul className="admin-records">{result.items.filter(item => item.outcome !== "created").map((item, index) =>
        <li key={`${item.address}-${index}`}><span>{item.address}</span><span className="muted">{SUBMIT_OUTCOMES[item.outcome]}</span></li>)}</ul>}
    </div>}
  </section>;
}

const OPEN = ["submitted", "under_review", "needs_info"];

/** Платформа одобряет выбранные заявки на дома одним действием с одним регионом. */
export function BatchApprove({ requests, packs, refresh, regionFields }: {
  requests: Schema["HouseRequestView"][];
  packs?: Schema["RegionPackView"][];
  refresh: () => void;
  regionFields: (region: string, onRegion: (value: string) => void) => ReactNode;
}) {
  const id = useId();
  const open = requests.filter(item => OPEN.includes(item.status));
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [region, setRegion] = useState("");
  const [result, setResult] = useState<Schema["HouseBatchApproved"] | null>(null);
  const action = useAction(refresh);
  if (!open.length && !result) return null;
  const toggle = (value: string) => setSelected(current => {
    const next = new Set(current);
    if (next.has(value)) next.delete(value); else next.add(value);
    return next;
  });
  const addresses = new Map(requests.map(item => [item.id, item.requested_address]));
  const blocked = selected.size === 0 ? "Отметьте заявки" : !region ? "Выберите регион дома" : null;
  return <section className="ds-section admin-detail" aria-labelledby={`${id}-title`}>
    <h2 id={`${id}-title`}>Одобрить пачкой</h2>
    <p className="muted">Отметьте открытые заявки одной УК и региона. Дом берётся найденный по адресу или создаётся новый;
      результат — по каждому дому. Пересечение периода управления не одобряется.</p>
    <form className="ds-form" onSubmit={async e => {
      const data = submitted(e);
      const answer = await action.run<Schema["HouseBatchApproved"]>("/api/v1/platform/house-management-requests/approve-batch", {
        request_ids: [...selected], reason: formValue(data, "reason"),
        valid_from: new Date(`${formValue(data, "date")}T00:00:00`).toISOString(), confirm_backdate: data.get("backdate") === "on",
        region_code: formValue(data, "region") || null, municipality_code: formValue(data, "municipality") || null,
        territory_policy: formValue(data, "territory") || "mixed",
      });
      if (answer) { setResult(answer); setSelected(new Set()); }
    }}>
      <fieldset className="ds-field"><legend>Заявки ({selected.size} из {open.length})</legend>
        <label className="checkbox-label"><input type="checkbox" checked={open.length > 0 && selected.size === open.length}
          onChange={e => setSelected(e.target.checked ? new Set(open.slice(0, HOUSE_BATCH_LIMIT).map(item => item.id)) : new Set())} />
          Выбрать все открытые</label>
        <ul className="admin-records">{open.map(item => <li key={item.id}><label className="checkbox-label">
          <input type="checkbox" checked={selected.has(item.id)} onChange={() => toggle(item.id)} />{item.requested_address}</label>
          {item.source_application_id && <span className="muted">из заявки УК</span>}</li>)}</ul>
      </fieldset>
      {regionFields(region, setRegion)}
      <div className="ds-field"><label htmlFor={`${id}-date`}>Дата начала управления</label>
        <input id={`${id}-date`} name="date" type="date" required defaultValue={dateInput(new Date())} /></div>
      <label className="checkbox-label"><input type="checkbox" name="backdate" />Явно подтверждаю прошлую дату на указанном основании</label>
      <div className="ds-field"><label htmlFor={`${id}-reason`}>Основание решения</label>
        <textarea id={`${id}-reason`} name="reason" required maxLength={2000} /></div>
      <Feedback error={action.error || undefined} />
      <Button type="submit" variant="primary" loading={action.busy} loadingLabel="Одобряем…" disabled={!!blocked} reason={blocked}>
        Одобрить выбранные ({selected.size})</Button>
    </form>
    {result && <div role="status" className="ds-section">
      <p><strong>Одобрено: {result.approved}.</strong> Уже одобрено: {result.already_approved}. Не одобрено: {result.failed}.</p>
      {result.failed > 0 && <ul className="admin-records">{result.items.filter(item => !["approved", "already_approved"].includes(item.outcome))
        .map(item => <li key={item.request_id}><span>{addresses.get(item.request_id) ?? item.request_id}</span>
          <span className="muted">{APPROVE_OUTCOMES[item.outcome]}{item.message ? `: ${item.message}` : ""}</span></li>)}</ul>}
    </div>}
    {packs === undefined && <p className="muted">Загружаем регионы…</p>}
  </section>;
}

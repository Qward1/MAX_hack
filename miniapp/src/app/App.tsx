import { Button } from '@maxhub/max-ui';
import { FormEvent, useCallback, useEffect, useState } from 'react';

import type {
  Capabilities,
  DomSignalApi,
  IncidentDetail,
  IncidentList,
  Me,
  ReportCreate,
} from '../shared/api/client';
import { apiClient } from '../shared/api/client';

type ScreenState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | {
      kind: 'board';
      capabilities: Capabilities;
      me: Me;
      incidents: IncidentList;
    }
  | { kind: 'detail'; incident: IncidentDetail; previous: BoardState };

type BoardState = Extract<ScreenState, { kind: 'board' }>;

const categoryLabels: Record<ReportCreate['category'], string> = {
  elevator: 'Лифт',
  water: 'Вода',
  lighting: 'Освещение',
  waste: 'Отходы',
  other: 'Другое',
};

export function App({ client = apiClient }: { client?: DomSignalApi }) {
  const [state, setState] = useState<ScreenState>({ kind: 'loading' });

  const load = useCallback(async () => {
    setState({ kind: 'loading' });
    try {
      const capabilities = await client.capabilities();
      await client.authenticate(capabilities);
      const me = await client.me();
      const house = me.houses[0];
      if (!house) {
        setState({ kind: 'error', message: 'У пользователя пока нет доступного дома.' });
        return;
      }
      const incidents = await client.incidents(house.id);
      setState({ kind: 'board', capabilities, me, incidents });
    } catch (error) {
      setState({
        kind: 'error',
        message: error instanceof Error ? error.message : 'Не удалось загрузить дом.',
      });
    }
  }, [client]);

  useEffect(() => {
    void load();
  }, [load]);

  if (state.kind === 'loading') return <Loading />;
  if (state.kind === 'error') return <ErrorState message={state.message} onRetry={load} />;
  if (state.kind === 'detail') {
    return <IncidentCard incident={state.incident} onBack={() => setState(state.previous)} />;
  }
  return (
    <HouseBoard
      state={state}
      client={client}
      onOpen={async (id) => {
        try {
          const incident = await client.incident(id);
          setState({ kind: 'detail', incident, previous: state });
        } catch (error) {
          setState({
            kind: 'error',
            message: error instanceof Error ? error.message : 'Не удалось открыть карточку.',
          });
        }
      }}
      onRefresh={load}
    />
  );
}

function Loading() {
  return (
    <main className="app-shell" aria-busy="true">
      <p className="eyebrow">ДомСигнал</p>
      <div className="skeleton skeleton-title" />
      <div className="skeleton skeleton-card" />
      <span className="sr-only">Загрузка доски дома</span>
    </main>
  );
}

function ErrorState({ message, onRetry }: { message: string; onRetry: () => Promise<void> }) {
  return (
    <main className="app-shell center-state">
      <div className="state-mark" aria-hidden="true">!</div>
      <h1>Доска временно недоступна</h1>
      <p>{message}</p>
      <Button onClick={() => void onRetry()}>Попробовать снова</Button>
    </main>
  );
}

function HouseBoard({
  state,
  client,
  onOpen,
  onRefresh,
}: {
  state: BoardState;
  client: DomSignalApi;
  onOpen: (id: string) => Promise<void>;
  onRefresh: () => Promise<void>;
}) {
  const [isFormOpen, setFormOpen] = useState(false);
  const house = state.me.houses[0];
  return (
    <main className="app-shell">
      <header className="hero">
        <div>
          <p className="eyebrow">Мой дом</p>
          <h1>{house.name}</h1>
          <p className="muted">{house.address}</p>
        </div>
        <span className="demo-badge">Демо</span>
      </header>

      <section className="section-heading">
        <div>
          <h2>Что происходит</h2>
          <p className="muted">Сохранённые сигналы жителей этого дома</p>
        </div>
        {state.capabilities.features.report_create && (
          <Button onClick={() => setFormOpen((value) => !value)}>
            {isFormOpen ? 'Закрыть' : 'Сообщить'}
          </Button>
        )}
      </section>

      {isFormOpen && (
        <ReportForm
          houseId={house.id}
          client={client}
          onCreated={async () => {
            setFormOpen(false);
            await onRefresh();
          }}
        />
      )}

      {state.incidents.items.length === 0 ? (
        <section className="empty-state">
          <div className="state-mark calm" aria-hidden="true">✓</div>
          <h2>На доске пока пусто</h2>
          <p>Новый сигнал появится здесь после сохранения.</p>
        </section>
      ) : (
        <ul className="incident-grid" aria-label="Инциденты дома">
          {state.incidents.items.map((incident) => (
            <li key={incident.id}>
              <button className="incident-tile" onClick={() => void onOpen(incident.id)}>
                <span className={`category-dot category-${incident.category}`} />
                <span className="tile-copy">
                  <strong>{incident.title}</strong>
                  <span>{incident.description}</span>
                </span>
                <span className="status">Открыто</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}

function ReportForm({
  houseId,
  client,
  onCreated,
}: {
  houseId: string;
  client: DomSignalApi;
  onCreated: () => Promise<void>;
}) {
  const [category, setCategory] = useState<ReportCreate['category']>('elevator');
  const [description, setDescription] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await client.createReport(
        { house_id: houseId, category, description, classification_mode: 'manual' },
        crypto.randomUUID(),
      );
      await onCreated();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Не удалось сохранить сигнал.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="report-form" onSubmit={(event) => void submit(event)}>
      <div>
        <p className="eyebrow">Новый сигнал</p>
        <h2>Что случилось?</h2>
      </div>
      <label>
        Категория
        <select value={category} onChange={(event) => setCategory(event.target.value as ReportCreate['category'])}>
          {Object.entries(categoryLabels).map(([value, label]) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </select>
      </label>
      <label>
        Описание
        <textarea
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          minLength={5}
          maxLength={2000}
          placeholder="Например: лифт не реагирует на кнопку на первом этаже"
          required
        />
      </label>
      <p className="form-note">Категория выбрана вручную. Маршрут и обращение ещё не формируются.</p>
      {error && <p className="inline-error" role="alert">{error}</p>}
      <Button type="submit" disabled={saving || description.trim().length < 5}>
        {saving ? 'Сохраняем…' : 'Сохранить сигнал'}
      </Button>
    </form>
  );
}

function IncidentCard({ incident, onBack }: { incident: IncidentDetail; onBack: () => void }) {
  return (
    <main className="app-shell">
      <button className="back-link" onClick={onBack}>← К доске дома</button>
      <article className="detail-card">
        <p className="eyebrow">Открытая проблема</p>
        <h1>{incident.title}</h1>
        <p className="lead">{incident.description}</p>
        <dl className="facts">
          <div><dt>Сообщили</dt><dd>{incident.report_count}</dd></div>
          <div><dt>Категория</dt><dd>{categoryLabels[incident.category]}</dd></div>
          <div><dt>Срок</dt><dd>Не определён</dd></div>
        </dl>
        <aside className="source-note">
          <strong>{incident.rule.source_title}</strong>
          <span>{incident.rule.note}</span>
        </aside>
      </article>
    </main>
  );
}

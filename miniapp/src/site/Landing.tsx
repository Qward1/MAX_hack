import { useEffect, useState, type ReactNode } from "react";

/**
 * Публичная страница продукта (D2, новый дизайн F1 §2.6). Только то, что продукт
 * действительно делает: без цифр, клиентов и отзывов. Переписка в примере
 * подписана «Пример». Значки — свои SVG, без картинок и библиотек.
 */
export function Landing() {
  const [botUrl, setBotUrl] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    fetch("/api/v1/capabilities", { cache: "no-store" })
      .then(response => response.ok ? response.json() : null)
      .then((caps: { bot_url?: string | null } | null) => {
        const url = caps?.bot_url;
        if (active && url && /^https:\/\/max\.ru\/[A-Za-z0-9_]+$/.test(url)) setBotUrl(url);
      })
      .catch(() => undefined);
    return () => { active = false; };
  }, []);
  return <div className="site">
    <a className="skip-link" href="#main">Перейти к содержанию</a>
    <header className="site-header">
      <div className="site-header-inner">
        <a className="site-brand" href="/" aria-label="ДомСигнал — на главную"><Logo /><span className="site-brand-text">ДомСигнал</span></a>
        <nav aria-label="Разделы страницы" className="site-nav">
          <a href="#how">Как это работает</a>
          <a href="#residents">Жителям</a>
          <a href="#companies">УК</a>
          <a href="#safety">Безопасность</a>
        </nav>
        <div className="site-header-actions">
          <a className="site-button site-button-quiet" href="/login">Войти</a>
          <a className="site-button" href="/company/apply">Подключить УК</a>
        </div>
      </div>
    </header>

    <main id="main">
      <section className="site-hero" aria-labelledby="hero-title">
        <div className="site-hero-text">
          <p className="site-eyebrow">Бот и мини-приложение для домовых чатов MAX</p>
          <h1 id="hero-title">Проблемы дома — из домового чата в работу</h1>
          <p className="site-lead">ДомСигнал замечает в переписке соседей, что сломалось, собирает сообщения в одну
            проблему и доводит её до результата: заявка управляющей компании или правильный официальный сервис.
            Закрывает проблему житель, а не отчёт исполнителя.</p>
          <div className="site-actions">
            <a className="site-button site-button-large" href="/company/apply">Подключить УК</a>
            {botUrl && <a className="site-button site-button-quiet site-button-large" href={botUrl} rel="noopener">Открыть бота в MAX</a>}
          </div>
          <p className="site-note">Жителю ничего не нужно устанавливать: бот и мини-приложение работают внутри MAX.</p>
        </div>
        <Chain />
      </section>

      <section className="site-section" id="how" aria-labelledby="how-title">
        <SectionHead title="Как это работает" id="how-title">Четыре шага от сообщения в чате до подтверждённого результата.</SectionHead>
        <ol className="site-steps">
          <Step icon={<IconChat />} n={1} title="Соседи пишут как обычно">
            «Лифт опять стоит» — без форм и команд. Можно и явно: /report в чате, сообщение боту или кнопка в мини-приложении.
          </Step>
          <Step icon={<IconStack />} n={2} title="ДомСигнал собирает проблему">
            Похожие сообщения становятся одной проблемой на доске дома. Признаки опасности распознаются сразу.
          </Step>
          <Step icon={<IconRoute />} n={3} title="Проблема попадает к тому, кто отвечает">
            Общее имущество — в очередь заявок УК. Городская территория — официальный сервис с источником и черновик обращения.
          </Step>
          <Step icon={<IconCheck />} n={4} title="Житель подтверждает результат">
            Исполнитель сообщает о выполнении, жители подтверждают или возвращают заявку в работу.
          </Step>
        </ol>
      </section>

      <section className="site-section" aria-labelledby="value-title">
        <SectionHead title="Польза для трёх сторон" id="value-title">Одна проблема — один путь, понятный всем, кто в нём участвует.</SectionHead>
        <div className="site-value">
          <article className="site-card site-value-card" id="residents" aria-labelledby="residents-title">
            <span className="site-card-icon"><IconPeople /></span>
            <h3 id="residents-title">Жителям</h3>
            <ul className="site-list">
              <li>Не нужно искать, куда писать: достаточно сказать в чате.</li>
              <li>Видно, о чём уже сообщили соседи и кто занимается.</li>
              <li>Последнее слово за вами: исправлено или нет.</li>
            </ul>
          </article>
          <article className="site-card site-value-card" id="companies" aria-labelledby="companies-title">
            <span className="site-card-icon"><IconQueue /></span>
            <h3 id="companies-title">Управляющей компании</h3>
            <ul className="site-list">
              <li>Очередь заявок по домам вместо ленты сообщений.</li>
              <li>Повторы собраны в одну проблему, опасное — оповещением сразу.</li>
              <li>Подключение без разработчиков: заявка, дома, чаты.</li>
            </ul>
          </article>
          <article className="site-card site-value-card" aria-labelledby="city-title">
            <span className="site-card-icon"><IconCity /></span>
            <h3 id="city-title">Городу</h3>
            <ul className="site-list">
              <li>Проблемы вне зоны УК доходят до официальных сервисов региона.</li>
              <li>Житель отправляет обращение сам — по готовому черновику, с адресом и сутью.</li>
              <li>Результат подтверждают те, кто живёт в доме.</li>
            </ul>
          </article>
        </div>
      </section>

      <section className="site-section" aria-labelledby="features-title">
        <SectionHead title="Возможности" id="features-title">Всё, что делает ДомСигнал, — по одной фразе.</SectionHead>
        <ul className="site-features">
          <Feature icon={<IconEye />} title="Разбор домового чата">Бот замечает проблемы в обычной переписке соседей.</Feature>
          <Feature icon={<IconDoors />} title="Три входа">Домовой чат, личные сообщения боту и мини-приложение.</Feature>
          <Feature icon={<IconAlert />} title="Опасность за секунды">Газ, дым и огонь распознают правила при приёме сообщения.</Feature>
          <Feature icon={<IconSource />} title="Кто отвечает — с источником">Ответственный и сервис — из проверенного справочника с датой проверки.</Feature>
          <Feature icon={<IconDraft />} title="Черновик обращения">Готовый текст для официального сервиса; отправляет житель сам.</Feature>
          <Feature icon={<IconCheck />} title="Закрывает житель">Отчёт исполнителя не закрывает проблему без подтверждения жителей.</Feature>
          <Feature icon={<IconMegaphone />} title="Заявка в чате дома">Статус заявки в домовом чате и кнопка «Меня тоже касается».</Feature>
          <Feature icon={<IconHome />} title="«Мой дом» и «Если авария»">Контакты УК, сервисы региона и 112 — в одно касание.</Feature>
          <Feature icon={<IconPoll />} title="Объявления и опросы">УК и совет дома пишут жителям, соседи голосуют в мини-приложении.</Feature>
          <Feature icon={<IconKey />} title="Самоподключение УК">Заявка, проверка платформой, аккаунт администратора — без разработчиков.</Feature>
          <Feature icon={<IconList />} title="Дома пачкой">Список адресов добавляется одной вставкой.</Feature>
          <Feature icon={<IconChart />} title="Обзор по домам">Сигналы, заявки, время до принятия и итоги проверки жителями.</Feature>
        </ul>
      </section>

      <section className="site-section site-safety" id="safety" aria-labelledby="safety-title">
        <SectionHead title="Безопасность и честность" id="safety-title">Правила, которые не отключаются ради удобства.</SectionHead>
        <ul className="site-principles">
          <li><span className="site-card-icon"><IconAlert /></span><div><h3>Опасность — правилами</h3>
            <p>Газ, дым и огонь распознаются без ожидания модели. Сотрудник УК получает оповещение, житель — «Если авария» и 112.</p></div></li>
          <li><span className="site-card-icon"><IconSource /></span><div><h3>Ответственный — только с источником</h3>
            <p>Каждое «кто отвечает» показывает документ и дату проверки. Нет источника — так и написано.</p></div></li>
          <li><span className="site-card-icon"><IconCheck /></span><div><h3>Заявку закрывает житель</h3>
            <p>Работа исполнителя — это ещё не результат. Жители подтверждают его или возвращают заявку.</p></div></li>
          <li><span className="site-card-icon"><IconLock /></span><div><h3>Что мы храним</h3>
            <p>Сообщения чата — не дольше 72 часов. Перед моделью текст маскируется, имена и идентификаторы не передаются.
              Подробно — в <a className="ds-text-link" href="/privacy">политике данных</a>.</p></div></li>
        </ul>
      </section>

      <section className="site-section site-where" aria-labelledby="where-title">
        <SectionHead title="Где работает" id="where-title">Там, где жители уже общаются, — в MAX.</SectionHead>
        <div className="site-where-grid">
          <div className="site-card"><span className="site-card-icon"><IconPhone /></span><h3>MAX на телефоне и в веб-версии</h3>
            <p>Бот в домовом чате и мини-приложение с доской проблем, «Моими обращениями» и «Моим домом».</p></div>
          <div className="site-card"><span className="site-card-icon"><IconMap /></span><h3>Справочники четырёх регионов</h3>
            <p>Москва, Республика Татарстан, Приморский край и Псковская область, плюс федеральные сервисы для любого адреса.</p></div>
        </div>
      </section>

      <section className="site-section site-faq" aria-labelledby="faq-title">
        <SectionHead title="Вопросы и ответы" id="faq-title" />
        <div className="site-faq-list">
          <Faq q="Нужно ли жителям что-то устанавливать?">Нет. Бот и мини-приложение работают внутри MAX — на телефоне и в веб-версии.</Faq>
          <Faq q="Бот читает всю переписку?">Только в чатах, которые подключила управляющая компания, и только после включения чтения — бот сообщает об этом в чате. Сообщения чата хранятся не дольше 72 часов.</Faq>
          <Faq q="А если проблема не к управляющей компании?">ДомСигнал покажет официальный сервис региона с источником и подготовит черновик обращения. Отправляет его житель сам.</Faq>
          <Faq q="Кто закрывает заявку?">Житель. Исполнитель сообщает о выполнении, жители подтверждают результат или возвращают заявку в работу.</Faq>
          <Faq q="Используется ли модель ИИ?">Да, для разбора переписки — открытая модель Qwen3-30B-A3B через Cloud.ru Foundation Models; по документации Cloud.ru это внешняя модель. Перед моделью текст маскируется. Опасность распознают правила без модели.</Faq>
          <Faq q="Как подключить управляющую компанию?">Подайте заявку. После проверки платформой вы создадите аккаунт администратора, добавите дома и подключите их чаты.</Faq>
        </div>
      </section>

      <section className="site-cta" aria-labelledby="cta-title">
        <h2 id="cta-title">Подключите свою управляющую компанию</h2>
        <p>Заявка занимает несколько минут. После проверки вы сами создадите аккаунт администратора, добавите дома и подключите их чаты.</p>
        <div className="site-actions">
          <a className="site-button site-button-large site-button-invert" href="/company/apply">Подать заявку</a>
          <a className="site-button site-button-large site-button-ghost" href="/login">Уже подключены — войти</a>
        </div>
      </section>
    </main>

    <footer className="site-footer">
      <div className="site-footer-inner">
        <p className="site-brand site-footer-brand"><Logo />ДомСигнал</p>
        <ul>
          <li><a href="/company/apply">Подключить УК</a></li>
          <li><a href="/login">Вход для сотрудников</a></li>
          {botUrl && <li><a href={botUrl} rel="noopener">Бот в MAX</a></li>}
          <li><a href="/privacy">Политика данных</a></li>
        </ul>
      </div>
    </footer>
  </div>;
}

function SectionHead({ title, id, children }: { title: string; id: string; children?: ReactNode }) {
  return <div className="site-section-head"><h2 id={id}>{title}</h2>{children && <p>{children}</p>}</div>;
}
function Step({ icon, n, title, children }: { icon: ReactNode; n: number; title: string; children: ReactNode }) {
  return <li className="site-step"><span className="site-card-icon">{icon}</span>
    <p className="site-step-n">Шаг {n}</p><h3>{title}</h3><p>{children}</p></li>;
}
function Feature({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return <li className="site-feature"><span className="site-card-icon">{icon}</span><h3>{title}</h3><p>{children}</p></li>;
}
function Faq({ q, children }: { q: string; children: ReactNode }) {
  return <details className="site-faq-item"><summary>{q}</summary><p>{children}</p></details>;
}

/** Пример: реплика в чате → проблема → заявка → «Исправлено». Появляется по шагам. */
function Chain() {
  return <figure className="site-chain" aria-labelledby="chain-caption">
    <span className="site-example-badge">Пример</span>
    <div className="chain-step chain-chat">
      <p className="chain-label"><IconChat />Домовой чат</p>
      <p className="chain-bubble"><span>Сосед, кв. 12</span>Лифт во втором подъезде опять стоит</p>
      <p className="chain-bubble"><span>Соседка, кв. 40</span>Да, с утра не едет</p>
    </div>
    <div className="chain-step chain-problem">
      <p className="chain-label"><IconStack />Проблема на доске дома</p>
      <p className="chain-title">Лифт не работает</p>
      <p className="chain-meta">Подъезд 2 · сообщили 2 соседа</p>
    </div>
    <div className="chain-step chain-ticket">
      <p className="chain-label"><IconQueue />Заявка в управляющую компанию</p>
      <p className="chain-title">Исполнитель назначен</p>
      <p className="chain-meta">Статус заявки — в чате дома</p>
    </div>
    <div className="chain-step chain-done">
      <p className="chain-label"><IconCheck />Исправлено</p>
      <p className="chain-title">Жители подтвердили: лифт работает</p>
    </div>
    <figcaption id="chain-caption">Пример: как сообщение в чате становится заявкой и закрывается жителями</figcaption>
  </figure>;
}

function Svg({ children, size = 24 }: { children: ReactNode; size?: number }) {
  return <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="1.8"
    strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">{children}</svg>;
}
function Logo() {
  return <svg className="site-logo" viewBox="0 0 32 32" width="28" height="28" aria-hidden="true" focusable="false">
    <rect width="32" height="32" rx="8" fill="var(--ds-action)" />
    <path d="M8 16.5 16 9.5l8 7V24a1 1 0 0 1-1 1h-4.5v-5h-5v5H9a1 1 0 0 1-1-1z" fill="var(--ds-on-action)" />
    <circle cx="23.5" cy="9" r="3.5" fill="#f5b83d" stroke="var(--ds-action)" strokeWidth="1.5" />
  </svg>;
}
const IconChat = () => <Svg><path d="M5 5h14a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1h-8l-4 3v-3H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z" /><path d="M8 9.5h8M8 12.5h5" /></Svg>;
const IconStack = () => <Svg><path d="m12 4 8 4-8 4-8-4z" /><path d="m4 12 8 4 8-4" /><path d="m4 16 8 4 8-4" /></Svg>;
const IconRoute = () => <Svg><circle cx="6" cy="18" r="2" /><circle cx="18" cy="6" r="2" /><path d="M8 18h6a3 3 0 0 0 0-6h-4a3 3 0 0 1 0-6h6" /></Svg>;
const IconCheck = () => <Svg><circle cx="12" cy="12" r="8" /><path d="m8.5 12.2 2.4 2.4 4.8-5" /></Svg>;
const IconPeople = () => <Svg><circle cx="9" cy="8.5" r="3" /><path d="M3.5 19a5.5 5.5 0 0 1 11 0" /><circle cx="17" cy="9.5" r="2.4" /><path d="M16 14.2a4.5 4.5 0 0 1 5 4.8" /></Svg>;
const IconQueue = () => <Svg><rect x="4" y="4" width="16" height="16" rx="2" /><path d="M8 9h8M8 12.5h8M8 16h5" /></Svg>;
const IconCity = () => <Svg><path d="M3 20h18" /><path d="M5 20V9l5-3v14" /><path d="M10 20V4l9 4v12" /><path d="M13 10h3M13 13.5h3M13 17h3" /></Svg>;
const IconEye = () => <Svg><path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z" /><circle cx="12" cy="12" r="3" /></Svg>;
const IconDoors = () => <Svg><rect x="3" y="5" width="5" height="14" rx="1" /><rect x="9.5" y="5" width="5" height="14" rx="1" /><rect x="16" y="5" width="5" height="14" rx="1" /></Svg>;
const IconAlert = () => <Svg><path d="M12 4 2.8 19.5h18.4z" /><path d="M12 10v4.5M12 17.2v.1" /></Svg>;
const IconSource = () => <Svg><path d="M6 3.5h8l4 4V20a.5.5 0 0 1-.5.5h-11A.5.5 0 0 1 6 20z" /><path d="M14 3.5v4h4" /><path d="m9 14 2 2 4-4" /></Svg>;
const IconDraft = () => <Svg><path d="M4 20h4l10.5-10.5a2.1 2.1 0 0 0-3-3L5 17z" /><path d="m13.5 7.5 3 3" /></Svg>;
const IconMegaphone = () => <Svg><path d="M4 10v4a1 1 0 0 0 1 1h2l6 4V5L7 9H5a1 1 0 0 0-1 1z" /><path d="M17 9a4 4 0 0 1 0 6" /></Svg>;
const IconHome = () => <Svg><path d="M4 11 12 4l8 7" /><path d="M6 9.5V20h12V9.5" /><path d="M10 20v-5h4v5" /></Svg>;
const IconPoll = () => <Svg><path d="M5 20V11M12 20V5M19 20v-7" /><path d="M3 20h18" /></Svg>;
const IconKey = () => <Svg><circle cx="8" cy="15" r="4" /><path d="m11 12 8-8M16 7l2 2M14 9l2 2" /></Svg>;
const IconList = () => <Svg><path d="M9 6h11M9 12h11M9 18h11" /><circle cx="5" cy="6" r="1" /><circle cx="5" cy="12" r="1" /><circle cx="5" cy="18" r="1" /></Svg>;
const IconChart = () => <Svg><path d="M4 4v16h16" /><path d="m7 15 4-4 3 3 5-6" /></Svg>;
const IconLock = () => <Svg><rect x="5" y="10.5" width="14" height="9.5" rx="1.5" /><path d="M8 10.5V8a4 4 0 0 1 8 0v2.5" /></Svg>;
const IconPhone = () => <Svg><rect x="7" y="3" width="10" height="18" rx="2" /><path d="M11 17.5h2" /></Svg>;
const IconMap = () => <Svg><path d="m3 6 6-2 6 2 6-2v14l-6 2-6-2-6 2z" /><path d="M9 4v14M15 6v14" /></Svg>;

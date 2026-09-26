import { useEffect, useState } from "react";

/**
 * Публичная страница продукта (D2). Только то, что продукт действительно делает:
 * без цифр, клиентов и отзывов. Переписка в примере помечена как пример.
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
      <a className="site-brand" href="/" aria-label="ДомСигнал — на главную">ДомСигнал</a>
      <nav aria-label="Основная навигация" className="site-nav">
        <a href="#how">Как это работает</a>
        <a href="#for-companies">Для УК</a>
        <a className="site-button site-button-quiet" href="/login">Вход</a>
      </nav>
    </header>

    <main id="main">
      <section className="site-hero" aria-labelledby="hero-title">
        <div className="site-hero-text">
          <h1 id="hero-title">Проблемы дома — из домового чата в работу</h1>
          <p className="site-lead">ДомСигнал — бот для домовых чатов в MAX. Он замечает, когда соседи пишут о поломке,
            собирает их сообщения в один сигнал и помогает довести дело до результата: заявки управляющей компании
            или обращения в правильный официальный канал.</p>
          <div className="site-actions">
            <a className="site-button" href="/company/apply">Подключить УК</a>
            {botUrl && <a className="site-button site-button-quiet" href={botUrl} rel="noopener">Открыть бота в MAX</a>}
          </div>
        </div>
        <ChatExample />
      </section>

      <section className="site-section" id="how" aria-labelledby="how-title">
        <h2 id="how-title">Как это работает</h2>
        <ol className="site-steps">
          <li><h3>Соседи пишут в чат как обычно</h3>
            <p>«Лифт опять стоит», «во дворе не горит фонарь» — без форм и команд. Можно и явно: команда /report в чате или сообщение боту в личку.</p></li>
          <li><h3>Бот собирает сообщения в сигнал</h3>
            <p>Похожие реплики становятся одним сигналом: что сломалось, где и сколько соседей подтвердили. Продолжение разговора добавляется к тому же сигналу, а не создаёт новый.</p></li>
          <li><h3>Сигнал попадает к тому, кто отвечает</h3>
            <p>Общее имущество дома — в очередь управляющей компании. Городская территория — житель получает проверенный официальный канал и черновик обращения, который отправляет сам.</p></li>
          <li><h3>Результат проверяют жители</h3>
            <p>Отчёт исполнителя не закрывает проблему. Жители подтверждают, что всё работает, или возвращают заявку в работу.</p></li>
        </ol>
      </section>

      <section className="site-section site-columns" aria-label="Возможности">
        <div>
          <h2>Жителям</h2>
          <ul className="site-list">
            <li>Сообщить о проблеме в домовом чате, в личке бота или в мини-приложении.</li>
            <li>Видеть доску проблем своего дома и присоединиться к уже известной, а не писать заново.</li>
            <li>Получить карточку следующего шага: кто отвечает и где подать обращение — только с источником.</li>
            <li>Подтвердить устранение или вернуть заявку в работу.</li>
          </ul>
        </div>
        <div id="for-companies">
          <h2>Управляющей компании</h2>
          <ul className="site-list">
            <li>Очередь сигналов и заявок по каждому дому вместо ленты сообщений.</li>
            <li>Сотрудники с назначениями на дома, вход по паролю и приложению-аутентификатору.</li>
            <li>Подключение существующих чатов с проверкой прав администратора в MAX.</li>
            <li>Обзор по домам: сигналы, время до принятия заявки, итоги проверки жителями, выгрузка CSV.</li>
          </ul>
        </div>
      </section>

      <section className="site-section site-boundary" aria-labelledby="boundary-title">
        <h2 id="boundary-title">Чего ДомСигнал не делает</h2>
        <ul className="site-list">
          <li>Не подаёт обращения за жителя и не называет их зарегистрированными — во внешний канал житель пишет сам.</li>
          <li>Не выдумывает ответственных: организацию и канал показывает только из проверенного источника, иначе честно говорит, что ответственный не определён.</li>
          <li>Не ждёт модель при опасности: признаки газа или дыма распознают правила сразу, и управляющая компания получает оповещение.</li>
        </ul>
      </section>

      <section className="site-cta" aria-labelledby="cta-title">
        <h2 id="cta-title">Подключите свою управляющую компанию</h2>
        <p>Заявка занимает несколько минут. После проверки вы сами создадите аккаунт администратора, добавите дома и подключите их чаты.</p>
        <div className="site-actions">
          <a className="site-button" href="/company/apply">Подать заявку</a>
          <a className="site-button site-button-quiet" href="/login">Уже подключены — войти</a>
        </div>
      </section>
    </main>

    <footer className="site-footer">
      <p>ДомСигнал</p>
      <ul>
        <li><a href="/company/apply">Подключить УК</a></li>
        <li><a href="/login">Вход для сотрудников</a></li>
        {botUrl && <li><a href={botUrl} rel="noopener">Бот в MAX</a></li>}
        <li><a href="/privacy">Политика данных</a></li>
      </ul>
    </footer>
  </div>;
}

/** Пример: переписка → сигнал → заявка → подтверждение жителей. */
function ChatExample() {
  return <figure className="site-example" aria-labelledby="example-caption">
    <div className="example-chat" aria-label="Пример сообщений в домовом чате">
      <p className="example-bubble"><span className="example-author">Сосед из кв. 12</span>Лифт во втором подъезде опять стоит</p>
      <p className="example-bubble"><span className="example-author">Соседка из кв. 40</span>Да, с утра не едет</p>
      <p className="example-bubble"><span className="example-author">Сосед из кв. 57</span>Подтверждаю, пешком поднимаюсь</p>
    </div>
    <div className="example-signal">
      <p className="example-kind">Сигнал</p>
      <p className="example-title">Лифт не работает</p>
      <p className="example-meta">Подъезд 2, подтвердили трое соседей</p>
      <ol className="example-track" aria-label="Путь сигнала">
        <li className="is-done">Заявка управляющей компании</li>
        <li className="is-done">Исполнитель сообщил о ремонте</li>
        <li className="is-current">Жители проверяют результат</li>
      </ol>
    </div>
    <figcaption id="example-caption">Пример: как переписка становится сигналом и заявкой</figcaption>
  </figure>;
}

"""Презентация ДомСигнала: HTML-слайды 1280×720 → PDF (печать в Chromium).

    uv run python docs/presentation/build_deck.py                      # публичная версия
    uv run python docs/presentation/build_deck.py --private "Claude outputs/PRIVATE" --commit <sha>

Публичная версия — `docs/presentation/DomSignal_presentation.pdf`, без секретов:
первый слайд называет адреса и логины, пароли и TOTP — «в закрытой версии».
Закрытая версия для кабинета сдачи берёт учётные записи жюри из папки вне git и
пишет PDF туда же; в репозиторий она не попадает. Печать — `print_pdf.mjs`
(Playwright из `miniapp/node_modules`).
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import os
import subprocess
from pathlib import Path

import qrcode
import qrcode.image.svg

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SITE = "https://domsignal.176-108-244-168.sslip.io"
BOT = "https://max.ru/t480_hakaton_max_bot"
REPO = "https://github.com/Qward1/MAX_hack"
TAG = "online-submission-final"

# Числа проверок финальной версии — из прогонов 28.09.2026 (docs/TESTING.md).
FACTS = {
    "backend": "1 064",
    "integration": "536",
    "frontend": "343",
    "browser": "78",
    "acceptance": "145 PASS · 0 FAIL · 14 — живой MAX",
    "data_api": "24 из 24",
    "ml_tests": "7",
}


def esc(text: str) -> str:
    return html.escape(text, quote=False)


def img(name: str, cls: str = "") -> str:
    data = base64.b64encode((HERE / "screens" / name).read_bytes()).decode()
    return f'<img class="{cls}" src="data:image/png;base64,{data}" alt="">'


def img_file(path: Path, cls: str = "") -> str:
    data = base64.b64encode(path.read_bytes()).decode()
    return f'<img class="{cls}" src="data:image/png;base64,{data}" alt="">'


def qr(url: str, size: int = 118) -> str:
    code = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, border=1)
    svg = code.to_string().decode()
    return f'<div class="qr" style="width:{size}px;height:{size}px">{svg}</div>'


def bullets(items: list[str]) -> str:
    return "<ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>"


def slide(title: str, body: str, *, kicker: str = "", cls: str = "", note: str = "") -> str:
    k = f'<div class="kicker">{kicker}</div>' if kicker else ""
    n = f'<div class="note">{note}</div>' if note else ""
    return f'<section class="slide {cls}">{k}<h1>{title}</h1>{body}{n}</section>'


def two(left: str, right: str, ratio: str = "1.15fr 1fr") -> str:
    return f'<div class="two" style="grid-template-columns:{ratio}"><div>{left}</div><div class="right">{right}</div></div>'


def phones(*names: str) -> str:
    return '<div class="phones">' + "".join(img(n, "phone") for n in names) + "</div>"


def cards(items: list[tuple[str, str]], cols: int = 3) -> str:
    inner = "".join(f'<div class="card"><div class="card-t">{t}</div><div>{b}</div></div>' for t, b in items)
    return f'<div class="cards" style="grid-template-columns:repeat({cols},1fr)">{inner}</div>'


def numbers(items: list[tuple[str, str]]) -> str:
    inner = "".join(f'<div class="num"><b>{v}</b><span>{t}</span></div>' for v, t in items)
    return f'<div class="numbers">{inner}</div>'


def table(head: list[str], rows: list[list[str]], cls: str = "") -> str:
    h = "".join(f"<th>{c}</th>" for c in head)
    r = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
    return f'<table class="{cls}"><thead><tr>{h}</tr></thead><tbody>{r}</tbody></table>'


# ------------------------------------------------------------------ служебный слайд
def service_slide(private: dict | None, commit: str | None) -> list[str]:
    version = (
        f"тег <b>{TAG}</b> · commit <code>{commit}</code> = <code>/version</code>"
        if commit
        else f"тег <b>{TAG}</b> · commit = <code>{SITE}/version</code>"
    )
    left = f"""
    <table class="kv">
      <tr><th>MAX-бот</th><td><a href="{BOT}">max.ru/t480_hakaton_max_bot</a> — «Начать»</td></tr>
      <tr><th>Mini App</th><td>из бота: «Открыть ДомСигнал» или «Открыть» под постом заявки в чате</td></tr>
      <tr><th>Web</th><td><a href="{SITE}/login">{SITE[8:]}/login</a> — кабинеты УК и платформы (пароль + TOTP)</td></tr>
      <tr><th>API</th><td><code>{SITE[8:]}/api/v1</code> · OpenAPI 3.1: <code>/openapi.json</code> · <code>DATA-API.yaml</code> — 24 проверки</td></tr>
      <tr><th>Код</th><td><a href="{REPO}">github.com/Qward1/MAX_hack</a> · {version}</td></tr>
      <tr><th>Данные</th><td>тестовые: демо-УК «Пилотная, 7», дом «Казань, ул. Пилотная, 7», демо-чат MAX</td></tr>
    </table>"""
    if private:
        rows = "".join(
            f"<tr><td>{esc(a['role_ru'])}</td><td><code>{esc(a['login'])}</code></td>"
            f"<td><code>{esc(a['password'])}</code></td><td><code class='totp'>{esc(a['totp_secret'])}</code></td></tr>"
            for a in private["accounts"] if not a["login"].endswith(".reserve")
        )
        access = f"""
        <table class="creds"><thead><tr><th>Роль</th><th>Логин</th><th>Пароль</th><th>Секрет TOTP (любое приложение-аутентификатор)</th></tr></thead>
        <tbody>{rows}</tbody></table>
        <p class="small">Житель — свой аккаунт MAX; демо-чат «Дом · Казань, Пилотная, 7»: <a href="{private['invite']}">{esc(private['invite'])}</a>.
        Резервные логины, QR-коды TOTP и коды восстановления — следующий слайд.</p>"""
    else:
        access = """<p class="small"><b>Учётные записи:</b> <code>jury.operator</code>, <code>jury.admin</code>,
        <code>jury.platform</code> (+ <code>.reserve</code>). Пароли, секреты TOTP и ссылка в демо-чат —
        в закрытой версии этого слайда, переданной организаторам; в репозитории секретов нет.</p>"""
    steps = bullets([
        "Бот → «Начать» → вступить в демо-чат по ссылке или «Выбрать дом» → «Казань, ул. Пилотная, 7»",
        "В чате: <code>/report во втором подъезде не работает лифт</code> → пост «Заявка T-N»",
        "<code>jury.operator</code> → «Заявки» → «Принять заявку» → «Начать работу» → «Сообщить о выполнении»",
        "В личке бота «Исправлено» → «Закрыта: жители подтвердили»",
        "<code>jury.platform</code> → «Обзор»; гид — <code>JURY_GUIDE.md</code> в корне репозитория",
    ])
    body = f"""<div class="svc">
      <div class="svc-main">{left}{access}</div>
      <div class="svc-side"><div class="qrs"><div>{qr(BOT)}<span>бот в MAX</span></div>
      <div>{qr(REPO + "/blob/main/JURY_GUIDE.md")}<span>гид проверки</span></div></div>
      <div class="steps"><b>Порядок проверки (5 минут)</b>{steps.replace('<ul>', '<ol>').replace('</ul>', '</ol>')}</div></div>
    </div>"""
    out = [slide("ДомСигнал — данные для проверки", body, kicker="Служебный слайд", cls="service")]
    if private:
        blocks = []
        for a in private["accounts"]:
            codes = ", ".join(a["recovery_codes"][:5])
            qr_png = private["dir"] / "qr" / f"{a['login']}.png"
            qr_img = img_file(qr_png, "totp-qr") if qr_png.is_file() else ""
            blocks.append(
                f'<div class="acc">{qr_img}<div><b>{esc(a["role_ru"])}</b><br><code>{esc(a["login"])}</code> · '
                f'<code>{esc(a["password"])}</code><br><span class="small">TOTP: <code>{esc(a["totp_secret"])}</code></span>'
                f'<br><span class="small">Коды восстановления (одноразовые): {esc(codes)}</span></div></div>'
            )
        tips = """<p class="small">Если вход закрылся («Слишком много попыток») — 5 минут паузы или резервный логин.
        «Неверный или уже использованный код» — подождать следующий код (30 с). Сессия: 30 минут без действий,
        8 часов всего. Аккаунты действуют до 29.10.2026. Разрушающие действия над витриной для проверочных
        аккаунтов неактивны — всё можно на своей УК («Подключить УК» на сайте).</p>"""
        out.append(slide("Доступы: QR-коды TOTP, резерв, коды восстановления",
                         f'<div class="accs">{"".join(blocks)}</div>{tips}',
                         kicker="Служебный слайд — закрытая версия", cls="service"))
    return out


# ------------------------------------------------------------------ содержание
def content() -> list[str]:
    s: list[str] = []
    s.append(f"""<section class="slide title-slide">
      <div class="title-left"><div class="kicker">Трек «Умный город» · хакатон MAX</div>
      <h1 class="big">ДомСигнал</h1>
      <p class="lead">Проблема из домового чата доходит до того, кто решает, — и закрывается, только
      когда житель подтвердил результат.</p>
      <p class="thesis">ИИ понимает, что написали. Проверенный справочник решает, кто отвечает.
      Житель подтверждает, что сделано.</p></div>
      <div class="title-right">{img("s11-board-390.png", "phone")}</div></section>""")
    s.append(slide("Не чат-бот для ЖКХ, а замкнутый контур", cards([
        ("Проблема", "О поломках пишут в домовые чаты, но разговор не становится заявкой с ответственным и "
                     "проверяемым результатом; УК с десятками чатов не успевает их читать."),
        ("Решение", "Бот и мини-приложение в MAX, кабинеты УК и платформы: сообщение или разговор → сигнал или "
                    "заявка → ответственный по справочнику → работа → подтверждение жителем."),
        ("Результат", "Работает в production и в настоящем MAX; УК подключается сама; путь «своя УК с нуля» "
                      "проходит автотест с эмулятором MAX."),
    ]) + numbers([
        ("1 000", "чатов на железе production — ≈ 0,3 ядра [изм.]"),
        ("≈ 0,1 ₽", "за разбор окна переписки моделью [изм.]"),
        ("160", "приёмочных кейсов: 145 авто PASS, 14 — живой MAX"),
        ("4", "региона + федеральный слой справочника"),
    ]), kicker="Кратко"))
    s.append(slide("Лифт стоит второй день, а в чате — «+», «у нас тоже» и «кто-нибудь звонил?»", two(
        bullets([
            "<b>Анна</b>, 2-й подъезд, 9-й этаж, коляска. Пишет в чат дома о лифте; соседи отвечают, но никто "
            "не знает, дошло ли до УК.",
            "<b>Ирина</b>, диспетчер УК: 50 домов, 50 чатов, три сотрудника. Читать чаты некому.",
            "Путь проблемы рвётся в трёх местах: <b>кому писать</b> (УК, город, РСО, 112), <b>дошло ли</b>, "
            "<b>починили ли</b>. Опасность — газ, дым, щиток — теряется в потоке.",
        ]),
        numbers([("01.09.2026", "УК обязаны работать с жителями в MAX (ПП РФ № 40, изм. ПП № 416)"),
                 ("14,5 млн", "в домовых чатах MAX на 13.05.2026 (Минстрой, РИА Недвижимость)"),
                 ("+41,2 %", "обращений в ГЖИ Татарстана, I полугодие 2026")]), "1.1fr 1fr"),
        kicker="Ситуация и почему сейчас",
        note="Персонажи вымышлены; ситуация — по двум реальным домовым чатам и словам эксперта на Q&amp;A организаторов."))
    s.append(slide("Что показали два реальных домовых чата", two(
        bullets([
            "Telegram — 25 488 сообщений, 432 автора, 5,6 года; WhatsApp — 9 096 сообщений, 177 авторов.",
            "Проблема дома — в <b>12,5 %</b> окон переписки [8,6; 17,8].",
            "УК с 50 загруженными чатами: ≈ 480 окон в сутки, из них <b>≈ 60 о проблемах</b> [41; 85] — расчёт.",
            "17 % адресованных проблем — <b>вне зоны УК</b>; правила без модели находят только 36 % проблем — "
            "поэтому нужен ИИ.",
        ]),
        cards([("As Is", "реплика → соседи дублируют → кто-то звонит (или никто) → диспетчер записывает без "
                         "подъезда → житель узнаёт случайно"),
               ("To Be", "житель пишет как привык → ДомСигнал замечает проблему и опасность → справочник: кто "
                         "отвечает → заявка УК или официальный сервис → отчёт исполнителя → житель: «Исправлено» "
                         "или «Проблема осталась»")], 1)),
        kicker="Данные и процесс",
        note="2 чата — наблюдение, не выборка; разметка — ИИ-агентом после маскирования; реальные тексты модели "
             "продукта не отправлялись."))
    s.append(slide("Три входа: пишу как привык", two(
        bullets([
            "<b>Домовой чат.</b> Бот читает с согласия УК и молчит; разговор соседей становится сигналом "
            "для УК, при опасности — памятка «звоните 112».",
            "<b><code>/report</code> в чате или сообщение боту в личку</b> — заявка, ответ приходит лично.",
            "<b>Мини-приложение</b>: «Сообщить о проблеме» → «Проверьте, что мы поняли» → «Изменить» — "
            "житель видит, как его поняли, до отправки.",
            "Не нужно знать категорию и адресата — достаточно написать.",
        ]), phones("s13c-report-390.png", "s13c-review-390.png"), "1.05fr 1fr"), kicker="Житель"))
    s.append(slide("Заявка из чата: статусы в том же посте, закрывает житель", two(
        bullets([
            "<code>/report …</code> → пост «Заявка T-N · Статус…» с кнопками «Меня тоже касается» и «Открыть».",
            "Оператор: «Принять заявку» → «Начать работу» → «Сообщить о выполнении» — пост правится, "
            "жителю в личку «Проверьте, устранена ли проблема».",
            "«Проблема осталась» — та же заявка снова в работе, номер не меняется; «Исправлено» — "
            "«Закрыта: жители подтвердили».",
            "История заявки неизменяема: каждая попытка, возражение и подтверждение.",
        ]), '<div class="pair"><div class="duo">' + img("op-ticket-head.png", "shot") + img("op-ticket-attempts.png", "shot")
        + '</div><div class="duo">' + img("op-ticket-history.png", "shot") + "</div></div>", "0.9fr 1.3fr"),
        kicker="Основной сценарий", note="Кабинет оператора: заявка T-1 — возражение жителя после первой "
        "попытки, подтверждение после второй; справа — история заявки."))
    s.append(slide("Разговор соседей становится сигналом — решение принимает человек", two(
        bullets([
            "Реплики копятся в окно; после паузы — разбор: роли реплик, подтип из 31, подъезд, этаж.",
            "Повторы склеиваются в один сигнал «N реплик · M жителей» с цитатами.",
            "Оператор: «Создать заявку», «Присоединить», «Внешний маршрут» или «Закрыть» с причиной — "
            "система не засыпает УК автоматическими заявками.",
            "Критические сигналы — наверху, с кнопкой «Открыть последний критический сигнал».",
        ]), img("op-signals.png", "shot"), "1fr 1.25fr"), kicker="Кабинет оператора"))
    s.append(slide("Опасность не ждёт модель", two(
        bullets([
            "Правила опасности — <b>в транзакции приёма</b>, до модели и очереди: памятка «При угрозе жизни и "
            "здоровью звоните 112» в чат и оповещение оператора.",
            "От приёма сервером до принятия памятки MAX — <b>0,67 с</b> [живой MAX 24.09]; при 1 000 чатах "
            "памятки 20/20, p95 0,03 с [изм.].",
            "«В доме напротив горит квартира», «накурили», учения, прошедшее время — без памятки в чат.",
        ]), phones("s13d-danger-390.png"), "1.35fr 1fr"), kicker="Безопасность"))
    s.append(slide("«Не к УК» — кто отвечает, с источником, и готовый текст", two(
        bullets([
            "«На улице у остановки не горят фонари» → «Проблема, вероятно, относится не к вашей УК».",
            "Официальный канал региона из проверенного справочника: Казань — «Народный контроль», "
            "Москва — «Наш город»; источник и дата проверки.",
            "«Подготовить текст обращения» → «Скопировать» → «Я отправил(а) обращение» — отметка жителя, "
            "не регистрация во внешней системе; через 14 дней — «Пришёл ли ответ?».",
            "Регион — пакет данных: новый регион без изменения кода.",
        ]), phones("s13f-problem-390.png"), "1.35fr 1fr"), kicker="Маршрут"))
    s.append(slide("Кабинет УК: заявки, сотрудники, чаты MAX, рассылки", two(
        img("op-tickets-all.png", "shot quad") + '<div class="gap"></div>' + img("adm-max.png", "shot quad"),
        img("adm-overview.png", "shot quad") + '<div class="gap"></div>' + img("adm-staff.png", "shot quad"),
        "1fr 1fr"),
        kicker="УК", note="Снимки — локальный стенд с эмулятором MAX и синтетической УК «Кленовый двор»."))
    s.append(slide("УК подключается сама — без разработчиков", two(
        bullets([
            "Заявка на сайте со списком адресов → страница статуса → одобрение платформой с квотой чатов.",
            "Администратор УК создаёт свой вход: пароль + TOTP, 10 кодов восстановления.",
            "Адреса из заявки → заявки на дома → одобрение пачкой с регионом.",
            "Чат подключается по коду: бот проверяет свои права в MAX до привязки; «Подключено N из M».",
            "Весь путь — автотест с эмулятором MAX, 15 шагов, в том числе на чистом клоне.",
        ]), img("plat-applications.png", "shot"), "1fr 1.2fr"), kicker="Тиражирование"))
    s.append(slide("Платформа: подключение УК и состояние системы — без текстов жителей", two(
        bullets([
            "Заявки УК и домов, квоты чатов, приостановка организаций, регионы.",
            "Очередь по пулам, доставка в MAX, доля окон у правил, расход модели в ₽.",
            "Тексты жителей и заявки платформа не видит — это ограничение ролей в коде, а не обещание "
            "(проверено: 404 на чужие данные).",
        ]), img("plat-overview.png", "shot crop"), "1fr 1.3fr"), kicker="Платформа"))
    s.append(slide("MAX как платформа, а не только чат", cards([
        ("Пост заявки в группе", "правится при каждой смене статуса; кнопки «Меня тоже касается» и «Открыть»"),
        ("Мини-приложение", "подписанный вход MAX и запуск по ссылке (<code>start_param</code>) — сразу на "
                            "нужной проблеме или опросе"),
        ("Личные уведомления", "с кнопками «Исправлено» / «Проблема осталась» — они правят тот же пост"),
        ("Участие в чате = доступ", "вступил в домовую группу — видит свой дом, вышел — нет"),
        ("Подключение чата", "код → бот в группе → проверка прав бота в MAX → подтверждение УК"),
        ("Объявления и опросы", "пост в чате, голосование, итоги только числами; отписка уважается"),
    ]), kicker="Возможности MAX"))
    s.append(slide("ИИ — там, где нужен язык; правила — где нужна гарантия", two(
        table(["Кто", "Что решает"], [
            ["<b>ИИ</b>", "роли реплик, подтип из 31, несколько проблем в окне, опасность «между строк»"],
            ["<b>Правила</b>", "опасность и памятка, подъезд и этаж, итог по опасности; всё при отказе модели"],
            ["<b>Справочник</b>", "кто отвечает — с источником и датой проверки"],
            ["<b>Человек</b>", "сигнал → заявка (оператор); результат (житель)"],
        ]),
        bullets([
            "Модель: <b>Qwen3-30B-A3B</b> (Apache 2.0) через Cloud.ru Foundation Models; по документации "
            "Cloud.ru — внешняя модель. Текст маскируется; идентификаторы людей, чатов и домов не передаются.",
            "Контроль: опасные окна 30/30 и 10/10 — <b>0 пропусков</b>; инциденты 37/39 (правила 35/39); "
            "JSON 99 %; p95 10,9 с [изм., синтетика].",
            "Отказ, таймаут, 429 — окно разбирают правила, предохранитель после 3 отказов; окно не теряется.",
        ]), "1fr 1fr"), kicker="ИИ под контролем"))
    arch = """<div class="arch">
      <div class="lane"><div class="box ext">MAX · домовой чат · личка бота · мини-приложение</div>
        <div class="box ext">Сотрудники УК и платформы · браузер</div></div>
      <div class="arrow">↓ вебхук + секрет · HTTPS (initData MAX; пароль + TOTP)</div>
      <div class="lane"><div class="box">Caddy · TLS, HSTS</div></div>
      <div class="arrow">↓</div>
      <div class="lane three"><div class="box core"><b>api</b> — FastAPI<br>вебхук, API, кабинеты,<br>опасность при приёме</div>
        <div class="box core"><b>worker</b> operational<br>окна, заявки, рассылки,<br>доставка в MAX → MAX Bot API</div>
        <div class="box core"><b>ai-worker</b><br>маскирование → модель → проверка<br>→ Cloud.ru · Qwen3-30B-A3B</div></div>
      <div class="arrow">↓ одна транзакция: данные + задачи + исходящие</div>
      <div class="lane"><div class="box db"><b>PostgreSQL 16</b> — данные · очередь jobs (SKIP LOCKED) · outbox · inbox</div>
        <div class="box side">regions/ — справочник<br>каналов и правил</div>
        <div class="box dashed">ml/ — локальная модель<br>(в репозитории, не в работе)</div></div>
    </div>"""
    s.append(slide("Архитектура: один образ, три процесса, PostgreSQL как данные и очередь",
                   arch + bullets([
                       "<code>api</code> — вебхук MAX, API, кабинеты; <code>worker</code> — окна, заявки, доставка; "
                       "<code>ai-worker</code> — только модель. Задачи и outbox — в той же транзакции PostgreSQL.",
                       "Растёт числом процессов: <code>--scale ai-worker=N</code>, циклы в процессе, PgBouncer; "
                       "<code>ml/</code> — локальная модель, пока не в работе."]), kicker="Техника", cls="arch-slide"))
    s.append(slide("API решения — заявлен и проверяем", two(
        bullets([
            f"Адрес <code>{SITE[8:]}/api/v1</code>, OpenAPI 3.1 — <code>/openapi.json</code> = "
            "<code>docs/openapi.json</code> (сверяется в CI).",
            "<code>DATA-API.yaml</code>: 24 проверки — служебные методы, отказы без входа, три роли, "
            f"изоляция УК; на production — <b>{FACTS['data_api']}</b>.",
            "Ошибки — RFC 7807 с <code>code</code> и <code>trace_id</code>; повтор с тем же "
            "<code>Idempotency-Key</code> — тот же результат, другое тело — 409.",
            "Вход сотрудников: пароль + TOTP, CSRF, cookie <code>__Host-</code>; житель — подпись MAX.",
        ]),
        table(["Роль", "Видит", "Чужое"], [
            ["Житель", "свой дом", "404"], ["Оператор", "дома по назначению", "403 / 404"],
            ["Администратор УК", "своя УК", "404"], ["Платформа", "организации, система", "тексты — нет"]]),
        "1.2fr 1fr"), kicker="API"))
    s.append(slide("Качество: каждый кейс — с тестом или честной пометкой «нужен человек в MAX»", numbers([
        (FACTS["backend"], "backend unit и контракты"), (FACTS["integration"], "интеграция на PostgreSQL"),
        (FACTS["frontend"], "фронтенд unit"), (FACTS["browser"], "браузерные сценарии"),
    ]) + bullets([
        "Финальная версия: сквозной путь «своя УК с нуля» через эмулятор MAX — 15 из 15, сценарии — 38 из 38; "
        f"матрица приёмки (срез F1): {FACTS['acceptance']}.",
        "Перезапуск api / воркеров / базы / стека — готов за 0–4 с, данные на месте; при остановленном воркере "
        "приём работает, задачи ждут; повтор запроса не дублирует заявку.",
        "Чистый клон → <code>docker compose up --build</code>: сборка 34 с, готовность 20 с; секретов в истории нет "
        "(gitleaks).",
    ]), kicker="Проверки финальной версии"))
    s.append(slide("Масштаб и стоимость", two(
        table(["", "50 чатов", "1 000", "5 000"], [
            ["Окон в час пик", "42", "850", "4 240"],
            ["Процессы разбора", "1", "2 цикла", "2 × 4 цикла"],
            ["Модель, ₽/мес", "1,5–1,6 тыс.", "29–32 тыс.", "145–159 тыс."],
            ["Метка", "расчёт", "измерено на железе prod", "расчёт"],
        ]),
        bullets([
            "Разбор: 616 → 2 536 → 5 027 окон в час при 1 → 4 → 8 циклах [изм., модель-заглушка].",
            "1 УК — один VPS; 10 УК — те же процессы, квоты; 100 УК — копии процессов и PgBouncer.",
            "Регион — пакет данных: 4 региона + федеральный слой; фонарь в Казани → «Народный контроль», "
            "в Москве → «Наш город».",
            "Без модели — 0 ₽: работают правила.",
        ]), "1fr 1fr"), kicker="Рост"))
    s.append(slide("Что работает, что готово в фундаменте, что в плане", table(
        ["Работает сейчас", "ML-фундамент (в репозитории, не в работе)", "Тестовое", "План финала"],
        [["Бот и мини-приложение в MAX, чтение чата, сигналы, заявки, статусы в посте, подтверждение жителем, "
          "опасность, внешние каналы, кабинеты УК и платформы, TOTP, квоты, рассылки, опросы, совет, приём, API",
          "Локальный классификатор <code>ml/</code>: 33 класса, срочность, группировка сообщений; офлайн, ≈ 8 мс, 0 ₽",
          "Демо-УК «Пилотная, 7», демо-чат, тестовые УК; синтетические наборы оценки; 5 000 чатов — расчёт",
          "<code>local_ml</code> в режиме тени, решения операторов как разметка, модель внутри РФ, пилот с УК, "
          "сроки в кабинете"]], "four"), kicker="Честно о статусе"))
    s.append(slide("ML-фундамент: локальная модель уже в репозитории", two(
        bullets([
            "Сообщение → есть ли проблема → класс из 33 → тип реплики → срочность → подъезд/этаж; лента чата → "
            "предварительная заявка.",
            "Лёгкий вариант: TF-IDF + логистическая регрессия, ≈ 8 мс и 247 МБ; усиленный: + E5 и дообученный "
            "ruBERT.",
            "Отложенная часть набора из двух реальных чатов: нахождение проблемы <b>AP 0,900 / 0,829</b>, вся "
            "цепочка <b>macro-F1 0,669 / 0,571</b>, объединение F1 0,354 при точности 0,928.",
            "Ограничения: разметка ИИ-агентом, людьми не проверена; срочность — полнота 0,507, самостоятельной "
            "тревоге не доверяем.",
            f"В рабочую систему не подключён; {FACTS['ml_tests']} юнит-тестов и смоук-запуск на синтетике — "
            "<code>ml/README.md</code>.",
        ]),
        cards([("Сейчас", "правила + внешняя модель: ≈ 0,1 ₽ за окно, p95 ≈ 11 с, данные вне Cloud.ru"),
               ("С local_ml", "0 ₽ за запрос, миллисекунды, текст не покидает контур"),
               ("Как подключаем", "третий провайдер за тем же интерфейсом <code>analyze_window</code> в "
                                  "<code>ai-worker</code>; опасность — по-прежнему правила")], 1), "1.3fr 1fr"),
        kicker="Что реализуем при выходе в финал · 1/2"))
    s.append(slide("План на две недели финала", two(
        table(["Неделя 1", "Метрика"], [
            ["<code>local_ml</code> в режиме тени рядом с Qwen3 и правилами", "не хуже Qwen3 на holdout (37/39); "
             "p95 ≤ 100 мс; 0 ₽"],
            ["Решения операторов по сигналам как разметка (верно / класс)", "≥ 300 проверенных людьми окон"],
            ["Человеческий эталон: 300 окон, два разметчика", "κ ≥ 0,7"],
        ]),
        table(["Неделя 2", "Метрика"], [
            ["Выбор способа разбора по дому", "F1 проблемы на эталоне ≥ текущего; 0 пропусков опасности"],
            ["Подсказки группировки сигналов оператору", "точность ≥ 0,9; F1 ≥ 0,5 на новом периоде"],
            ["Модель внутри РФ на тех же наборах", "опасность 30/30 и 10/10; JSON ≥ 99 %; ≤ 0,15 ₽"],
            ["Пилот с УК Казани; сроки и отзыв чата в кабинете", "время до принятия, доля подтверждений жителями"],
        ]), "1fr 1fr"),
        kicker="Что реализуем при выходе в финал · 2/2", note="Метрики — цели проверки, не обещания; подробно — "
        "docs/FINAL_PLAN.md."))
    s.append(slide("Ограничения и риски — говорим сами", two(
        bullets([
            "Модель внешняя (данные вне инфраструктуры Cloud.ru) — для пилота нужна модель внутри РФ.",
            "Кастдева не было; качество модели измерено на синтетике одного автора.",
            "Нормативные сроки не ведём; обращения во внешние системы отправляет житель.",
            "Живые проверки в клиенте MAX частично ручные — список в матрице приёмки.",
        ]),
        bullets([
            "<b>Пилот (предложение):</b> одна УК в Казани, её домовые чаты, 4 недели — партнёра пока нет.",
            "Метрики уже считает дашборд: время до принятия заявки, доля подтверждений жителями, возвраты "
            "«Проблема осталась», сигналы из чатов.",
        ]), "1fr 1fr"), kicker="Реализм"))
    s.append(slide("Команда", cards([
        ("Влад Демин", "продукт, бэкенд, бот и мини-приложение MAX, кабинеты, выкладка и эксплуатация (DEV-B)"),
        ("Дмитрий Ромашкин", "ИИ и ML: разбор переписки, оценка моделей, локальный классификатор <code>ml/</code> (DEV-A)"),
    ], 2) + bullets([
        "Код и тесты писали ИИ-агенты (Claude Code) по срезам; решения по продукту и безопасности и живые "
        "проверки в MAX — люди команды.",
        "Решения с датами — <code>docs/decisions.md</code>; ни одно изменение не принималось без автоматических "
        "проверок.",
    ]), kicker="Кто делал"))
    s.append(f"""<section class="slide title-slide end"><div class="title-left">
      <h1 class="big">ДомСигнал</h1>
      <p class="thesis">ИИ понимает, что написали. Проверенный справочник решает, кто отвечает.
      Житель подтверждает, что сделано.</p>
      <p class="lead">Работает в MAX сегодня · УК подключается сама · регион — пакет данных.</p>
      <p class="small">Источники: ПП РФ № 40 от 26.01.2026 — publication.pravo.gov.ru/document/0001202601300066;
      14,5 млн в домовых чатах MAX — realty.ria.ru/20260513/max-2092174285.html; ГЖИ РТ — rt-online.ru,
      16.07.2026. Репозиторий: README.md, docs/, evaluation/reports/, ml/README.md.</p></div>
      <div class="title-right">{qr(BOT, 200)}<span>бот в MAX</span></div></section>""")
    return s


CSS = """
@page { size: 1280px 720px; margin: 0; }
* { box-sizing: border-box; }
body { margin: 0; font-family: "Segoe UI", Arial, sans-serif; color: #111827; background: #fff; }
.slide { width: 1280px; height: 720px; padding: 44px 60px 36px; position: relative; overflow: hidden;
  page-break-after: always; break-after: page; background: #fff; }
.slide::before { content: ""; position: absolute; left: 0; top: 0; right: 0; height: 6px; background: #2358d0; }
.kicker { color: #2358d0; font-weight: 700; font-size: 15px; text-transform: uppercase; letter-spacing: .06em; margin-bottom: 6px; }
h1 { font-size: 34px; line-height: 1.15; margin: 0 0 20px; font-weight: 700; }
h1.big { font-size: 76px; margin-bottom: 24px; color: #2358d0; }
ul, ol { margin: 0; padding-left: 22px; }
li { font-size: 20.5px; line-height: 1.38; margin-bottom: 12px; }
code { font-family: Consolas, "Cascadia Mono", monospace; font-size: .9em; background: #eef2fb; padding: 1px 5px; border-radius: 4px; }
a { color: #2358d0; text-decoration: none; }
.lead { font-size: 26px; line-height: 1.35; color: #374151; }
.thesis { font-size: 24px; line-height: 1.4; font-weight: 600; border-left: 5px solid #2358d0; padding-left: 16px; }
.small { font-size: 14px; color: #4b5563; line-height: 1.4; }
.note { position: absolute; left: 60px; right: 60px; bottom: 16px; font-size: 13px; color: #6b7280; }
.two { display: grid; gap: 36px; align-items: start; }
.right { display: flex; flex-direction: column; align-items: center; }
.phones { display: flex; gap: 18px; justify-content: center; }
img.phone { height: 540px; width: auto; border: 1px solid #d1d5db; border-radius: 22px; box-shadow: 0 6px 20px rgba(17,24,39,.12); object-fit: cover; object-position: top; max-width: 300px; }
.phones img.phone { height: 540px; max-width: 250px; }
img.shot { width: 100%; border: 1px solid #d1d5db; border-radius: 10px; box-shadow: 0 6px 20px rgba(17,24,39,.12); }
img.shot.tall { height: 560px; width: auto; max-width: 100%; object-fit: cover; object-position: top; }
img.shot.crop { height: 540px; object-fit: cover; object-position: top; }
.gap { height: 14px; }
.cards { display: grid; gap: 18px; margin-bottom: 22px; }
.card { background: #f5f7fc; border: 1px solid #dfe5f2; border-radius: 14px; padding: 16px 18px; font-size: 18px; line-height: 1.4; }
.card-t { font-weight: 700; color: #2358d0; margin-bottom: 6px; font-size: 18px; }
.numbers { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin: 6px 0 22px; }
.two .numbers { grid-template-columns: 1fr; }
.num { border-top: 4px solid #2358d0; padding-top: 8px; }
.num b { display: block; font-size: 38px; color: #111827; }
.num span { font-size: 15px; color: #4b5563; line-height: 1.3; display: block; }
table { border-collapse: collapse; width: 100%; font-size: 16px; }
th, td { border-bottom: 1px solid #e5e7eb; padding: 9px 10px; text-align: left; vertical-align: top; line-height: 1.35; }
th { background: #f5f7fc; font-weight: 700; }
table.four td { font-size: 17px; width: 25%; }
.title-slide { display: grid; grid-template-columns: 1.4fr 1fr; gap: 40px; align-items: center; }
.title-slide .title-right { display: flex; flex-direction: column; align-items: center; gap: 8px; font-size: 15px; color: #4b5563; }
.title-slide img.phone { height: 600px; max-width: 330px; }
.service h1 { font-size: 30px; margin-bottom: 14px; }
.svc { display: grid; grid-template-columns: 1.55fr 1fr; gap: 28px; }
table.kv th { width: 92px; background: none; color: #2358d0; font-size: 15px; padding: 7px 8px; }
table.kv td { font-size: 15.5px; padding: 7px 8px; }
table.creds th, table.creds td { font-size: 14px; padding: 6px 8px; }
code.totp { font-size: 12.5px; }
.svc-side { display: flex; flex-direction: column; gap: 14px; }
.qrs { display: flex; gap: 18px; justify-content: center; }
.qrs > div { display: flex; flex-direction: column; align-items: center; font-size: 13px; color: #4b5563; }
.qr svg { width: 100%; height: 100%; }
.steps { background: #f5f7fc; border-radius: 12px; padding: 12px 14px; }
.steps b { display: block; margin-bottom: 6px; font-size: 15px; }
.steps li { font-size: 14.5px; margin-bottom: 5px; line-height: 1.3; }
.accs { display: grid; grid-template-columns: 1fr 1fr; gap: 12px 22px; }
.acc { display: flex; gap: 12px; align-items: flex-start; font-size: 14px; line-height: 1.35; border: 1px solid #e5e7eb; border-radius: 10px; padding: 8px; }
img.totp-qr { width: 92px; height: 92px; }
.arch { display: flex; flex-direction: column; gap: 6px; margin-bottom: 14px; }
.lane { display: flex; gap: 14px; justify-content: center; }
.lane.three .box { flex: 1; }
.box { border: 2px solid #2358d0; border-radius: 12px; padding: 9px 14px; font-size: 16px; line-height: 1.3; text-align: center; background: #f5f7fc; }
.box.ext { background: #fff; border-color: #9ca3af; }
.box.core { background: #eaf0fd; }
.box.db { flex: 2.4; background: #e8f5ee; border-color: #1f8f55; }
.box.side { flex: 1; background: #fff; }
.box.dashed { flex: 1; border-style: dashed; border-color: #6b7280; background: #fff; color: #4b5563; }
.arrow { text-align: center; color: #4b5563; font-size: 14px; }
.arch-slide li { font-size: 17px; margin-bottom: 6px; }
.pair { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; width: 100%; }
.duo { display: flex; flex-direction: column; gap: 10px; }
.two .duo img.shot { width: 100%; }
img.shot.quad { height: 262px; object-fit: cover; object-position: top left; }
.end .title-right span { font-size: 16px; }
"""


def build(private_dir: Path | None, commit: str | None, out_pdf: Path) -> None:
    private = None
    if private_dir:
        role_ru = {"jury.platform": "Администратор платформы", "jury.admin": "Администратор УК",
                   "jury.operator": "Оператор УК"}
        accounts = []
        for login in ("jury.operator", "jury.admin", "jury.platform",
                      "jury.operator.reserve", "jury.admin.reserve", "jury.platform.reserve"):
            data = json.loads((private_dir / "accounts" / f"{login}.json").read_text(encoding="utf-8"))
            base_login = login.removesuffix(".reserve")
            data["role_ru"] = role_ru[base_login] + (" — резерв" if login.endswith(".reserve") else "")
            accounts.append(data)
        invite = json.loads((private_dir / "resident.json").read_text(encoding="utf-8"))["chat_invite"]
        private = {"accounts": accounts, "invite": invite, "dir": private_dir}
    slides = service_slide(private, commit) + content()
    page = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>ДомСигнал</title>
<style>{CSS}</style></head><body>{''.join(slides)}</body></html>"""
    html_path = out_pdf.with_suffix(".html")
    html_path.write_text(page, encoding="utf-8")
    subprocess.run(["node", str(HERE / "print_pdf.mjs"), str(html_path), str(out_pdf)], check=True,
                   cwd=ROOT / "miniapp")
    if private_dir is None and not os.getenv("DECK_KEEP_HTML"):
        html_path.unlink()
    print(f"{out_pdf} — {len(slides)} слайдов")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--private", type=Path, help="папка с закрытыми учётками жюри (вне git)")
    parser.add_argument("--commit", help="финальный commit для закрытой версии")
    args = parser.parse_args()
    if args.private:
        out = args.private / "DomSignal_presentation_PRIVATE.pdf"
    else:
        out = HERE / "DomSignal_presentation.pdf"
    build(args.private, args.commit, out)


if __name__ == "__main__":
    main()

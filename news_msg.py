# -*- coding: utf-8 -*-
"""
Як виглядають повідомлення про новини.

Раніше зведення було стовпчиком однакових рядків «11:50  USD — Non-Farm»:
о котрій буде гаряче, видно лише якщо прочитати кожен. Тут воно збирається
часом і валютою:

    🔴 15:30 · 🇺🇸 USD
          Non-Farm Employment Change
          Average Hourly Earnings m/m

Три новини, що виходять одночасно й по одній валюті, — для трейдера одна
подія, а не три. Тому вони стоять під спільною шапкою.

Розмітка — HTML Телеграма (<b>), назви подій приходять із чужого фіда, тому
екрануються. Шапки — трьома мовами: бот пише мовою співрозмовника. Сайт бере
ті самі події з /api/calendar і збирає свою репліку (static/newsay.js);
спільний між ними вигляд, а не код — там свої слова.
"""
import datetime
import html
import re

import calendar_feed

# Прапорець замість слова: у стовпчику валюта помітна одразу.
FLAG = {
    "USD": "🇺🇸", "EUR": "🇪🇺", "GBP": "🇬🇧", "JPY": "🇯🇵", "CHF": "🇨🇭",
    "CAD": "🇨🇦", "AUD": "🇦🇺", "NZD": "🇳🇿", "CNY": "🇨🇳", "ALL": "🌍",
}

# Самі назви подій не перекладаємо — вони так і звучать у стрічці й у терміналі.
WORDS = {
    "uk": {
        "today": "Важливі новини сьогодні",
        "tomorrow": "Завтра",
        "empty": "Сьогодні важливих новин немає",
        "empty_sub": "Календар вільний — день тільки за твоїм планом.",
        "nearest": "найближча о %s",
        "left": "Ще сьогодні",
        "alert": "Через %d хв — важлива новина",
        "alert_many": "Через %d хв — %d %s",
        "footer": "⏰ Нагадаю за пів години до кожної.",
        "forecast": "прогноз %s",
        "prev": "було %s",
        "plural": ("новина", "новини", "новин"),
        "weekdays": ("понеділок", "вівторок", "середа", "четвер",
                     "п'ятниця", "субота", "неділя"),
        "day": "Важливі новини — %s",
        "empty_day": "%s важливих новин немає",
        "week": "Важливі новини на тиждень",
        "empty_week": "На найближчий тиждень важливих новин немає",
    },
    "ru": {
        "today": "Важные новости сегодня",
        "tomorrow": "Завтра",
        "empty": "Сегодня важных новостей нет",
        "empty_sub": "Календарь пустой — день только по твоему плану.",
        "nearest": "ближайшая в %s",
        "left": "Ещё сегодня",
        "alert": "Через %d мин — важная новость",
        "alert_many": "Через %d мин — %d %s",
        "footer": "⏰ Напомню за полчаса до каждой.",
        "forecast": "прогноз %s",
        "prev": "было %s",
        "plural": ("новость", "новости", "новостей"),
        "weekdays": ("понедельник", "вторник", "среда", "четверг",
                     "пятница", "суббота", "воскресенье"),
        "day": "Важные новости — %s",
        "empty_day": "%s важных новостей нет",
        "week": "Важные новости на неделю",
        "empty_week": "На ближайшую неделю важных новостей нет",
    },
    "en": {
        "today": "High-impact news today",
        "tomorrow": "Tomorrow",
        "empty": "No high-impact news today",
        "empty_sub": "The calendar is clear — the day is yours.",
        "nearest": "first at %s",
        "left": "Still ahead today",
        "alert": "In %d min — high-impact news",
        "alert_many": "In %d min — %d %s",
        "footer": "⏰ I'll remind you half an hour before each.",
        "forecast": "forecast %s",
        "prev": "previous %s",
        "plural": ("release", "releases", "releases"),
        "weekdays": ("Monday", "Tuesday", "Wednesday", "Thursday",
                     "Friday", "Saturday", "Sunday"),
        "day": "High-impact news — %s",
        "empty_day": "No high-impact news on %s",
        "week": "High-impact news this week",
        "empty_week": "No high-impact news in the week ahead",
    },
}


# Питання про новини впізнаємо тут, щоб і бот, і помічник на сайті ловили
# їх однаково. Перевірка груба навмисне: вона лише вирішує, чи підкласти
# факти з календаря.
_ASKS = re.compile(
    r"(новин|новост|календар|calendar|news|червон|красн|red folder|нфп|nfp)",
    re.IGNORECASE | re.UNICODE)
_TOMORROW = re.compile(r"(завтра|tomorrow|взавтра)", re.IGNORECASE | re.UNICODE)
_AFTER_TOMORROW = re.compile(r"(післязавтра|послезавтра|day after tomorrow)",
                             re.IGNORECASE | re.UNICODE)
# «на тижні» питають частіше, ніж здається, і відповідь на один день тут
# не годиться. Перевіряємо це першим: російське «на неделе» інакше
# сплуталося б з українською «неділею», тобто з воскресінням.
_WEEK = re.compile(r"(цього тижня|на тижні|на цьому тижні|наступного тижня|"
                   r"на этой неделе|на следующей неделе|на неделе|"
                   r"this week|next week|за тиждень|за неделю)",
                   re.IGNORECASE | re.UNICODE)
# День тижня в питанні: «що по новинах у понеділок». Раніше таке питання
# мовчки віддавалось як «сьогодні» — і в суботу людина читала, що новин
# немає, хоча питала про понеділок.
_WEEKDAYS = (
    (0, re.compile(r"(понеділ|понедельн|monday)", re.IGNORECASE | re.UNICODE)),
    (1, re.compile(r"(вівтор|вторник|tuesday)", re.IGNORECASE | re.UNICODE)),
    (2, re.compile(r"(серед[уиія]|сред[уые]|wednesday)", re.IGNORECASE | re.UNICODE)),
    (3, re.compile(r"(четвер|четверг|thursday)", re.IGNORECASE | re.UNICODE)),
    (4, re.compile(r"(п['’ʼ]?ятниц|пятниц|friday)", re.IGNORECASE | re.UNICODE)),
    (5, re.compile(r"(субот|суббот|saturday)", re.IGNORECASE | re.UNICODE)),
    (6, re.compile(r"(неділ[юіі]|воскрес|sunday)", re.IGNORECASE | re.UNICODE)),
)


def asks_news(text):
    return bool(_ASKS.search(text or ""))


def asks_tomorrow(text):
    return bool(_TOMORROW.search(text or ""))


def asks_day(text, today):
    """Про який день питають: дата, "week" — або None, якщо дня не назвали.

    Назвали день тижня — беремо найближчий такий день попереду; сьогоднішній
    день тижня означає сьогодні, а не через тиждень.
    """
    t = text or ""
    if _WEEK.search(t):
        return "week"
    if _AFTER_TOMORROW.search(t):
        return today + datetime.timedelta(days=2)
    if _TOMORROW.search(t):
        return today + datetime.timedelta(days=1)
    for idx, pat in _WEEKDAYS:
        if pat.search(t):
            return today + datetime.timedelta(days=(idx - today.weekday()) % 7)
    return None


def _w(lang):
    return WORDS.get(lang or "uk", WORDS["uk"])


def words(lang):
    """Шапки для того, хто збирає повідомлення сам (bot.py)."""
    return _w(lang)


def flag(cur):
    return FLAG.get((cur or "").upper(), "🏳️")


def groups(events, tz, day=None):
    """Події, зібрані за часом і валютою.

    Повертає список {"time": "15:30", "cur": "USD", "titles": [...],
    "events": [...]} у порядку годинника. day=None — беремо все, що дали.
    """
    rows = []
    for e in events:
        dt = calendar_feed.event_time(e)
        if not dt:
            continue
        local = dt.astimezone(tz)
        if day and local.date() != day:
            continue
        rows.append((local, e))
    rows.sort(key=lambda r: r[0])

    out = []
    for local, e in rows:
        when = local.strftime("%H:%M")
        cur = (e.get("country") or "").upper()
        if out and out[-1]["time"] == when and out[-1]["cur"] == cur:
            out[-1]["titles"].append(e.get("title") or "")
            out[-1]["events"].append(e)
            continue
        out.append({"time": when, "cur": cur,
                    "titles": [e.get("title") or ""], "events": [e]})
    return out


def _esc(s):
    return html.escape(str(s or ""), quote=False)


def _block(g):
    head = "🔴 <b>%s</b> · %s %s" % (_esc(g["time"]), flag(g["cur"]), _esc(g["cur"]))
    body = "\n".join("      %s" % _esc(t) for t in g["titles"] if t)
    return head + ("\n" + body if body else "")


def _count(n, lang):
    one, few, many = _w(lang)["plural"]
    if lang == "en":
        return one if n == 1 else few
    a, b = n % 10, n % 100
    if a == 1 and b != 11:
        return one
    if 2 <= a <= 4 and not 12 <= b <= 14:
        return few
    return many


def _body(gs):
    return "\n\n".join(_block(g) for g in gs)


def day_name(day, today, lang="uk"):
    """«сьогодні», «завтра» — або «понеділок, 07.09» для дальшого дня."""
    w = _w(lang)
    if day == today:
        return w["today"]
    if day == today + datetime.timedelta(days=1):
        return w["tomorrow"]
    return "%s, %s" % (w["weekdays"][day.weekday()], day.strftime("%d.%m"))


def digest(events, tz, day, lang="uk", today=None):
    """Ранкове зведення: усі «червоні» новини дня.

    Порожній день — теж повідомлення: людина його чекає й має знати, що
    сьогодні можна на календар не оглядатись.

    today — який день вважати сьогоднішнім. Потрібен, коли питають не про
    сьогодні: шапка «Важливі новини сьогодні» над новинами понеділка
    збивала з пантелику, а на порожньому дні прямо брехала.
    """
    w = _w(lang)
    gs = groups([e for e in events if calendar_feed.is_high(e)], tz, day)
    other = today is not None and day != today
    if not gs:
        if other:
            return "☀️ <b>%s</b>\n%s" % (
                w["empty_day"] % day_name(day, today, lang).capitalize(), w["empty_sub"])
        return "☀️ <b>%s</b>\n%s" % (w["empty"], w["empty_sub"])
    n = sum(len(g["titles"]) for g in gs)
    title = w["day"] % day_name(day, today, lang) if other else w["today"]
    head = "☀️ <b>%s</b>\n%d %s · %s" % (
        title, n, _count(n, lang), w["nearest"] % gs[0]["time"])
    return "%s\n\n%s\n\n%s" % (head, _body(gs), w["footer"])


def week_digest(events, tz, today, lang="uk", days=7):
    """Тиждень уперед: по днях, тільки ті, де щось є.

    Питання «що там на тижні» одним днем не закрити, а сім окремих зведень
    у чат ніхто читати не буде. Тому — короткий список: день, час, валюта.
    """
    w = _w(lang)
    high = [e for e in events if calendar_feed.is_high(e)]
    out = []
    for i in range(days):
        day = today + datetime.timedelta(days=i)
        gs = groups(high, tz, day)
        if not gs:
            continue
        rows = ["  %s · %s %s — %s" % (g["time"], flag(g["cur"]), g["cur"], _esc(t))
                for g in gs for t in g["titles"]]
        out.append("<b>%s</b>\n%s" % (day_name(day, today, lang).capitalize(),
                                      "\n".join(rows)))
    if not out:
        return "☀️ <b>%s</b>\n%s" % (w["empty_week"], w["empty_sub"])
    return "🗓 <b>%s</b>\n\n%s" % (w["week"], "\n\n".join(out))


def remind(events, tz, day, lang="uk"):
    """Нагадування серед дня: те саме, але тільки те, що ще попереду.

    Порожнього нагадування не буває: коли на сьогодні вже нічого не
    лишилось, повертаємо порожній рядок, і бот просто мовчить.
    """
    w = _w(lang)
    gs = groups([e for e in events if calendar_feed.is_high(e)], tz, day)
    if not gs:
        return ""
    n = sum(len(g["titles"]) for g in gs)
    head = "⏳ <b>%s</b>\n%d %s, %s" % (
        w["left"], n, _count(n, lang), w["nearest"] % gs[0]["time"])
    return "%s\n\n%s" % (head, _body(gs))


def _hint(e, w):
    """Прогноз і попереднє значення однією стрічкою — або нічого."""
    bits = []
    if (e.get("forecast") or "").strip():
        bits.append(w["forecast"] % _esc(e["forecast"].strip()))
    if (e.get("previous") or "").strip():
        bits.append(w["prev"] % _esc(e["previous"].strip()))
    return " · ".join(bits)


def _alert_block(g, w):
    """Той самий блок, що й у зведенні, але з прогнозом під кожним рядком."""
    head = "🔴 <b>%s</b> · %s %s" % (_esc(g["time"]), flag(g["cur"]), _esc(g["cur"]))
    lines = []
    for title, e in zip(g["titles"], g["events"]):
        if not title:
            continue
        lines.append("      %s" % _esc(title))
        hint = _hint(e, w)
        if hint:
            lines.append("         <i>%s</i>" % hint)
    return head + (chr(10) + chr(10).join(lines) if lines else "")


def alert(events, minutes, tz, lang="uk"):
    """За півгодини до новин — усі, що виходять тієї самої хвилини, разом.

    Раніше кожна новина йшла окремим повідомленням: о 15:30 їх буває п'ять,
    і телефон дзвонив п'ять разів поспіль про те саме. Тепер одне
    повідомлення зі списком.
    """
    w = _w(lang)
    if isinstance(events, dict):          # раніше сюди давали одну подію
        events = [events]
    gs = groups(events, tz)
    if not gs:
        return ""
    n = sum(len(g["titles"]) for g in gs)
    if n > 1:
        head = "⚠️ <b>%s</b>" % (w["alert_many"] % (round(minutes), n, _count(n, lang)))
    else:
        head = "⚠️ <b>%s</b>" % (w["alert"] % round(minutes))
    body = (chr(10) + chr(10)).join(_alert_block(g, w) for g in gs)
    return head + chr(10) + chr(10) + body

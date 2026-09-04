# -*- coding: utf-8 -*-
"""
Історія економічних подій.

Фід Forex Factory, з якого живе розділ «Новини», віддає лише поточний
тиждень — минулих виходів у ньому немає взагалі, і навіть фактичного
значення теж (тільки прогноз і «попереднє»). Тому історію беремо з
відкритого календаря TradingView: там на кожен вихід є дата, період,
прогноз і факт, і можна попросити будь-який проміжок часу.

Головна небезпека тут — переплутати показники. Назви в двох календарях
різні («Unemployment Claims» проти «Initial Jobless Claims»), а о 15:30
за Києвом виходить одразу кілька цифр. Тому подію спершу шукаємо за
часом виходу й країною, а потім ОБОВ'ЯЗКОВО звіряємо: останній факт із
TradingView має збігтися з «попереднім» із Forex Factory. Не збіглось —
історію не показуємо взагалі. Краще порожня таблиця, ніж чужі числа,
за якими людина зайде в ринок.
"""
import datetime
import difflib
import json
import os
import re
import threading
import time
import urllib.request

from config import ROOT

TV_URL = "https://economic-calendar.tradingview.com/events"
TV_DIR = os.path.join(ROOT, "data", "tvcal")
TV_TTL = 12 * 3600         # свіжість збереженої відповіді
TV_UA = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Origin": "https://www.tradingview.com",
    "Referer": "https://www.tradingview.com/",
}

# Скільки місяців історії максимум і якими шматками її тягнути. Відповідь
# обрізається на 2000 подіях, а США за рік дають більше — тому по чотири
# місяці за раз. Щойно назбиралось достатньо виходів, зупиняємось.
CHUNK_DAYS = 122
MAX_CHUNKS = 4
WANT_ROWS = 10
MAX_TRIES = 4          # скільки здогадів про показник перевіряємо числами
MIN_SCORE = 0.45       # нижче цієї схожості назв здогад не розглядаємо
KEEP_FILES = 60        # скільки збережених відповідей тримаємо на диску

# Валюта Forex Factory → країни TradingView. Євро — це кілька країн:
# у фіді разом лежать і дані єврозони, і німецькі з італійськими.
COUNTRIES = {
    "USD": "US", "EUR": "EU,DE,FR,IT,ES,NL", "GBP": "GB", "JPY": "JP",
    "CHF": "CH", "CAD": "CA", "AUD": "AU", "NZD": "NZ", "CNY": "CN",
}
# Назви, які в двох календарях розходяться настільки, що за словами їх не
# звести: «Official Cash Rate» — це «RBNZ Interest Rate Decision», а «Non-Farm
# Employment Change» — «Non Farm Payrolls». Тут лише ті події, за якими ходить
# ринок; решту знаходить звичайне порівняння назв.
#
# Без цього списку схожість слів обманює: «German Prelim CPI m/m» чіплялось за
# «Baden Wuerttemberg CPI MoM» — назва схожа, число за минулий місяць збіглось
# випадково, а ряд зовсім інший, земельний.
ALIAS = {
    # ставки центробанків
    "official cash rate": ("RBNZ Interest Rate Decision", "NZ"),
    "overnight rate": ("BoC Interest Rate Decision", "CA"),
    "federal funds rate": ("Fed Interest Rate Decision", "US"),
    "main refinancing rate": ("ECB Interest Rate Decision", "EU"),
    "official bank rate": ("BoE Interest Rate Decision", "GB"),
    "cash rate": ("RBA Interest Rate Decision", "AU"),
    "boj policy rate": ("BoJ Interest Rate Decision", "JP"),
    "snb policy rate": ("SNB Interest Rate Decision", "CH"),
    # ринок праці США
    "non-farm employment change": ("Non Farm Payrolls", "US"),
    "unemployment claims": ("Initial Jobless Claims", "US"),
    "adp non-farm employment change": ("ADP Employment Change", "US"),
    "average hourly earnings m/m": ("Average Hourly Earnings MoM", "US"),
    # ціни
    # None замість країни — назва однакова скрізь: CPI m/m є і в США, і в
    # Швейцарії, і в Британії, а ряд у TradingView зветься так само
    "cpi m/m": ("Inflation Rate MoM", None),
    "cpi y/y": ("Inflation Rate YoY", None),
    "core cpi m/m": ("Core Inflation Rate MoM", None),
    "core cpi y/y": ("Core Inflation Rate YoY", None),
    "gdp q/q": ("GDP Growth Rate QoQ", None),
    "gdp y/y": ("GDP Growth Rate YoY", None),
    "trade balance": ("Balance of Trade", None),
    "retail sales y/y": ("Retail Sales YoY", None),
    "german prelim cpi m/m": ("Inflation Rate MoM Prel", "DE"),
    "german final cpi m/m": ("Inflation Rate MoM Final", "DE"),
    "cpi flash estimate y/y": ("Inflation Rate YoY Flash", "EU"),
    "core cpi flash estimate y/y": ("Core Inflation Rate YoY Flash", "EU"),
    "italian prelim cpi m/m": ("Inflation Rate MoM Prel", "IT"),
    "french prelim cpi m/m": ("Inflation Rate MoM Prel", "FR"),
    "spanish flash cpi y/y": ("Inflation Rate YoY Prel", "ES"),
    # решта важливого
    "retail sales m/m": ("Retail Sales MoM", None),
    "core retail sales m/m": ("Retail Sales Ex Autos MoM", "US"),
    "german retail sales m/m": ("Retail Sales MoM", "DE"),
    "prelim gdp q/q": ("GDP Growth Rate QoQ 2nd Est", "US"),
    "crude oil inventories": ("EIA Crude Oil Stocks Change", "US"),
    "natural gas storage": ("EIA Natural Gas Stocks Change", "US"),
}

# Назва події сама каже, чия вона: «German Prelim CPI m/m» — німецька.
HINTS = {"german": "DE", "italian": "IT", "french": "FR", "spanish": "ES",
         "dutch": "NL"}

_lock = threading.Lock()
_mem = {}


def _norm(s):
    """Слова назви без розмітки й службових хвостиків."""
    drop = {"prelim", "preliminary", "final", "flash", "adv", "advance", "est",
            "estimate", "the", "of", "and", "s", "p", "global", "index", "rate",
            "change", "german", "italian", "french", "spanish", "dutch"}
    words = re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).split()
    return [w for w in words if w not in drop]


def _period_mark(title):
    """m/m, y/y, q/q — порівнювати місячне з річним не можна."""
    t = (title or "").lower()
    if re.search(r"\bm/?m\b|\bmom\b", t):
        return "m"
    if re.search(r"\by/?y\b|\byoy\b", t):
        return "y"
    if re.search(r"\bq/?q\b|\bqoq\b", t):
        return "q"
    return ""


def _score(a, b):
    ta, tb = set(_norm(a)), set(_norm(b))
    if not ta or not tb:
        return 0.0
    jac = len(ta & tb) / float(len(ta | tb))
    seq = difflib.SequenceMatcher(None, " ".join(sorted(ta)),
                                  " ".join(sorted(tb))).ratio()
    return max(jac, seq)


# ------------------------------------------------------------ мережа ----

def _month_start(day, back=0):
    """Перше число місяця, на `back` місяців тому."""
    y, m = day.year, day.month - back
    while m <= 0:
        m += 12
        y -= 1
    while m > 12:
        m -= 12
        y += 1
    return datetime.date(y, m, 1)


def _week_edges(day):
    """Тиждень події з запасом у три дні з обох боків."""
    monday = day - datetime.timedelta(days=day.weekday())
    return monday - datetime.timedelta(days=3), monday + datetime.timedelta(days=10)


def _trim():
    """Кеш не має рости без меж: лишаємо найсвіжіші файли."""
    try:
        files = [os.path.join(TV_DIR, f) for f in os.listdir(TV_DIR) if f.endswith(".json")]
    except OSError:
        return
    if len(files) <= KEEP_FILES:
        return
    files.sort(key=lambda f: os.path.getmtime(f), reverse=True)
    for old in files[KEEP_FILES:]:
        try:
            os.remove(old)
        except OSError:
            pass


def _cache_path(countries, frm, to):
    key = re.sub(r"[^A-Za-z0-9]+", "", countries) + "_" + frm + "_" + to
    return os.path.join(TV_DIR, key + ".json")


def _fetch(countries, frm, to):
    """Події за проміжок. Спершу з кешу, потім із мережі."""
    path = _cache_path(countries, frm, to)
    with _lock:
        got = _mem.get(path)
    if got and time.time() - got[0] < TV_TTL:
        return got[1]
    if os.path.exists(path):
        try:
            if time.time() - os.path.getmtime(path) < TV_TTL:
                with open(path, "r", encoding="utf-8") as f:
                    rows = json.load(f)
                with _lock:
                    _mem[path] = (time.time(), rows)
                return rows
        except Exception:
            pass
    url = ("%s?from=%sT00:00:00.000Z&to=%sT00:00:00.000Z&countries=%s"
           "&minImportance=-1" % (TV_URL, frm, to, countries))
    try:
        req = urllib.request.Request(url, headers=TV_UA)
        with urllib.request.urlopen(req, timeout=25) as r:
            data = json.loads(r.read().decode("utf-8"))
        rows = data.get("result")
        if not isinstance(rows, list):
            raise ValueError("календар віддав не список")
    except Exception as ex:
        print("tv_calendar:", ex)
        # прострочений кеш кращий за порожнечу
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return []
    try:
        os.makedirs(TV_DIR, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        pass
    with _lock:
        _mem[path] = (time.time(), rows)
    _trim()
    return rows


def _when(row):
    try:
        return datetime.datetime.fromisoformat(
            (row.get("date") or "").replace("Z", "+00:00"))
    except Exception:
        return None


# ----------------------------------------------------- пошук показника ----

# --------------------------------------------------------- одиниці ----

def _num(text):
    """«205K», «-1.2%», «1,234» → число або None."""
    s = str(text or "").replace(" ", "").replace(",", "")
    m = re.match(r"^(-?\d+(?:\.\d+)?)([KMBT])?%?$", s, re.I)
    if not m:
        return None
    mul = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}.get((m.group(2) or "").upper(), 1)
    return float(m.group(1)) * mul


def _shown(text):
    """Число так, як його показує Forex Factory: «205K» → (205.0, 'K', 0)."""
    s = str(text or "").replace(" ", "").replace(",", "")
    m = re.match(r"^(-?\d+(?:\.\d+)?)([KMBT])?(%)?$", s, re.I)
    if not m:
        return None
    tail = (m.group(2) or "").upper() + (m.group(3) or "")
    dot = m.group(1).split(".")
    return float(m.group(1)), tail, (len(dot[1]) if len(dot) > 1 else 0)


def _fmt(value, tail, digits):
    if value is None:
        return ""
    r = round(value, max(digits, 2))
    txt = ("%.*f" % (digits, r)) if digits else ("%g" % r)
    return txt + tail


# ------------------------------------------------------------ історія ----

def _candidates(event, rows, hours=2, tries=MAX_TRIES):
    """Рядки TradingView, які можуть бути нашою подією, від схожих до менш.

    Назви в двох календарях розходяться сильніше, ніж здається: «Official
    Cash Rate» у Forex Factory — це «RBNZ Interest Rate Decision» у
    TradingView, схожість слів майже нульова. Тому назва тут лише впорядковує
    здогадки, а вирішує звірка чисел нижче: вона куди надійніша за слова.
    """
    mine = _when({"date": event.get("date")})
    if not mine:
        return []
    want_country = None
    low = (event.get("title") or "").lower()
    for word, code in HINTS.items():
        if word in low:
            want_country = code
            break
    named = ALIAS.get((event.get("title") or "").strip().lower())
    main = (COUNTRIES.get((event.get("country") or "").strip()) or "").split(",")[0]
    mark = _period_mark(event.get("title"))
    out = []
    for row in rows:
        d = _when(row)
        if not d or abs((d - mine).total_seconds()) > hours * 3600:
            continue
        if want_country and (row.get("country") or "") != want_country:
            continue
        if _period_mark(row.get("title")) != mark:
            continue
        if row.get("actual") is None and row.get("forecast") is None \
                and row.get("previous") is None:
            continue                      # виступи й засідання без чисел
        s = _score(event.get("title"), row.get("title"))
        same = (not named[1]) or (row.get("country") or "") == named[1] if named else False
        if named and (row.get("title") or "").lower() == named[0].lower() and same:
            s = 2.0                   # прямий запис у таблиці — поза чергою
        elif s < MIN_SCORE:
            continue                  # надто далека назва: це інший показник
        if not want_country and (row.get("country") or "") == main:
            s += 0.1        # «Final Manufacturing PMI» для EUR — це єврозона,
                            # а не Іспанія з Італією, що виходять тієї ж хвилини
        out.append((s, row))
    out.sort(key=lambda z: -z[0])
    return [r for _, r in out[:tries]]


def _rows_for(row, day, limit):
    """Усі виходи цього ж показника, від нових до старих."""
    country, title = row.get("country") or "", row.get("title") or ""

    def chunk(i):
        # межі — перші числа місяців, однакові для всіх подій цього місяця:
        # інакше кожна подія просила б свій зсунутий діапазон, і те саме
        # тягнулося б із мережі по десять разів
        end = _month_start(day, 4 * i - 1)
        start = _month_start(day, 4 * i + 3)
        return [r for r in _fetch(country, start.isoformat(), end.isoformat())
                if (r.get("title") or "") == title and (r.get("country") or "") == country]

    got = chunk(0)
    if len([r for r in got if r.get("actual") is not None]) < limit:
        # решту проміжків беремо разом: послідовно виходило під десять секунд,
        # а це чекання людини з відкритим вікном
        more = [None] * (MAX_CHUNKS - 1)

        def grab(i):
            try:
                more[i - 1] = chunk(i)
            except Exception:
                more[i - 1] = []

        threads = [threading.Thread(target=grab, args=(i,), daemon=True)
                   for i in range(1, MAX_CHUNKS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=25)
        for part in more:
            got += part or []

    seen, uniq = set(), []
    for r in sorted(got, key=lambda z: z.get("date") or "", reverse=True):
        d = r.get("date") or ""
        if d and d not in seen:
            seen.add(d)
            uniq.append(r)
    return uniq


def _series(event, row, limit):
    """Історія за одним здогадом — або [], якщо числа не зійшлись.

    Звіряємось двічі: «попереднє» з фіда має дорівнювати факту виходу, що
    БУВ ДО нашої події, а прогноз фіда — прогнозу того самого рядка. Один
    збіг ще може бути випадковим (дві ставки по 2.50%), два — навряд.
    """
    shown = _shown(event.get("previous"))
    if not shown:
        return [], False
    want, tail, digits = shown
    mine = _when({"date": event.get("date")})
    uniq = _rows_for(row, mine.date(), limit)
    before = [r for r in uniq if r.get("actual") is not None
              and (_when(r) or mine) < mine - datetime.timedelta(hours=1)]
    if not before:
        return [], False

    fact = before[0].get("actual")
    # Допуск рахуємо від того, скільки знаків показує фід: «0.1M» — це будь-що
    # від 0.05 до 0.15, і вимагати точної рівності з 0.108 безглуздо.
    tol = max(abs(want) * 0.005, 0.5 * (10 ** -digits))
    scale = None
    for k in (1, 1e3, 1e-3, 1e6, 1e-6):
        if abs(fact * k - want) <= tol:
            scale = k
            break
    if scale is None:
        return [], False

    # Другий доказ: прогнози в двох календарях мають бути хоча б поруч.
    # Точної рівності тут не буває — консенсус збирають з різних опитувань
    # (58K проти 56K на тих самих робочих місцях), тому допуск широкий:
    # він відсіює чужий показник, а не дрібну розбіжність.
    sure = True
    fc = _shown(event.get("forecast"))
    if fc and row.get("forecast") is not None:
        sure = abs(row["forecast"] * scale - fc[0]) <= max(abs(fc[0]) * 0.3, 0.2)

    out = []
    for r in [x for x in uniq if x.get("actual") is not None][:limit]:
        d = _when(r)
        out.append({
            "date": d.isoformat() if d else (r.get("date") or ""),
            "period": r.get("period") or "",
            "forecast": _fmt(r["forecast"] * scale, tail, digits)
                        if r.get("forecast") is not None else "",
            "actual": _fmt(r["actual"] * scale, tail, digits),
        })
    return out, sure


def history(event, limit=WANT_ROWS):
    """Попередні виходи цієї ж події: дата, період, прогноз, факт.

    event — подія з фіда Forex Factory (title, country, date, previous).
    Повертає [] щоразу, коли не вдалось переконатись, що показник той самий.
    """
    group = COUNTRIES.get((event.get("country") or "").strip())
    if not group or not (event.get("title") or "").strip():
        return []
    mine = _when({"date": event.get("date")})
    if not mine or not _shown(event.get("previous")):
        return []

    day = mine.date()
    frm, to = _week_edges(day)
    near = _fetch(group, frm.isoformat(), to.isoformat())
    # Спершу шукаємо здогад, який зійшовся і по факту, і по прогнозу. Якщо
    # такого немає — беремо перший, що зійшовся хоча б по факту.
    maybe = []
    tried = []
    # Спершу шукаємо поруч за часом. Не знайшли — розсуваємо вікно на весь
    # день: у Forex Factory частина подій стоїть «орієнтовно» (німецький CPI
    # там о 09:29 замість 15:00), і за двома годинами їх не видно.
    for hours, tries in ((2, MAX_TRIES), (8, 2 * MAX_TRIES)):
        for row in _candidates(event, near, hours, tries):
            key = (row.get("country"), row.get("title"), row.get("date"))
            if key in tried:
                continue
            tried.append(key)
            got, sure = _series(event, row, limit) or ([], False)
            if got and sure:
                return got
            if got:
                maybe.append(got)
        if maybe:
            return maybe[0]
    return []

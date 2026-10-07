# -*- coding: utf-8 -*-
"""
Свічки з історії: звідки режим «Перемотка» бере графік.

Навіщо. Журнал досі жив без котирувань: угоду людина записувала руками, а
графік лишався в її терміналі. Для перемотки графік потрібен свій — бар за
баром, з можливістю зупинитись посеред дня й відкрити угоду звідти.

Джерела. Їх кілька, і людина обирає, чиїми цінами ганяти прогін: ціни в
різних постачальників трохи різні, і хто торгує на своєму брокері, хоче
бачити його свічки. Влаштовані всі однаково — файл на добу, який можна
покласти на диск і більше не перепитувати:

  * `dukascopy` — історичний фід брокера Dukascopy. Валюти, метали,
    індекси, нафта; глибина — роки. Ключів не треба, але частих звернень
    не любить і відповідає 503, тому нижче пауза й повтори.
  * `binance`   — добові архіви біржі (data.binance.vision). Тільки крипта,
    зате повна історія з 2017-го, без ключів і без обмежень частоти.

Додати ще одного — це рядок у SOURCES плюс дві невеликі функції: як
скласти адресу дня і як розібрати відповідь. Брокери на кшталт Oanda чи
Forex.com теж лягають сюди, але в них історія за ключем від рахунку —
про це в README біля SOURCES.

Де лежить. У базі свічкам не місце: це спільний довідник, однаковий для
всіх, і він удвічі більший за весь журнал. Тому диск —
`data/candles/ДЖЕРЕЛО/ІНСТРУМЕНТ/РРРР-ММ-ДД.роз`, як зроблено з чужим
календарем у `tv_calendar.py`. Скачане не протухає: історія вчорашнього
дня вже не зміниться. Загубиться кеш — просто скачається знову.

Час скрізь UTC. У якому поясі його показувати, вирішує браузер.
"""
import csv
import datetime
import gzip
import io
import json
import lzma
import os
import struct
import threading
import time
import urllib.error
import urllib.request
import zipfile

import config

DIR = os.path.join(config.ROOT, "data", "candles")

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"}

PAUSE = 0.35                    # пауза між зверненнями до одного джерела
TRIES = 4                       # скільки разів повторюємо після 503
MAX_DAYS = 400                  # стеля на один запит діапазону
NL = chr(10)

# Таймфрейми в секундах. Понад добу не тримаємо: перемотка тижневими
# свічками — це вже не перевірка входів, а огляд історії.
TF = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800,
      "1h": 3600, "4h": 14400, "1d": 86400}

_net_lock = threading.Lock()
_last_call = {}

# Скільки поспіль зривів вважаємо «джерело лежить» і на скільки тоді до
# нього не ходимо. Без цього недоступний фід перетворює звичайний запит на
# багатохвилинне очікування: кожен день окремо чекає свої чотири спроби.
# Dukascopy, наприклад, блокує за частоту — і тоді жодна спроба не пройде.
FAIL_LIMIT = 3
COOLDOWN = 300
_fails = {}
_cold = {}


def cooling(source):
    """Скільки секунд джерелу ще відпочивати; 0 — можна користуватись."""
    left = _cold.get(source, 0) - time.time()
    return max(0, int(left))


def _note_fail(source):
    _fails[source] = _fails.get(source, 0) + 1
    if _fails[source] >= FAIL_LIMIT:
        _cold[source] = time.time() + COOLDOWN


def _note_ok(source):
    _fails[source] = 0
    _cold.pop(source, None)


class FeedError(RuntimeError):
    """Джерело не віддало день, і це не «торгів не було»."""


# ------------------------------------------------------- Dukascopy ----

DUKA_URL = "https://datafeed.dukascopy.com/datafeed/%s/%04d/%02d/%02d/BID_candles_min_1.bi5"

# Місяць в адресі фіду рахується з нуля: 00 — січень, 11 — грудень. Це не
# здогад, а перевірене: див. `test_candles.py --feed`, де тиждень лягає у
# календар ринку тільки за такої нумерації — субота порожня, п'ятниця
# коротка, неділя відкривається ввечері.
MONTH_BASE = 0

DUKA_REC = struct.Struct(">5if")   # секунда доби, open, close, low, high, обсяг


def _duka_url(code, d):
    return DUKA_URL % (code, d.year, d.month - 1 + MONTH_BASE, d.day)


def _duka_parse(raw, day_start, div):
    """Розпакований файл доби -> [(час UTC, o, h, l, c, обсяг)].

    Хвилини без жодного тіку викидаємо. У файлі доба завжди повна — 1440
    записів, і на вихідних усі вони з нульовим обсягом та однаковою ціною.
    Малювати з них свічки означало б показати рівну лінію там, де ринок
    просто стояв зачинений."""
    try:
        body = lzma.decompress(raw)
    except lzma.LZMAError:
        return []
    out = []
    size = DUKA_REC.size
    for i in range(len(body) // size):
        sec, o, c, l, h, vol = DUKA_REC.unpack_from(body, i * size)
        if vol <= 0 and o == c == l == h:
            continue
        out.append((day_start + sec, o / div, h / div, l / div, c / div, float(vol)))
    return out


# ---------------------------------------------------------- Binance ----

BNC_URL = "https://data.binance.vision/data/spot/daily/klines/%s/1m/%s-1m-%s.zip"


def _bnc_url(code, d):
    return BNC_URL % (code, code, d.isoformat())


def _bnc_parse(raw, day_start, div):
    """Добовий архів біржі: CSV всередині zip. Стовпці — час відкриття,
    open, high, low, close, обсяг."""
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            name = z.namelist()[0]
            text = z.read(name).decode("utf-8", "replace")
    except (zipfile.BadZipFile, IndexError, KeyError):
        return []
    out = []
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 6:
            continue
        try:
            ts = int(row[0])
            o, h, l, c, v = (float(row[i]) for i in range(1, 6))
        except ValueError:
            continue            # заголовок, який біржа іноді кладе першим рядком
        # Біржа міняла одиниці часу: були мілісекунди, стали мікросекунди.
        # Розрізняємо за величиною, а не за роком файлу.
        if ts > 1e15:
            ts //= 1000000
        elif ts > 1e12:
            ts //= 1000
        out.append((ts, o / div, h / div, l / div, c / div, v))
    return out


# ------------------------------------------------------------- FXCM ----

# У FXCM відкритий архів без жодного ключа, і він єдиний з наших джерел
# віддає разом bid і ask — тобто справжній спред брокера, а не вигаданий.
# Платимо за це незручністю: файл не на добу, а на цілий тиждень.
FXCM_URL = "https://candledata.fxcorporate.com/m1/%s/%04d/%d.csv.gz"

# Тиждень у них рахується від першої неділі року: неділя 04.01.2026 — це
# тиждень 1, 11.01 — другий і так далі. Тиждень починається ввечері в
# неділю й закінчується ввечері в п'ятницю, час — UTC.
#
# Але є виняток, і він коштував нам половини архіву. Коли 1 січня випадає
# на понеділок, вівторок або середу, у них з'являється окремий «тиждень
# 1» — огризок від 1 січня до першої неділі, — і вся подальша нумерація
# року зсувається на один. Перевірено живцем на 15 роках по три дати в
# кожному (березень, червень, жовтень): зсув усередині року сталий і
# залежить лише від того, на який день тижня припало 1 січня.
#   1 січня у нд, чт, пт, сб -> зсуву немає (2012, 2015-2017, 2021-2023, 2026)
#   1 січня у пн, вт, ср     -> +1       (2013, 2014, 2018-2020, 2024, 2025)
# Без цієї поправки ми просили сусідній тиждень, потрібної доби в ньому
# не було — і всі сім днів лягали в кеш як «торгів не було», назавжди.
def _fxcm_week(d):
    """Дата -> (рік, номер тижня) в нумерації FXCM."""
    sunday = d - datetime.timedelta(days=(d.weekday() + 1) % 7)
    jan1 = datetime.date(sunday.year, 1, 1)
    first = jan1 + datetime.timedelta(days=(6 - jan1.weekday()) % 7)
    week = (sunday - first).days // 7 + 1
    if jan1.weekday() <= 2:          # пн, вт або ср — попереду є огризок
        week += 1
    return sunday.year, week


def _fxcm_url(code, d):
    year, week = _fxcm_week(d)
    return FXCM_URL % (code, year, week)


def _fxcm_bulk(source, symbol, code, d):
    """Скачати тиждень і розкласти його по днях у кеш.

    Решта джерел віддає добу, і кеш у нас теж подобовий. Щоб не тримати
    один і той самий тижневий файл сім разів, ріжемо його одразу: кожна
    доба лягає окремим gzip-ом, а дні без рядків (субота, свята) —
    позначкою «торгів не було». Після цього кеш заповнений на весь
    тиждень, і day_raw просто його читає."""
    raw = _download(source, _fxcm_url(code, d))
    days = {}
    if raw:
        try:
            text = gzip.decompress(raw).decode("utf-8", "replace")
        except (OSError, EOFError) as ex:
            # Відповідь прийшла, але розпакувати її не вдалось: обрив
            # посеред файлу. Це збій, а не порожній тиждень, і мовчати тут
            # не можна — інакше всі сім днів ляжуть у кеш порожніми, і
            # дірка в графіку лишиться назавжди. Саме так ми вже втрачали
            # цілі місяці: тиждень на сервері є й відкривається, а в нас
            # «торгів не було».
            raise FeedError("FXCM: тиждень прийшов пошкодженим (%s)" % ex)
        for line in text.splitlines():
            head = line[:10]
            if len(head) < 10 or head[2] != "/" or head[5] != "/":
                continue            # заголовок або сміття
            try:
                key = datetime.date(int(head[6:10]), int(head[0:2]), int(head[3:5]))
            except ValueError:
                continue
            days.setdefault(key, []).append(line)
        if not text.strip():
            # Розпакувалось у порожнечу — ні заголовка, ні рядків. Так
            # виглядає обірваний файл, а не порожній тиждень: у їхньому
            # архіві справді трапляються тижні без торгів, але в них усе
            # одно лежить рядок заголовка (71 байт, перевірено на
            # AUDCAD/2022/46 і 2023/27). Тому порожнечу вважаємо збоєм, а
            # самий заголовок — чесно порожнім тижнем.
            raise FeedError("FXCM: порожня відповідь замість тижня")
    sunday = d - datetime.timedelta(days=(d.weekday() + 1) % 7)
    for i in range(7):
        day = sunday + datetime.timedelta(days=i)
        rows = days.get(day)
        _write_cache(source, symbol, day, ".csv.gz",
                     gzip.compress(NL.join(rows).encode("utf-8")) if rows else b"")


def _fxcm_parse(raw, day_start, div):
    """Доба з кеша -> [(час UTC, o, h, l, c, обсяг)].

    Стовпці: час, потім bid OHLC, потім ask OHLC. Малюємо по bid — так
    само, як Dukascopy, інакше два джерела давали б графік із зсувом на
    спред. Обсягу в архіві немає взагалі, тому нуль."""
    try:
        text = gzip.decompress(raw).decode("utf-8", "replace")
    except (OSError, EOFError):
        return []
    out = []
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 5:
            continue
        try:
            t = datetime.datetime.strptime(row[0][:19], "%m/%d/%Y %H:%M:%S")
            ts = int(t.replace(tzinfo=datetime.timezone.utc).timestamp())
            o, h, l, c = (float(row[i]) / div for i in (1, 2, 3, 4))
        except (ValueError, IndexError):
            continue
        out.append((ts, o, h, l, c, 0.0))
    return out


# ------------------------------------------------------------ Oanda ----

# Тут, на відміну від решти, потрібен ключ: публічної історії Oanda не
# тримає, вона віддає її власникам рахунку. Безкоштовний демо-рахунок
# такий ключ дає (AMP > My Services > Manage API Access), історія — з
# 2005 року. Немає ключа в налаштуваннях — джерело просто не з'являється
# у списку, як це зроблено з поштою в `mailer.py`.
OANDA_HOST = {"practice": "https://api-fxpractice.oanda.com",
              "live": "https://api-fxtrade.oanda.com"}


def _oanda_url(code, d):
    # Доба цілком: 1440 хвилинних свічок, а стеля відповіді — 5000.
    nxt = d + datetime.timedelta(days=1)
    host = OANDA_HOST.get(config.OANDA_ENV, OANDA_HOST["practice"])
    return ("%s/v3/instruments/%s/candles?price=M&granularity=M1"
            "&from=%sT00:00:00Z&to=%sT00:00:00Z"
            % (host, code, d.isoformat(), nxt.isoformat()))


def _oanda_headers():
    # Час просимо числом, а не рядком з датою: так його не треба розбирати
    # і не виникає питання, у якому поясі він приїхав.
    return {"Authorization": "Bearer " + config.OANDA_TOKEN,
            "Accept-Datetime-Format": "UNIX"}


def _oanda_parse(raw, day_start, div):
    try:
        got = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        return []
    out = []
    for c in got.get("candles") or []:
        # Незакриту свічку пропускаємо: її ціна ще зміниться, а в історії
        # такій не місце.
        if not c.get("complete"):
            continue
        mid = c.get("mid") or {}
        try:
            ts = int(float(c["time"]))
            o, h, l, cl = (float(mid[k]) for k in ("o", "h", "l", "c"))
        except (KeyError, ValueError, TypeError):
            continue
        out.append((ts, o / div, h / div, l / div, cl / div,
                    float(c.get("volume") or 0)))
    return out


def _oanda_ready():
    return bool(config.OANDA_TOKEN)


# --------------------------------------------------------- джерела ----

# `empty` — коди, за якими день вважається просто порожнім (вихідний,
# свято, немає такого інструмента). Усе інше — збій, і день не можна
# запам'ятовувати як порожній: у Oanda 401 означає поганий ключ, і мовчки
# перетворити це на порожній графік було б найгіршим, що можна зробити.
SOURCES = {
    "dukascopy": {"title": "Dukascopy", "ext": ".bi5", "pause": 1.20,
                  "empty": (404,), "url": _duka_url, "parse": _duka_parse},
    "oanda":     {"title": "Oanda", "ext": ".json", "pause": 0.15,
                  "empty": (400, 404), "url": _oanda_url, "parse": _oanda_parse,
                  "headers": _oanda_headers, "ready": _oanda_ready},
    # 403 тут колись стояв поряд із 404 — і це дорого коштувало. Обидва
    # архіви на будь-який відсутній файл відповідають саме 404 (перевірено
    # живцем: інший рік, інший інструмент, неіснуючий тиждень — усюди 404).
    # А 403 — це відмова за частоту запитів, і коли його вважали «днем без
    # торгів», блокування назавжди лягало в кеш порожнім днем: половина
    # тижнів історії FXCM отак і «зникла».
    "binance":   {"title": "Binance", "ext": ".zip", "pause": 0.10,
                  "empty": (404,), "url": _bnc_url, "parse": _bnc_parse},
    "fxcm":      {"title": "FXCM", "ext": ".csv.gz", "pause": 0.35,
                  "empty": (404,), "url": _fxcm_url, "parse": _fxcm_parse,
                  "bulk": _fxcm_bulk},
}


def source_ready(source):
    """Чи можна цим джерелом користуватись. Одні працюють завжди, інші —
    лише коли в налаштуваннях є ключ."""
    s = SOURCES.get(source)
    if not s:
        return False
    return s["ready"]() if "ready" in s else True

# Інструменти. `src` — код і дільник ціни в кожного джерела, бо називають
# вони їх по-своєму, а ціни Dukascopy віддає цілими: 25550999 це 25550.999
# для індексу і 116337 це 1.16337 для пари валют. Порядок джерел у словнику
# і є порядком за замовчуванням: перше — те, яким малюємо, поки людина не
# обрала інше.
def _fx(title, group="Валюти", jpy=False):
    # Dukascopy віддає ціни цілими, тому дільник; Oanda — вже десятковим
    # рядком, там дільник одиниця.
    div = 1000.0 if jpy else 100000.0
    return {"title": title, "group": group, "digits": 3 if jpy else 5,
            "src": {"fxcm": (None, 1.0), "dukascopy": (None, div),
                    "oanda": (None, 1.0)}}


SYMBOLS = {
    # --- валюти ---
    "EURUSD": _fx("EUR/USD"), "GBPUSD": _fx("GBP/USD"),
    "AUDUSD": _fx("AUD/USD"), "NZDUSD": _fx("NZD/USD"),
    "USDCAD": _fx("USD/CAD"), "USDCHF": _fx("USD/CHF"),
    "USDJPY": _fx("USD/JPY", jpy=True), "EURJPY": _fx("EUR/JPY", jpy=True),
    "GBPJPY": _fx("GBP/JPY", jpy=True), "AUDJPY": _fx("AUD/JPY", jpy=True),
    "CADJPY": _fx("CAD/JPY", jpy=True), "CHFJPY": _fx("CHF/JPY", jpy=True),
    "EURGBP": _fx("EUR/GBP"), "EURCHF": _fx("EUR/CHF"),
    "EURAUD": _fx("EUR/AUD"), "EURCAD": _fx("EUR/CAD"),
    "GBPAUD": _fx("GBP/AUD"), "GBPCAD": _fx("GBP/CAD"),
    "GBPCHF": _fx("GBP/CHF"), "AUDNZD": _fx("AUD/NZD"),
    "AUDCAD": _fx("AUD/CAD"), "NZDJPY": _fx("NZD/JPY", jpy=True),

    # --- метали й нафта ---
    "XAUUSD": {"title": "Золото", "group": "Метали", "digits": 3,
               "src": {"dukascopy": ("XAUUSD", 1000.0), "oanda": ("XAU_USD", 1.0)}},
    "XAGUSD": {"title": "Срібло", "group": "Метали", "digits": 3,
               "src": {"dukascopy": ("XAGUSD", 1000.0), "oanda": ("XAG_USD", 1.0)}},
    "USOIL":  {"title": "Нафта WTI", "group": "Сировина", "digits": 3,
               "src": {"dukascopy": ("LIGHTCMDUSD", 1000.0), "oanda": ("WTICO_USD", 1.0)}},
    "UKOIL":  {"title": "Нафта Brent", "group": "Сировина", "digits": 3,
               "src": {"dukascopy": ("BRENTCMDUSD", 1000.0), "oanda": ("BCO_USD", 1.0)}},

    # --- індекси ---
    "GER40": {"title": "Germany 40", "group": "Індекси", "digits": 3,
              "src": {"dukascopy": ("DEUIDXEUR", 1000.0), "oanda": ("DE30_EUR", 1.0)}},
    "US100": {"title": "US Tech 100", "group": "Індекси", "digits": 3,
              "src": {"dukascopy": ("USATECHIDXUSD", 1000.0), "oanda": ("NAS100_USD", 1.0)}},
    "US500": {"title": "US 500", "group": "Індекси", "digits": 3,
              "src": {"dukascopy": ("USA500IDXUSD", 1000.0), "oanda": ("SPX500_USD", 1.0)}},
    "US30":  {"title": "US 30", "group": "Індекси", "digits": 3,
              "src": {"dukascopy": ("USA30IDXUSD", 1000.0), "oanda": ("US30_USD", 1.0)}},
    "UK100": {"title": "UK 100", "group": "Індекси", "digits": 3,
              "src": {"dukascopy": ("GBRIDXGBP", 1000.0), "oanda": ("UK100_GBP", 1.0)}},
    "FRA40": {"title": "France 40", "group": "Індекси", "digits": 3,
              "src": {"dukascopy": ("FRAIDXEUR", 1000.0), "oanda": ("FR40_EUR", 1.0)}},
    "EU50":  {"title": "Europe 50", "group": "Індекси", "digits": 3,
              "src": {"dukascopy": ("EUSIDXEUR", 1000.0), "oanda": ("EU50_EUR", 1.0)}},
    "JP225": {"title": "Japan 225", "group": "Індекси", "digits": 3,
              "src": {"dukascopy": ("JPNIDXJPY", 1000.0), "oanda": ("JP225_USD", 1.0)}},
    "AUS200": {"title": "Australia 200", "group": "Індекси", "digits": 3,
               "src": {"dukascopy": ("AUSIDXAUD", 1000.0), "oanda": ("AU200_AUD", 1.0)}},

    # --- крипта ---
    "BTCUSD": {"title": "Bitcoin", "group": "Крипта", "digits": 2,
               "src": {"binance": ("BTCUSDT", 1.0), "dukascopy": ("BTCUSD", 1000.0)}},
    "ETHUSD": {"title": "Ethereum", "group": "Крипта", "digits": 2,
               "src": {"binance": ("ETHUSDT", 1.0), "dukascopy": ("ETHUSD", 1000.0)}},
    "SOLUSD": {"title": "Solana", "group": "Крипта", "digits": 2,
               "src": {"binance": ("SOLUSDT", 1.0)}},
    "XRPUSD": {"title": "XRP", "group": "Крипта", "digits": 4,
               "src": {"binance": ("XRPUSDT", 1.0)}},
    "BNBUSD": {"title": "BNB", "group": "Крипта", "digits": 2,
               "src": {"binance": ("BNBUSDT", 1.0)}},
}

# Код валютної пари виводиться з назви, і повторювати його в таблиці
# двічі ні до чого: Dukascopy пише пару злитно, Oanda — через підкреслення.
_AUTO_CODE = {
    "dukascopy": lambda name: name,
    "oanda": lambda name: name[:3] + "_" + name[3:],
    "fxcm": lambda name: name,
}

for _name, _s in SYMBOLS.items():
    for _src, (_code, _div) in list(_s["src"].items()):
        if _code is None:
            _s["src"][_src] = (_AUTO_CODE[_src](_name), _div)


def known(symbol, source=None):
    s = SYMBOLS.get(str(symbol or "").upper())
    if not s:
        return False
    return True if source is None else source in s["src"]


def sources_of(symbol, all_=False):
    """Джерела, які тримають цей інструмент. Без `all_` — лише готові до
    роботи: те, для якого не заданий ключ, у списку не з'являється."""
    s = SYMBOLS.get(str(symbol or "").upper())
    if not s:
        return []
    return [k for k in s["src"] if all_ or source_ready(k)]


def pick_source(symbol, source=None):
    """Джерело, яким малюємо. Чуже, невимкнене або не задане — беремо
    перше доступне: людина просила графік, а не розбір того, хто з
    постачальників його не тримає."""
    if not SYMBOLS.get(str(symbol or "").upper()):
        raise ValueError("невідомий інструмент")
    have = sources_of(symbol)
    if not have:
        raise ValueError("для цього інструмента немає жодного джерела")
    return source if source in have else have[0]


def symbols():
    """Для списку в браузері: назва, підпис, група, знаки, джерела."""
    out = []
    for name, s in sorted(SYMBOLS.items(),
                          key=lambda kv: (kv[1]["group"], kv[0])):
        have = sources_of(name)
        if have:                # нічим малювати — нічого й пропонувати
            out.append({"symbol": name, "title": s["title"], "group": s["group"],
                        "digits": s["digits"], "sources": have})
    return out


def source_list():
    return [{"source": k, "title": v["title"]}
            for k, v in SOURCES.items() if source_ready(k)]


# -------------------------------------------------------------- диск ----

def _path(source, symbol, d, ext):
    return os.path.join(DIR, source, symbol, d.isoformat() + ext)


def _read_cache(source, symbol, d, ext):
    """Сирі байти, b"" для дня без торгів, None — ще не качали."""
    if os.path.exists(_path(source, symbol, d, ".none")):
        return b""
    try:
        with open(_path(source, symbol, d, ext), "rb") as f:
            return f.read()
    except OSError:
        return None


def _write_cache(source, symbol, d, ext, raw):
    """День без торгів позначаємо окремим порожнім файлом: інакше щоразу
    ходили б по мережі за суботою, якої не буде ніколи.

    Два файли на одну добу тримати не можна. Читання дивиться на позначку
    першою, тож коли поряд із нею лягали справжні свічки, їх ніхто вже не
    бачив: дані на диску є, а графік порожній. Тому, записуючи одне,
    прибираємо інше."""
    path = _path(source, symbol, d, ext)
    none = _path(source, symbol, d, ".none")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if raw:
            tmp = path + ".tmp"
            with open(tmp, "wb") as f:
                f.write(raw)
            os.replace(tmp, path)
            if os.path.exists(none):
                os.remove(none)
        else:
            with open(none, "wb"):
                pass
            if os.path.exists(path):
                os.remove(path)
    except OSError:
        pass                    # без кешу теж працює, просто повільніше


# ------------------------------------------------------------ мережа ----

def _download(source, url):
    """Сирий файл доби або b"" — торгів не було.

    Кидає FeedError, якщо джерело не відповіло: день з помилкою не можна
    запам'ятати як порожній, інакше діра в графіку лишиться назавжди."""
    src = SOURCES[source]
    left = cooling(source)
    if left:
        raise FeedError("%s не відповідає, пробуємо знову через %d с" %
                        (src.get("title", source), left))
    head = dict(UA)
    if "headers" in src:
        head.update(src["headers"]())
    pause = src.get("pause", PAUSE)
    wait = 2.0
    for attempt in range(TRIES):
        if cooling(source):
            # поки чекали між спробами, джерело визнали недоступним
            raise FeedError("%s не відповідає" % src.get("title", source))
        with _net_lock:
            gap = pause - (time.time() - _last_call.get(source, 0.0))
            if gap > 0:
                time.sleep(gap)
            _last_call[source] = time.time()
        try:
            req = urllib.request.Request(url, headers=head)
            with urllib.request.urlopen(req, timeout=10) as r:
                body = r.read()
            _note_ok(source)
            return body
        except urllib.error.HTTPError as ex:
            if ex.code in src["empty"]:
                _note_ok(source)
                return b""      # вихідний, свято або день до початку історії
            _note_fail(source)
            if attempt == TRIES - 1:
                raise FeedError("%s: %s" % (src.get("title", source), ex))
        except Exception as ex:
            _note_fail(source)
            if attempt == TRIES - 1:
                raise FeedError("%s: %s" % (src.get("title", source), ex))
        time.sleep(wait)
        wait *= 2
    return b""


def day_raw(symbol, d, source=None, fetch=True):
    symbol = str(symbol or "").upper()
    source = pick_source(symbol, source)
    ext = SOURCES[source]["ext"]
    raw = _read_cache(source, symbol, d, ext)
    if raw is not None:
        return raw
    if not fetch:
        return None
    code = SYMBOLS[symbol]["src"][source][0]
    if "bulk" in SOURCES[source]:
        # джерело віддає не добу, а пачку: воно саме розкладе її по днях
        SOURCES[source]["bulk"](source, symbol, code, d)
        raw = _read_cache(source, symbol, d, ext)
        return b"" if raw is None else raw
    raw = _download(source, SOURCES[source]["url"](code, d))
    _write_cache(source, symbol, d, ext, raw)
    return raw


# ------------------------------------------------------------ розбір ----

def minutes(symbol, d, source=None, fetch=True):
    """Хвилинні свічки доби: [(час UTC, o, h, l, c, обсяг)]."""
    symbol = str(symbol or "").upper()
    source = pick_source(symbol, source)
    raw = day_raw(symbol, d, source, fetch)
    if not raw:
        return []
    div = SYMBOLS[symbol]["src"][source][1]
    start = int(datetime.datetime(d.year, d.month, d.day,
                                  tzinfo=datetime.timezone.utc).timestamp())
    return SOURCES[source]["parse"](raw, start, div)


def fold(rows, step):
    """Хвилинки в потрібний таймфрейм. Межі рівні: 15m починається о :00,
    :15, :30 і :45 за UTC — так само, як їх малює будь-який термінал."""
    out = []
    cur = None
    for ts, o, h, l, c, v in rows:
        edge = ts - ts % step
        if cur is None or cur[0] != edge:
            if cur is not None:
                out.append(cur)
            cur = [edge, o, h, l, c, v]
        else:
            cur[2] = max(cur[2], h)
            cur[3] = min(cur[3], l)
            cur[4] = c
            cur[5] += v
    if cur is not None:
        out.append(cur)
    return out


def bars(symbol, tf, since, until, source=None, fetch=True):
    """Свічки за проміжок дат включно. `since` і `until` — datetime.date."""
    symbol = str(symbol or "").upper()
    source = pick_source(symbol, source)
    step = TF.get(tf)
    if not step:
        raise ValueError("невідомий таймфрейм")
    if until < since:
        since, until = until, since
    if (until - since).days + 1 > MAX_DAYS:
        until = since + datetime.timedelta(days=MAX_DAYS - 1)
    rows = []
    d = since
    while d <= until:
        rows.extend(minutes(symbol, d, source, fetch))
        d += datetime.timedelta(days=1)
    rows.sort()
    return fold(rows, step)


def warm(symbol, since, until, source=None, log=None):
    """Скачати проміжок наперед. Повертає (скачано, порожніх, помилок)."""
    symbol = str(symbol or "").upper()
    source = pick_source(symbol, source)
    got = empty = bad = 0
    d = since
    while d <= until:
        try:
            if day_raw(symbol, d, source):
                got += 1
            else:
                empty += 1
        except FeedError as ex:
            bad += 1
            if log:
                log("%s %s: %s" % (symbol, d, ex))
        d += datetime.timedelta(days=1)
    return got, empty, bad


def cached_days(symbol, source=None):
    """Скільки днів уже лежить на диску — для смужки готовності."""
    symbol = str(symbol or "").upper()
    source = pick_source(symbol, source)
    folder = os.path.join(DIR, source, symbol)
    try:
        return sum(1 for n in os.listdir(folder) if not n.endswith(".tmp"))
    except OSError:
        return 0

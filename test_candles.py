# -*- coding: utf-8 -*-
"""
Свічки для перемотки: python test_candles.py

Перевіряємо розбір відповідей джерел і складання хвилинок у таймфрейми —
те, що рахується без мережі й без бази. Живі джерела перевіряє окремий
прогін, він ходить у мережу й у загальний не входить:
  python test_candles.py --feed
"""
import datetime
import io
import json
import os
import struct
import sys
import zipfile

os.environ.setdefault("DATABASE_URL", "postgresql://x/y")

import candles

fails = []


def eq(got, want, what):
    if got != want:
        fails.append("%s: %r != %r" % (what, got, want))


def near(got, want, what, eps=1e-9):
    if got is None or abs(got - want) > eps:
        fails.append("%s: %r != %r" % (what, got, want))


duka = candles.SOURCES["dukascopy"]["parse"]
bnc = candles.SOURCES["binance"]["parse"]


# ------------------------------------------------- розбір Dukascopy ----

def rec(sec, o, c, l, h, vol):
    """Запис у тому ж вигляді, що у файлі фіду: час, open, close, low,
    high, обсяг — саме в такому порядку, не OHLC."""
    return struct.pack(">5if", sec, o, c, l, h, vol)


import lzma  # noqa: E402  (потрібен лише тут, щоб зібрати несправжній файл)


def duka_file(*records):
    return lzma.compress(b"".join(records))


body = duka_file(rec(0,   25550999, 25548188, 25546388, 25551999, 1.5),
                 rec(60,  25548188, 25552000, 25547000, 25553000, 2.0))
rows = duka(body, 1000000, 1000.0)
eq(len(rows), 2, "скільки хвилин")
near(rows[0][1], 25550.999, "open")
near(rows[0][2], 25551.999, "high")
near(rows[0][3], 25546.388, "low")
near(rows[0][4], 25548.188, "close")
eq(rows[0][0], 1000000, "час першої")
eq(rows[1][0], 1000060, "час другої")

for i, r in enumerate(rows):
    if not (r[2] >= max(r[1], r[4]) and r[3] <= min(r[1], r[4])):
        fails.append("свічка %d перевернута: %r" % (i, r))

# пара валют: дільник інший
pair = duka(duka_file(rec(0, 116337, 116341, 116328, 116345, 9.0)), 0, 100000.0)
near(pair[0][1], 1.16337, "ціна пари валют")

# хвилина без тіків (обсяг 0 і ціна стоїть) — не свічка, а зачинений ринок
dead = duka_file(rec(0, 100, 100, 100, 100, 0.0), rec(60, 100, 105, 99, 106, 3.0))
eq(len(duka(dead, 0, 1.0)), 1, "порожня хвилина викинута")

# а от нульовий обсяг при русі ціни лишаємо: буває на тонкому ринку
eq(len(duka(duka_file(rec(0, 100, 105, 99, 106, 0.0)), 0, 1.0)), 1,
   "рух без обсягу лишається")

# зіпсований файл не валить розбір
eq(duka(b"not lzma at all", 0, 1.0), [], "сміття замість файлу")


# --------------------------------------------------- розбір Binance ----

def bnc_file(lines):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("BTCUSDT-1m-2024-01-01.csv", "\n".join(lines))
    return buf.getvalue()


# час у мілісекундах
ms = bnc_file(["1704067200000,42000.1,42100.5,41950.0,42080.2,12.5,1704067259999,0,0,0,0,0",
               "1704067260000,42080.2,42150.0,42050.0,42100.0,8.25,1704067319999,0,0,0,0,0"])
got = bnc(ms, 0, 1.0)
eq(len(got), 2, "бінанс: скільки хвилин")
eq(got[0][0], 1704067200, "бінанс: мілісекунди в секунди")
near(got[0][1], 42000.1, "бінанс: open")
near(got[0][2], 42100.5, "бінанс: high")
near(got[0][3], 41950.0, "бінанс: low")
near(got[0][4], 42080.2, "бінанс: close")
near(got[0][5], 12.5, "бінанс: обсяг")

# той самий час у мікросекундах — біржа міняла одиниці
us = bnc_file(["1704067200000000,42000.1,42100.5,41950.0,42080.2,12.5,0,0,0,0,0,0"])
eq(bnc(us, 0, 1.0)[0][0], 1704067200, "бінанс: мікросекунди в секунди")

# заголовок, який біржа іноді кладе першим рядком, не ламає розбір
head = bnc_file(["open_time,open,high,low,close,volume,a,b,c,d,e,f",
                 "1704067200000,1,2,0.5,1.5,3,0,0,0,0,0,0"])
eq(len(bnc(head, 0, 1.0)), 1, "бінанс: заголовок пропущено")

eq(bnc(b"not a zip", 0, 1.0), [], "бінанс: сміття замість архіву")


# ----------------------------------------------------- розбір Oanda ----

oanda = candles.SOURCES["oanda"]["parse"]


def oanda_file(candles_):
    return json.dumps({"instrument": "EUR_USD", "granularity": "M1",
                       "candles": candles_}).encode("utf-8")


got = oanda(oanda_file([
    {"complete": True, "volume": 12, "time": "1704067200.000000000",
     "mid": {"o": "1.10425", "h": "1.10480", "l": "1.10400", "c": "1.10455"}},
    {"complete": True, "volume": 5, "time": "1704067260.000000000",
     "mid": {"o": "1.10455", "h": "1.10460", "l": "1.10430", "c": "1.10440"}},
]), 0, 1.0)
eq(len(got), 2, "oanda: скільки хвилин")
eq(got[0][0], 1704067200, "oanda: час числом")
near(got[0][1], 1.10425, "oanda: open")
near(got[0][2], 1.10480, "oanda: high")
near(got[0][3], 1.10400, "oanda: low")
near(got[0][4], 1.10455, "oanda: close")
near(got[0][5], 12.0, "oanda: обсяг")

# незакриту свічку в історію не беремо: її ціна ще зміниться
part = oanda(oanda_file([
    {"complete": True, "volume": 1, "time": "1704067200.0",
     "mid": {"o": "1", "h": "1", "l": "1", "c": "1"}},
    {"complete": False, "volume": 1, "time": "1704067260.0",
     "mid": {"o": "1", "h": "1", "l": "1", "c": "1"}},
]), 0, 1.0)
eq(len(part), 1, "oanda: незакрита свічка викинута")

# покалічений запис не валить весь день
eq(len(oanda(oanda_file([{"complete": True, "time": "1704067200.0", "mid": {}}]), 0, 1.0)),
   0, "oanda: запис без цін")
eq(oanda(b"<html>error</html>", 0, 1.0), [], "oanda: не json")

# без ключа джерела просто немає — ні в списку, ні у виборі
eq(candles.source_ready("oanda"), bool(candles.config.OANDA_TOKEN),
   "готовність oanda залежить від ключа")
if not candles.config.OANDA_TOKEN:
    eq([s["source"] for s in candles.source_list() if s["source"] == "oanda"], [],
       "без ключа oanda не пропонується")
    eq(candles.pick_source("EURUSD", "oanda"), "fxcm",
       "без ключа падаємо на доступне джерело")
    eq(candles.sources_of("EURUSD"), ["fxcm", "dukascopy"], "доступні джерела пари")
eq(sorted(candles.sources_of("EURUSD", all_=True)), ["dukascopy", "fxcm", "oanda"],
   "усі джерела пари, разом з невимкненими")

# коди в oanda свої: пара через підкреслення, індекс має власну назву
eq(candles.SYMBOLS["GBPUSD"]["src"]["oanda"][0], "GBP_USD", "код пари в oanda")
eq(candles.SYMBOLS["GER40"]["src"]["oanda"][0], "DE30_EUR", "код індексу в oanda")
eq(candles.SYMBOLS["BTCUSD"]["src"].get("oanda"), None, "крипти в oanda немає")

# адреса дня: рівно доба, хвилинками, серединною ціною
url = candles.SOURCES["oanda"]["url"]("EUR_USD", datetime.date(2025, 6, 11))
for part_ in ("/v3/instruments/EUR_USD/candles", "granularity=M1",
              "from=2025-06-11T00:00:00Z", "to=2025-06-12T00:00:00Z"):
    if part_ not in url:
        fails.append("адреса oanda без %r: %s" % (part_, url))


# ------------------------------------------------------ таймфрейми ----

def m(ts, o, h, l, c, v=1.0):
    return (ts, o, h, l, c, v)


mins = [m(0, 10, 12, 9, 11), m(60, 11, 15, 10, 14),
        m(120, 14, 14, 8, 9), m(180, 9, 11, 7, 10)]
got = candles.fold(mins, 300)
eq(len(got), 1, "один бар з чотирьох хвилин")
eq(got[0][0], 0, "межа бару")
near(got[0][1], 10, "open бару — з першої хвилини")
near(got[0][2], 15, "high бару — найвищий")
near(got[0][3], 7, "low бару — найнижчий")
near(got[0][4], 10, "close бару — з останньої хвилини")
near(got[0][5], 4.0, "обсяг склався")

two = candles.fold([m(240, 1, 1, 1, 1), m(300, 2, 2, 2, 2)], 300)
eq([b[0] for b in two], [0, 300], "межі п'ятихвилинок")

mid = candles.fold([m(13 * 60, 5, 5, 5, 5), m(16 * 60, 6, 6, 6, 6)], 900)
eq([b[0] for b in mid], [0, 900], "межі п'ятнадцятихвилинок")

hole = candles.fold([m(0, 1, 1, 1, 1), m(3600, 2, 2, 2, 2)], 300)
eq(len(hole), 2, "діра не створює пустих барів")
eq([b[0] for b in hole], [0, 3600], "бари по краях діри")

eq(candles.fold([], 900), [], "порожній вхід")


# --------------------------------------------------------- джерела ----

eq(candles.known("ger40"), True, "інструмент упізнається без регістру")
eq(candles.known("НЕМАЄ"), False, "чужий інструмент")
eq(candles.known("GER40", "binance"), False, "індекса в біржі немає")
eq(candles.known("BTCUSD", "binance"), True, "біткоїн у біржі є")

# крипту малюємо біржею, бо вона стоїть першою в списку джерел
eq(candles.pick_source("BTCUSD"), "binance", "джерело крипти за замовчуванням")
eq(candles.pick_source("BTCUSD", "dukascopy"), "dukascopy", "обране джерело поважаємо")
eq(candles.pick_source("BTCUSD", "немає"), "binance", "чуже джерело — беремо своє")
eq(candles.pick_source("EURUSD", "binance"), "fxcm", "валют у біржі немає")

try:
    candles.pick_source("НЕМАЄ")
    fails.append("чужий інструмент: помилки не було")
except ValueError:
    pass

# у кожного інструмента код джерела проставлений, дільник додатний
for name, s in candles.SYMBOLS.items():
    if not s["src"]:
        fails.append("%s: жодного джерела" % name)
    for src, pair_ in s["src"].items():
        if src not in candles.SOURCES:
            fails.append("%s: невідоме джерело %s" % (name, src))
        code, div = pair_
        if not code or div <= 0:
            fails.append("%s/%s: порожній код або дільник" % (name, src))
    if s["digits"] not in (2, 3, 4, 5):
        fails.append("%s: дивна кількість знаків %r" % (name, s["digits"]))

lst = candles.symbols()
eq(len({x["symbol"] for x in lst}), len(candles.SYMBOLS), "список без повторів")
digits = {x["symbol"]: x["digits"] for x in lst}
eq(digits["EURUSD"], 5, "знаків у пари валют")
eq(digits["USDJPY"], 3, "знаків у пари з єною")
eq(digits["GER40"], 3, "знаків в індексу")

# валютній парі код проставився сам, з назви
eq(candles.SYMBOLS["GBPUSD"]["src"]["dukascopy"][0], "GBPUSD", "код пари з назви")
eq(candles.SYMBOLS["GER40"]["src"]["dukascopy"][0], "DEUIDXEUR", "код індексу свій")


# ----------------------------------------------------------- решта ----

# без кешу й без мережі — порожньо, але не падає
eq(candles.bars("GER40", "15m", datetime.date(2019, 1, 1),
                datetime.date(2019, 1, 2), fetch=False), [], "немає кешу")

try:
    candles.bars("GER40", "7m", datetime.date(2025, 1, 1),
                 datetime.date(2025, 1, 2), fetch=False)
    fails.append("чужий таймфрейм: помилки не було")
except ValueError:
    pass

far = candles.bars("GER40", "1d", datetime.date(2015, 1, 1),
                   datetime.date(2030, 1, 1), fetch=False)
eq(far, [], "довгий проміжок обрізано, але не впало")


# --------------------------------------------- нумерація тижнів FXCM ----

# Пари «дата -> номер тижня», зняті живцем із самих файлів архіву: для
# кожного року брали березень, червень і жовтень і дивились, у якому
# файлі насправді лежить ця доба. Роки, де 1 січня припало на понеділок,
# вівторок чи середу, мають зсув +1 — через огризок тижня на початку
# року. Якщо колись цю поправку приберуть, половина архіву знову почне
# мовчки лягати в кеш порожніми днями, тому хай це тримає тест.
WEEKS = {
    (2012, 3, 7): 10, (2012, 6, 6): 23, (2012, 10, 3): 40,   # 1 січня — нд
    (2013, 3, 6): 10, (2013, 6, 5): 23, (2013, 10, 2): 40,   # вт, зсув
    (2014, 3, 5): 10, (2014, 6, 4): 23, (2014, 10, 1): 40,   # ср, зсув
    (2015, 3, 4): 9,  (2015, 6, 3): 22, (2015, 10, 7): 40,   # чт
    (2016, 3, 2): 9,  (2016, 6, 1): 22, (2016, 10, 5): 40,   # пт
    (2017, 3, 1): 9,  (2017, 6, 7): 23, (2017, 10, 4): 40,   # нд
    (2018, 3, 7): 10, (2018, 6, 6): 23, (2018, 10, 3): 40,   # пн, зсув
    (2019, 3, 6): 10, (2019, 6, 5): 23, (2019, 10, 2): 40,   # вт, зсув
    (2020, 3, 4): 10, (2020, 6, 3): 23, (2020, 10, 7): 41,   # ср, зсув
    (2021, 3, 3): 9,  (2021, 6, 2): 22, (2021, 10, 6): 40,   # пт
    (2022, 3, 2): 9,  (2022, 6, 1): 22, (2022, 10, 5): 40,   # сб
    (2023, 3, 1): 9,  (2023, 6, 7): 23, (2023, 10, 4): 40,   # нд
    (2024, 3, 6): 10, (2024, 6, 5): 23, (2024, 10, 2): 40,   # пн, зсув
    (2025, 3, 5): 10, (2025, 6, 4): 23, (2025, 10, 1): 40,   # ср, зсув
    (2026, 3, 4): 9,                                          # чт
}
for (yy, mm, dd), week in WEEKS.items():
    year, got = candles._fxcm_week(datetime.date(yy, mm, dd))
    eq((year, got), (yy, week), "тиждень FXCM %04d-%02d-%02d" % (yy, mm, dd))

# Доба на межі року лишається в тижні своєї неділі, а не перестрибує.
eq(candles._fxcm_week(datetime.date(2013, 1, 2))[0], 2012,
   "2 січня 2013 — ще тиждень, що почався в грудні")


# ------------------------------------------------------ живі джерела ----

def feed_check():
    """Ходить у мережу. Перевіряє головне припущення про Dukascopy: місяць
    в адресі рахується з нуля. Доказ — календар ринку: субота порожня,
    п'ятниця коротка, неділя відкривається ввечері. Плюс один день з
    біржі, щоб знати, що архіви крипти на місці."""
    bad = []
    start = datetime.date(2026, 8, 3)
    for i in range(7):
        d = start + datetime.timedelta(days=i)
        try:
            live = len(candles.minutes("EURUSD", d))
        except candles.FeedError as ex:
            # Мовчання джерела — це про мережу, а не про формат: такий день
            # просто не рахуємо, інакше перевірка падала б через чужий
            # таймаут і нічого про наші припущення не казала.
            print("  %s: джерело не відповіло, день пропущено (%s)" % (d, ex), flush=True)
            continue
        if d.weekday() == 5 and live > 10:
            bad.append("%s субота, а хвилин %d — місяць зміщений" % (d, live))
        if d.weekday() < 4 and live < 100:
            bad.append("%s %s, а хвилин лише %d" % (d, d.strftime("%a"), live))
        print("  %s %s: хвилин %d" % (d, d.strftime("%a"), live), flush=True)

    d = datetime.date(2026, 8, 5)
    try:
        live = candles.minutes("BTCUSD", d)
        print("  %s біткоїн з біржі: хвилин %d" % (d, len(live)), flush=True)
        if len(live) < 1000:
            bad.append("%s біткоїн: хвилин лише %d, а крипта торгується цілодобово"
                       % (d, len(live)))
    except candles.FeedError as ex:
        print("  біржа не відповіла, пропускаємо (%s)" % ex, flush=True)
    return bad


if "--feed" in sys.argv:
    print("жива перевірка джерел (йде в мережу):", flush=True)
    fails.extend(feed_check())

if fails:
    print("\n".join(fails))
    raise SystemExit(1)
print("усе добре")

# ------------------------------------------------------------- FXCM ----
# Тиждень у них рахується від першої неділі року, і це єдине, що легко
# зіпсувати: помилка на один тиждень дала б графік із чужими цінами.
import datetime as _dt
eq(candles._fxcm_week(_dt.date(2026, 1, 11)), (2026, 2), "тиждень fxcm: 11.01.2026")
eq(candles._fxcm_week(_dt.date(2026, 2, 1)), (2026, 5), "тиждень fxcm: 01.02.2026")
eq(candles._fxcm_week(_dt.date(2026, 9, 20)), (2026, 38), "тиждень fxcm: неділя")
eq(candles._fxcm_week(_dt.date(2026, 9, 25)), (2026, 38), "тиждень fxcm: п'ятниця тієї ж")
eq(candles._fxcm_week(_dt.date(2026, 9, 26)), (2026, 38), "тиждень fxcm: субота тієї ж")
eq(candles._fxcm_week(_dt.date(2026, 9, 27)), (2026, 39), "тиждень fxcm: наступна неділя")
eq(candles._fxcm_week(_dt.date(2026, 1, 1)), (2025, 53), "тиждень fxcm: стик років")

import gzip as _gz
_head = "DateTime,BidOpen,BidHigh,BidLow,BidClose,AskOpen,AskHigh,AskLow,AskClose"
_r1 = "09/22/2026 00:00:00.000,1.14635,1.14645,1.14634,1.14643,1.14645,1.14655,1.14644,1.14653"
_r2 = "09/22/2026 00:01:00.000,1.14643,1.14650,1.14640,1.14648,1.14653,1.14660,1.14650,1.14658"
_csv = chr(10).join([_head, _r1, _r2])
_rows = candles._fxcm_parse(_gz.compress(_csv.encode()), 0, 1.0)
eq(len(_rows), 2, "fxcm: заголовок не потрапив у свічки")
eq(_rows[0][0], 1789084800, "fxcm: час читається як UTC")
eq(_rows[0][1:5], (1.14635, 1.14645, 1.14634, 1.14643), "fxcm: малюємо по bid")
eq(candles._fxcm_parse(b"not a gzip", 0, 1.0), [], "fxcm: сміття не валить розбір")

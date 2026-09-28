# -*- coding: utf-8 -*-
"""
Одно и то же под разными именами.

Журнал часто собран из нескольких источников: два журнала Notion за разные
месяцы, файл из Excel, сделки, вбитые руками. В каждом свои привычки — где-то
«US100», где-то «NAS 100», где-то «Nasdaq». Для статистики это разные
инструменты: винрейт, профит-фактор и все разрезы делятся пополам, и заметить
это трудно — в списке просто две строки вместо одной.

Здесь мы находим такие пары. Сами ничего не меняем: сводит человек. «GER40»
и «GER 40» — одно, а «US30» и «US100» — разное, и машине эту границу видно
не всегда, поэтому последнее слово за ним.

Работает на стандартной библиотеке, как и весь app.py.
"""

import re

from notion_import import LOOKALIKE, SESSION_SAME

# Поля, по которым строится статистика: разнобой в них и разъезжается.
# Направление, результат и тип входа сюда не входят — они приводятся к
# твёрдому списку значений ещё при записи сделки.
FIELDS = ["pair", "session", "entry_model", "setup", "account"]

# Одно и то же под разными именами у разных брокеров. При записи сделки
# инструмент из группы сводится к написанию, которое уже есть в журнале
# (pair_key → db._one_spelling): «US100», «Nasdaq» и «NQ» — один актив.
# Копия этого списка для подсказок в браузере — PAIR_SAME в static/app.js.
SAME = [
    {"US100", "NAS100", "NASDAQ", "NASDAQ100", "USTEC", "NDX", "NQ", "MNQ", "NAS", "US100CASH",
     "NAS100USD", "USTECH", "USTECH100"},
    {"US30", "DJI", "DOW", "DOWJONES", "US30CASH", "YM", "MYM", "DJ30", "WS30"},
    {"US500", "SPX", "SP500", "SPX500", "ES", "ES500", "MES", "US500CASH", "SPX500USD", "SNP500", "SANDP500"},
    {"GER40", "GER30", "DAX", "DAX40", "DE40", "DE30", "GER40CASH", "FDAX"},
    {"XAUUSD", "XAU", "GOLD", "ЗОЛОТО", "ЗОЛОТА", "GC", "MGC"},
    {"XAGUSD", "XAG", "SILVER", "СРІБЛО", "СЕРЕБРО"},
    {"UK100", "FTSE", "FTSE100"},
    {"JP225", "NIKKEI", "NIKKEI225", "JPN225"},
    {"US2000", "RUSSELL", "RUSSELL2000", "RTY", "M2K"},
    {"BTCUSD", "BTCUSDT", "BITCOIN", "XBTUSD", "BTC"},
    {"ETHUSD", "ETHUSDT", "ETHEREUM", "ETH"},
    {"USOIL", "WTI", "CRUDE", "CL", "XTIUSD"},
]

_JUNK = re.compile(r"[^0-9A-Za-zА-Яа-яЁёІіЇїЄєҐґ]+")


def _plain(value):
    """Написание без пробелов, дефисов и регистра. Кириллические двойники
    латинских букв меняем на латиницу: «USD\\САD» оком не отличить."""
    s = str(value if value is not None else "").strip()
    if not s:
        return ""
    s = "".join(LOOKALIKE.get(ch, ch) for ch in s)
    return _JUNK.sub("", s).upper()


# написание -> к какому имени группы его свести. Собираем через _plain,
# чтобы слова из таблиц прошли ту же обработку, что и значения из журнала.
SYN = {}
for _group in SAME:
    _canon = sorted(_group)[0]
    for _w in _group:
        SYN[_plain(_w)] = _canon
# Только инструменты, без сессий: ключ для поля «Инструмент» при записи.
PAIR_SYN = dict(SYN)
for _bad, _good in SESSION_SAME.items():
    SYN[_plain(_bad)] = _plain(_good)


# Версия списка: сменилась — старые сделки при старте сводятся заново
# (app.py: _pairs_init).
SAME_VERSION = "2"


def _pieces(value):
    """Куски названия, по которым можно узнать актив, если целиком оно
    незнакомо: «Nasdaq (NQ)» → NASDAQ, NQ; «SPX 500 (ES)» → SPX, 500,
    SPX500, ES. Отдельно текст до скобок, в скобках, слова и пары
    соседних слов."""
    s = "".join(LOOKALIKE.get(ch, ch) for ch in str(value if value is not None else ""))
    chunks = [re.sub(r"\(.*?\)", " ", s)] + re.findall(r"\((.*?)\)", s)
    out = []
    for c in chunks:
        toks = [t.upper() for t in _JUNK.split(c) if t]
        out.append("".join(toks))
        out += toks
        out += [a + b for a, b in zip(toks, toks[1:])]
    return [o for o in out if o]


# Приписки брокера, которые актив не меняют: «US100.cash», «XAU spot».
NOISE = {"CASH", "SPOT", "CFD", "FUT", "FUTURES", "INDEX", "IDX", "ECN", "RAW",
         "M", "C", "PRO", "PLUS"}


def _by_pieces(value, table):
    """Имя группы по кускам — только если все узнанные куски указывают на
    одну и ту же группу. «US30 (Dow)» → US30; «US30/US100» — спор, не сводим.

    И только если незнакомых слов нет: «XAU MSNR» — это человек так назвал
    свой инструмент (актив + модель), а не просто золото. Раньше такое
    сводилось в «XAU», и своё название у человека пропадало."""
    s = "".join(LOOKALIKE.get(ch, ch) for ch in str(value if value is not None else ""))
    chunks = [re.sub(r"\(.*?\)", " ", s)] + re.findall(r"\((.*?)\)", s)
    for c in chunks:
        toks = [t.upper() for t in _JUNK.split(c) if t]
        if "".join(toks) in table:
            continue
        for i, t in enumerate(toks):
            near = toks[i - 1] + t if i else ""
            nxt = t + toks[i + 1] if i + 1 < len(toks) else ""
            if not (t in table or t in NOISE or near in table or nxt in table):
                return None
    hits = {table[p] for p in _pieces(value) if p in table}
    return hits.pop() if len(hits) == 1 else None


def plain(value):
    """Ключ написания: регистр, пробелы и знаки. Без сведения синонимов.

    «ger 40», «GER 40» и «GER40» сходятся в одно, а «USTEC» и «NAS100»
    остаются разными.
    """
    return _plain(value)


def pair_key(value):
    """Ключ инструмента при записи сделки (db.py): регистр, пробелы, знаки
    и известные имена одного актива. «US 100», «Nasdaq», «NQ» и «USTEC»
    сходятся в одно, «US30» и «US100» — нет.

    Владелец журнала сказал 18.09.2026: «US100», «NASDAQ» и «NQ» в статистике
    должны быть одним активом, а не тремя. Раньше синонимы только
    подсказывались в окне сведения, и новые сделки продолжали расползаться.
    """
    k = _plain(value)
    if not k:
        return ""
    return PAIR_SYN.get(k) or _by_pieces(value, PAIR_SYN) or k


def key(value):
    """Ключ, по которому два написания считаются одним именем.

    «NAS 100», «nas-100» и «НАС100» сходятся в одно, «US30» и «US100» — нет.
    Сверх этого сводим известные имена одного и того же инструмента.
    """
    k = _plain(value)
    return SYN.get(k, k) if k else ""


def same_trade_key(t):
    """Отпечаток сделки: день, инструмент, направление, результат и время.

    Нужен, когда одна и та же сделка записана в двух журналах: `notion_id`
    у них разные, по нему не узнать. Инструмент берём приведённый к общему
    имени — иначе «US100» и «NAS 100» останутся разными сделками.

    Время добавляем, только если оно есть: в журналах его часто не ставят,
    и тогда сравниваем по дню. Из-за этого два разных входа в один день на
    одном инструменте в одну сторону с одним исходом выглядят одинаково —
    поэтому считаем их количество, а не просто наличие (см. `prints`).
    """
    date = str(t.get("date") or "").strip()
    day, _, time = date.partition("T")
    if not day or not str(t.get("pair") or "").strip():
        return ""
    return "|".join([day, pair_key(t.get("pair")),
                     _plain(t.get("position")), _plain(t.get("result")),
                     time[:5] if time[:5] not in ("", "00:00") else ""])


def prints(trades):
    """Сколько сделок с каждым отпечатком уже лежит в журнале.

    Считаем именно количество: если человек за день сделал три одинаковых
    входа, второй перенос той же базы должен пропустить все три, а база,
    где их пять, — добавить два недостающих.
    """
    out = {}
    for t in trades:
        k = same_trade_key(t)
        if k:
            out[k] = out.get(k, 0) + 1
    return out


def scan(trades, fields=None):
    """Группы «одно и то же под разными именами».

    Возвращаем [{field, variants:[{value, count}], best}] — от самой крупной
    группы к мелким. Группа из одного написания не группа: её не показываем.
    """
    out = []
    for field in (fields or FIELDS):
        seen = {}          # ключ -> {написание: сколько сделок}
        for t in trades:
            val = str(t.get(field) or "").strip()
            k = key(val)
            if not k:
                continue
            seen.setdefault(k, {})
            seen[k][val] = seen[k].get(val, 0) + 1
        for k, spellings in seen.items():
            if len(spellings) < 2:
                continue
            variants = [{"value": v, "count": n} for v, n in spellings.items()]
            # самое частое написание считаем главным: скорее всего им и ведут
            variants.sort(key=lambda x: (-x["count"], x["value"]))
            out.append({"field": field, "key": k, "best": variants[0]["value"],
                        "variants": variants,
                        "total": sum(x["count"] for x in variants)})
    out.sort(key=lambda g: -g["total"])
    return out

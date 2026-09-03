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
FIELDS = ["pair", "session", "entry_model", "setup"]

# Одно и то же под разными именами у разных брокеров. Это подсказка, а не
# правило: показываем группу человеку, а сводить или нет — решает он.
SAME = [
    {"US100", "NAS100", "NASDAQ", "NASDAQ100", "USTEC", "NDX", "NQ"},
    {"US30", "DJI", "DOW", "DOWJONES", "US30CASH", "YM"},
    {"US500", "SPX", "SP500", "SPX500", "ES"},
    {"GER40", "GER30", "DAX", "DAX40"},
    {"XAUUSD", "GOLD", "ЗОЛОТО", "ЗОЛОТА"},
    {"XAGUSD", "SILVER", "СРІБЛО"},
    {"UK100", "FTSE", "FTSE100"},
    {"JP225", "NIKKEI", "NIKKEI225"},
    {"BTCUSD", "BTCUSDT", "BITCOIN", "XBTUSD"},
    {"ETHUSD", "ETHUSDT", "ETHEREUM"},
    {"USOIL", "WTI", "CRUDE", "CL"},
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
for _bad, _good in SESSION_SAME.items():
    SYN[_plain(_bad)] = _plain(_good)


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
    return "|".join([day, key(t.get("pair")),
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

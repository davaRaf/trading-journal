# -*- coding: utf-8 -*-
"""
Разбор журнала из Notion: угадывание колонок, приведение значений,
загрузка картинок и учёт хода переноса.

Само чтение Notion живёт в notion_public.py — оно ходит по обычной публичной
ссылке, без ключей и интеграций. Здесь только то, что от источника не зависит.

Работает на стандартной библиотеке, как и весь app.py.
"""

import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request

UA = "StatsAI/1.0"

MAX_SHOT = 12 * 1024 * 1024      # скриншот тяжелее 12 МБ не тянем
NET_TIMEOUT = 30


class NotionError(Exception):
    pass


# --------------------------------------------------------- угадывание колонок

FIELDS = ["date", "pair", "position", "bias", "direction_type", "entry_model",
          "setup", "session", "result", "rr", "risk", "entry_details",
          "notes", "mistakes", "comments"]

LABELS = {
    "date": "Дата", "pair": "Інструмент", "position": "Напрямок", "bias": "Біас",
    "direction_type": "Продовження / Розворот", "entry_model": "Модель входу",
    "setup": "Сетап", "session": "Сесія", "result": "Результат", "rr": "RR",
    "risk": "Ризик, %", "entry_details": "Деталі входу", "notes": "Нотатки",
    "mistakes": "Помилки", "comments": "Коментар",
}

# Слова, по которым узнаём колонку. Три языка, потому что журналы ведут
# кто на чём: украинский, русский, английский.
HINTS = {
    "date":           ["date", "дата", "day", "день", "коли", "когда", "time", "час"],
    "pair":           ["pair", "asset", "instrument", "symbol", "ticker", "market",
                       "інструмент", "актив", "пара", "символ", "інструменти"],
    "position":       ["position", "direction", "side", "long", "short", "напрям",
                       "направл", "позиц", "сторона", "buy", "sell", "тип угоди",
                       "тип сделки"],
    "bias":           ["bias", "біас", "биас", "ухил", "напрямок дня"],
    "direction_type": ["continuation", "reversal", "розворот", "продовж", "разворот",
                       "тип входу", "тип входа", "trade type"],
    "entry_model":    ["model", "модель", "entry model", "патерн", "паттерн", "pattern"],
    "setup":          ["setup", "сетап", "сетапи", "стратег", "strategy", "план"],
    "session":        ["session", "сесі", "сесія", "сессия", "killzone", "kill zone"],
    "result":         ["result", "outcome", "результат", "підсумок", "итог", "статус",
                       "status", "tp/sl", "win", "profit"],
    "rr":             ["rr", "r:r", "r/r", "risk reward", "risk/reward", "співвідношення",
                       "соотношение", "reward"],
    "risk":           ["risk", "ризик", "риск", "risk %", "risk%"],
    "entry_details":  ["entry", "вхід", "вход", "деталі", "детали", "причина", "reason",
                       "why", "опис", "описание"],
    "notes":          ["note", "нотат", "заметк", "замітк", "висновок", "вывод",
                       "lesson", "урок", "journal", "щоденник"],
    "mistakes":       ["mistake", "error", "помилк", "ошибк", "fail"],
    "comments":       ["comment", "коментар", "комментар", "note to self", "думки",
                       "прочее", "інше", "разное", "додатково"],
}

NUMERIC = ("number", "formula", "rollup")


def guess_mapping(props):
    """
    props: {"Имя колонки": "тип"}.
    Возвращает {наше_поле: "Имя колонки"} — то, что удалось узнать.
    Каждую колонку отдаём максимум одному полю: побеждает лучший счёт.
    """
    scored = []
    for field in FIELDS:
        for name, ptype in props.items():
            s = _score(field, name, ptype)
            if s > 0:
                scored.append((s, field, name))
    scored.sort(reverse=True)

    out, used_field, used_col = {}, set(), set()
    for _, field, name in scored:
        if field in used_field or name in used_col:
            continue
        out[field] = name
        used_field.add(field)
        used_col.add(name)

    # Инструмент почти всегда в заголовке страницы, даже если назван иначе
    if "pair" not in out:
        for name, ptype in props.items():
            if ptype == "title" and name not in used_col:
                out["pair"] = name
                break
    return out


def _score(field, name, ptype):
    low = re.sub(r"[_\s]+", " ", str(name).strip().lower())
    best = 0
    for hint in HINTS[field]:
        if low == hint:
            best = max(best, 100)
        elif low.startswith(hint) or low.endswith(hint):
            best = max(best, 70)
        elif hint in low:
            best = max(best, 50)
    if not best:
        return 0
    # тип колонки подтверждает или опровергает догадку
    if field == "date":
        best += 25 if ptype in ("date", "created_time") else -40
    elif field in ("rr", "risk"):
        best += 20 if ptype in NUMERIC else -5
    elif field in ("entry_details", "notes", "mistakes", "comments"):
        best += 10 if ptype in ("rich_text", "title") else -5
    elif field in ("pair", "position", "result", "session", "bias",
                   "direction_type", "entry_model", "setup"):
        best += 10 if ptype in ("select", "status", "title", "rich_text", "multi_select") else -5
    return best


# ------------------------------------------------------- приведение значений

LONG = ("long", "лонг", "buy", "покупка", "купівля", "bull", "up", "вверх", "вгору")
SHORT = ("short", "шорт", "sell", "продажа", "продаж", "bear", "down", "вниз")

RESULTS = [
    (("be+", "be +", "беззбиток+", "безубыток+", "бу+"), "BE+"),
    (("be-", "be -", "беззбиток-", "безубыток-", "бу-"), "BE-"),
    (("be", "breakeven", "break even", "беззбиток", "безубыток", "бу", "нуль", "ноль"), "BE+"),
    (("win", "tp", "take", "profit", "прибуток", "прибыль", "тейк", "плюс", "+"), "Win"),
    (("loss", "sl", "stop", "збиток", "убыток", "стоп", "мінус", "минус", "-"), "Loss"),
]


def norm_side(v):
    low = str(v or "").strip().lower()
    if not low:
        return ""
    if any(w in low for w in LONG):
        return "Long"
    if any(w in low for w in SHORT):
        return "Short"
    return str(v).strip()


def norm_result(v):
    low = str(v or "").strip().lower()
    if not low:
        return ""
    for words, val in RESULTS:
        if low in words:
            return val
    for words, val in RESULTS:
        if any(w in low for w in words if len(w) > 1):
            return val
    return str(v).strip()


def norm_dirtype(v):
    low = str(v or "").strip().lower()
    if not low:
        return ""
    if any(w in low for w in ("continu", "продовж", "продолж", "трен")):
        return "Continuation"
    if any(w in low for w in ("revers", "розворот", "разворот", "контр")):
        return "Reversal"
    return str(v).strip()


def norm_num(v):
    """Число из чего угодно: 2.2 · «2,2» · «1:2.2» · «1.5 %» · «RR 3»."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(",", ".")
    if ":" in s:                       # запись вида 1:2.5 — берём вторую часть
        s = s.split(":")[-1]
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    return float(m.group(0)) if m else None


def norm_date(v):
    """Приводим к нашему виду YYYY-MM-DDTHH:MM."""
    s = str(v or "").strip()
    if not s:
        return ""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?", s)
    if m:
        d = "%s-%s-%s" % (m.group(1), m.group(2), m.group(3))
        return d + "T" + (m.group(4) + ":" + m.group(5) if m.group(4) else "00:00")
    m = re.match(r"^(\d{1,2})[./](\d{1,2})[./](\d{4})(?:[ T](\d{1,2}):(\d{2}))?", s)
    if m:
        d = "%s-%02d-%02d" % (m.group(3), int(m.group(2)), int(m.group(1)))
        return d + "T" + ("%02d:%s" % (int(m.group(4)), m.group(5)) if m.group(4) else "00:00")
    return ""


NORMALIZE = {
    "date": norm_date, "position": norm_side, "bias": norm_side,
    "result": norm_result, "direction_type": norm_dirtype,
    "rr": norm_num, "risk": norm_num,
}


# ---------------------------------------------------------------- скриншоты

TF_RE = re.compile(r"(?<![0-9a-zA-Z])(1m|3m|5m|15m|30m|1h|4h|1d|1w)(?![0-9a-zA-Z])", re.I)
TF_CANON = {"1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m",
            "1h": "1H", "4h": "4H", "1d": "1D", "1w": "1W"}


def guess_tf(*parts):
    for p in parts:
        m = TF_RE.search(str(p or ""))
        if m:
            return TF_CANON[m.group(1).lower()]
    return ""


def download(url, dest_dir, base):
    """Тянем картинку к себе. Ссылки Notion живут около часа, поэтому
       откладывать загрузку нельзя — качаем прямо во время импорта."""
    req = urllib.request.Request(url)
    req.add_header("User-Agent", UA)
    with urllib.request.urlopen(req, timeout=NET_TIMEOUT) as r:
        ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip()
        data = r.read(MAX_SHOT + 1)
    if len(data) > MAX_SHOT:
        raise NotionError("картинка завелика")
    ext = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp",
           "image/gif": "gif"}.get(ctype)
    if not ext:
        path = urllib.parse.urlparse(url).path.lower()
        m = re.search(r"\.(png|jpe?g|webp|gif)$", path)
        ext = (m.group(1).replace("jpeg", "jpg") if m else "png")
    name = "%s.%s" % (base, ext)
    with open(os.path.join(dest_dir, name), "wb") as f:
        f.write(data)
    return name


# ------------------------------------------------------------------- прогресс

class Job(object):
    """Импорт идёт в фоне: полтысячи сделок со скриншотами — это минуты,
       столько браузер ждать не станет."""

    def __init__(self, jid):
        self.id = jid
        self.state = "running"     # running · done · error
        self.step = "готуємось"
        self.done = 0
        self.total = 0
        self.added = 0
        self.skipped = 0
        self.shots = 0
        self.new_assets = []
        self.warnings = []
        self.error = ""

    def snapshot(self):
        return {"id": self.id, "state": self.state, "step": self.step,
                "done": self.done, "total": self.total, "added": self.added,
                "skipped": self.skipped, "shots": self.shots,
                "newAssets": self.new_assets, "warnings": self.warnings[:20],
                "error": self.error}

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


def guess_mapping(props, values=None):
    """
    props:  {"Имя колонки": "тип"}
    values: {"Имя колонки": [значения из первых строк]} — необязательно.

    Возвращает {наше_поле: "Имя колонки"}.

    Сначала пробуем по названию. Названия у всех свои: «Направление», «Side»,
    «Куда», «Name» — словарь всё не покроет. Поэтому дальше смотрим на сами
    значения: если в колонке лежит Win/Loss/BE — это результат, как бы она
    ни называлась. Так работает на любом языке и с любыми заголовками.
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

    # Инструмент почти всегда в заголовке страницы, даже если назван иначе.
    # Занимаем колонку до разбора по значениям, иначе длинный заголовок
    # успеет уехать в «Коментар».
    if "pair" not in out:
        for name, ptype in props.items():
            if ptype == "title" and name not in used_col:
                out["pair"] = name
                used_col.add(name)
                break

    # Что не узнали по названию — узнаём по содержимому
    if values:
        infer_by_values(out, used_col, props, values)
    return out


# ------------------------------------------------------ узнавание по значениям

def _share(vals, test):
    """Доля значений, подходящих под проверку. Пустые не считаем."""
    vals = [str(v).strip() for v in vals if str(v if v is not None else "").strip()]
    if len(vals) < 2:
        return 0.0, 0
    return sum(1 for v in vals if test(v)) / float(len(vals)), len(vals)


# LONG и SHORT объявлены ниже, поэтому собираем набор при вызове
def _side_words():
    return set(LONG) | set(SHORT)

_RES_WORDS = {"win", "loss", "be", "be+", "be-", "tp", "sl", "тейк", "стоп",
              "прибуток", "прибыль", "збиток", "убыток", "беззбиток", "безубыток",
              "бу", "бу+", "бу-", "профит", "лось"}
_DIR_WORDS = {"continuation", "reversal", "продовження", "розворот",
              "продолжение", "разворот", "cont", "rev"}
_SESSIONS = {"london", "ny", "new york", "newyork", "asia", "asian", "tokyo",
             "frankfurt", "sydney", "лондон", "нью-йорк", "азия", "азія",
             "франкфурт", "токио", "ph", "pm", "am", "premarket", "pre-market"}

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}|^\d{1,2}[./]\d{1,2}[./]\d{2,4}")
_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9]{1,9}([./][A-Z0-9]{1,6})?$")
# просто число: 2.2 · «1,5 %» · 3. Дату сюда не пускаем, иначе год уедет в RR.
_NUM_RE = re.compile(r"^-?\d+(?:[.,]\d+)?\s*%?$")


def _num(v):
    try:
        return norm_num(v)
    except Exception:
        return None


def _plain_num(v):
    return bool(_NUM_RE.match(str(v).strip())) and not _DATE_RE.match(str(v).strip())


def _checks():
    """Как выглядят значения каждого поля. По этому и узнаём, и проверяем."""
    low = lambda v: str(v).strip().lower()
    sides = _side_words()
    return {
        "date":           lambda v: bool(_DATE_RE.match(str(v).strip())),
        "result":         lambda v: low(v) in _RES_WORDS,
        "position":       lambda v: low(v) in sides,
        "bias":           lambda v: low(v) in sides,
        "direction_type": lambda v: low(v) in _DIR_WORDS,
        "session":        lambda v: low(v) in _SESSIONS,
        "rr":             _plain_num,
        "risk":           _plain_num,
    }


def infer_by_values(out, used_col, props, values):
    """
    Дописываем сопоставление, глядя на содержимое колонок.

    Сначала проверяем то, что угадали по названию: если в колонке «Час» лежат
    LONDON и NY, то это не дата, как бы она ни называлась — такую догадку
    отменяем и колонку освобождаем. Потом добираем недостающее по значениям.
    """
    checks = _checks()
    low = lambda v: str(v).strip().lower()
    sides = _side_words()

    # 1. Отменяем догадки, которым содержимое противоречит
    for field, test in checks.items():
        col = out.get(field)
        if not col or col not in values:
            continue
        share, n = _share(values[col], test)
        if n and share < 0.5:
            del out[field]
            used_col.discard(col)

    free = [c for c in values if c not in used_col]

    def take(field, col):
        if not col or field in out or col in used_col:
            return
        out[field] = col
        used_col.add(col)
        if col in free:
            free.remove(col)

    def best(test, need=0.6):
        found, score = None, need
        for c in list(free):
            share, n = _share(values[c], test)
            if n and share >= score:
                found, score = c, share
        return found

    # 2. Однозначные наборы значений. Сесію ищем раньше дати: колонка «Час»
    #    с LONDON внутри — это сесія, а не дата.
    take("result", best(checks["result"]))
    take("direction_type", best(checks["direction_type"]))
    take("session", best(checks["session"]))
    take("date", best(checks["date"]))

    # Long/Short встречается дважды: напрямок и біас. Первым берём напрямок.
    for _ in range(2):
        col = best(lambda v: low(v) in sides)
        if not col:
            break
        take("position" if "position" not in out else "bias", col)

    # Инструмент: короткие заглавные тикеры
    take("pair", best(lambda v: bool(_TICKER_RE.match(str(v).strip())), 0.7))

    # Числа: где значения крупнее — это RR, где мельче — риск
    nums = []
    for c in list(free):
        vals = [_num(v) for v in values[c] if _plain_num(v)]
        filled = [x for x in values[c] if str(x if x is not None else "").strip()]
        vals = [v for v in vals if v is not None]
        if len(vals) >= 2 and filled and len(vals) >= len(filled) * 0.6:
            mean = sum(vals) / len(vals)
            if 0.05 <= mean <= 50:
                nums.append((mean, c))
    nums.sort(reverse=True)
    if nums:
        take("rr", nums[0][1])
    if len(nums) > 1:
        take("risk", nums[1][1])

    # Длинный текст: сначала деталі входу, потім нотатки й коментар
    texts = []
    for c in list(free):
        vals = [str(v).strip() for v in values[c] if str(v if v is not None else "").strip()]
        if vals:
            avg = sum(len(v) for v in vals) / float(len(vals))
            if avg >= 25:
                texts.append((avg, c))
    texts.sort(reverse=True)
    for field, (_avg, col) in zip(["entry_details", "notes", "comments"], texts):
        take(field, col)


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
        best += 10 if ptype in ("select", "status", "title", "rich_text",
                               "multi_select", "relation") else -5
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


# Кириллические двойники латинских букв. В тикере их не видно глазом,
# но «USD\САD» с кириллическими С и А — это уже другой инструмент.
LOOKALIKE = {"А":"A","В":"B","Е":"E","К":"K","М":"M","Н":"H","О":"O","Р":"P",
             "С":"C","Т":"T","У":"Y","Х":"X","І":"I","Ї":"I","а":"a","е":"e",
             "о":"o","р":"p","с":"c","у":"y","х":"x","і":"i"}

# Хвосты вида «(1)», «(2)», «#3» и одиночная цифра через пробел.
# Двузначное число без скобок не трогаем: «GER 40» — это название, а не копия.
PAIR_TAIL = re.compile(r"\s*[\(\[]\s*\d{1,2}\s*[\)\]]\s*$|\s+#\d{1,2}\s*$|\s+\d\s*$")
TICKER_LIKE = re.compile(r"^[A-Za-z0-9./\-]{2,12}$")


def norm_pair(v):
    """
    Инструмент к одному виду.

    В Notion один и тот же актив нередко записан как «US100», «US100 (1)»
    и «US100 (2)». Для статистики это три разных инструмента: и разрезы,
    и профит-фактор, и всё остальное разъезжается на ровном месте.
    Поэтому хвост убираем, кириллические двойники чиним, обратный слэш
    приводим к прямому.
    """
    s = str(v if v is not None else "").strip()
    if not s:
        return ""
    s = s.replace("\\", "/")
    s = re.sub(r"\s+", " ", s)
    prev = None
    while prev != s:                      # «US100 (1) (2)» тоже встречается
        prev = s
        s = PAIR_TAIL.sub("", s).strip()
    # Двойники меняем, только если из этого выходит тикер. Иначе испортим
    # обычное слово: «Bitcoin спот» стало бы «Bitcoin cпoт».
    swapped = "".join(LOOKALIKE.get(ch, ch) for ch in s)
    if TICKER_LIKE.match(swapped):
        s = swapped
    return s.upper() if TICKER_LIKE.match(s) else s


# Одна сесія під двома іменами — те саме, що один інструмент під двома:
# статистика розповзається. «NEW YORK» і «NY» у журналі власника прийшли
# з різних таблиць Notion.
SESSION_SAME = {
    "NEW YORK": "NY", "NEWYORK": "NY", "NEW-YORK": "NY", "НЬЮ-ЙОРК": "NY",
    "LONDON OPEN": "LONDON", "ЛОНДОН": "LONDON", "ФРАНКФУРТ": "FRANKFURT",
    "FRANKFURT OPEN": "FRANKFURT", "ASIA": "ASIA", "АЗІЯ": "ASIA", "АЗИЯ": "ASIA",
    "POWER HOUR": "PH",
}


def norm_session(v):
    """Сесію зводимо до великих літер і до одного імені."""
    s = re.sub(r"\s+", " ", str(v if v is not None else "").strip())
    if not s:
        return ""
    up = s.upper()
    return SESSION_SAME.get(up, up if len(up) <= 14 else s)


NORMALIZE = {
    "pair": norm_pair,
    "session": norm_session,
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
        # тем же ключом помечаем перенесённые сделки: по нему потом
        # можно отменить всё перенесение одним движением
        self.batch = jid
        self.state = "running"     # running · done · error
        self.step = "готуємось"
        self.done = 0
        self.total = 0
        self.added = 0
        self.skipped = 0
        self.similar = 0           # похоже на уже записанную сделку из другого журнала
        self.shots = 0
        self.new_assets = []
        self.warnings = []
        self.error = ""

    def snapshot(self):
        return {"id": self.id, "batch": self.batch, "state": self.state, "step": self.step,
                "done": self.done, "total": self.total, "added": self.added,
                "skipped": self.skipped, "similar": self.similar, "shots": self.shots,
                "newAssets": self.new_assets, "warnings": self.warnings[:20],
                "error": self.error}

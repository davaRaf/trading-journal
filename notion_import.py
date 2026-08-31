# -*- coding: utf-8 -*-
"""
Перенос журнала из Notion.

Задача: человек уже год ведёт журнал в Notion, и руками переносить сюда
двести сделок он не будет. Поэтому здесь всё, что нужно, чтобы забрать
базу целиком — строки, заметки со страниц и скриншоты.

Работает только на стандартной библиотеке, как и весь app.py.

Как это устроено по шагам:
  1. connect  — проверяем ключ доступа, запоминаем его на сервере
  2. databases— показываем базы, к которым человек дал доступ
  3. preview  — сами угадываем, какая колонка чем является, и показываем 5 строк
  4. run      — качаем всё в фоне, отдавая прогресс

Ключ доступа наружу не отдаём никогда: он лежит в data/notion.json
и в браузер не возвращается.
"""

import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

API = os.environ.get("NOTION_API", "https://api.notion.com/v1")
VERSION = "2022-06-28"
UA = "StatsAI/1.0"

# Notion не любит больше трёх обращений в секунду — держим паузу сами,
# иначе он начинает отвечать 429 и импорт разваливается на середине.
MIN_GAP = 0.34
MAX_SHOT = 12 * 1024 * 1024      # скриншот тяжелее 12 МБ не тянем
NET_TIMEOUT = 30


class NotionError(Exception):
    pass


_last_call = [0.0]
_gap_lock = threading.Lock()


def _throttle():
    with _gap_lock:
        wait = MIN_GAP - (time.time() - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.time()


def _req(token, method, path, body=None, tries=3):
    # Ключ уходит в заголовок, а туда можно только латиницу. Проверяем сами,
    # иначе вместо понятного текста человек увидит ошибку кодировки.
    try:
        str(token).encode("ascii")
    except Exception:
        raise NotionError("у ключі є зайві символи — скопіюй його з Notion ще раз")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    for attempt in range(tries):
        _throttle()
        req = urllib.request.Request(API + path, data=data, method=method)
        req.add_header("Authorization", "Bearer " + token)
        req.add_header("Notion-Version", VERSION)
        req.add_header("User-Agent", UA)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=NET_TIMEOUT) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            try:
                msg = json.loads(raw).get("message") or raw
            except Exception:
                msg = raw
            if e.code == 429 and attempt < tries - 1:
                time.sleep(float(e.headers.get("Retry-After") or 1) + 0.5)
                continue
            raise NotionError(_human(e.code, msg))
        except Exception as ex:
            if attempt < tries - 1:
                time.sleep(1.5)
                continue
            raise NotionError("немає зв'язку з Notion: %s" % ex)


def _human(code, msg):
    if code == 401:
        return "ключ не підходить — перевір, чи скопійований повністю"
    if code == 403:
        return "ключ є, але доступу до цієї сторінки немає — поділись базою з інтеграцією"
    if code == 404:
        return "Notion не бачить цю базу. Найчастіше — база не розшарена інтеграції"
    if code == 429:
        return "Notion просить зачекати — забагато запитів. Спробуй за хвилину"
    return "Notion відповів помилкою (%s): %s" % (code, msg)


# ---------------------------------------------------------------- подключение

def whoami(token):
    me = _req(token, "GET", "/users/me")
    bot = me.get("bot") or {}
    ws = bot.get("workspace_name") or ""
    return {"name": me.get("name") or "інтеграція", "workspace": ws}


def databases(token):
    """Базы, к которым интеграции дали доступ."""
    out, cursor = [], None
    while True:
        body = {"filter": {"value": "database", "property": "object"}, "page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        res = _req(token, "POST", "/search", body)
        for db in res.get("results", []):
            props = db.get("properties") or {}
            out.append({
                "id": db.get("id"),
                "title": _plain(db.get("title") or []) or "без назви",
                "props": {k: (v or {}).get("type", "") for k, v in props.items()},
            })
        if not res.get("has_more"):
            break
        cursor = res.get("next_cursor")
    return out


# ------------------------------------------------------------ чтение значений

def _plain(rich):
    return "".join(x.get("plain_text", "") for x in (rich or []))


def prop_value(p):
    """Значение свойства Notion в понятном нам виде. Тип может быть любым."""
    if not isinstance(p, dict):
        return ""
    t = p.get("type") or ""
    if t in ("title", "rich_text"):
        return _plain(p.get(t))
    if t == "select":
        return (p.get("select") or {}).get("name", "")
    if t == "status":
        return (p.get("status") or {}).get("name", "")
    if t == "multi_select":
        return ", ".join(x.get("name", "") for x in p.get("multi_select") or [])
    if t == "number":
        return p.get("number")
    if t == "date":
        d = p.get("date") or {}
        return d.get("start") or ""
    if t == "checkbox":
        return "так" if p.get("checkbox") else ""
    if t in ("url", "email", "phone_number"):
        return p.get(t) or ""
    if t == "people":
        return ", ".join(x.get("name", "") for x in p.get("people") or [])
    if t in ("created_time", "last_edited_time"):
        return p.get(t) or ""
    if t == "unique_id":
        u = p.get("unique_id") or {}
        return "%s%s" % (u.get("prefix") or "", u.get("number") or "")
    if t == "formula":
        f = p.get("formula") or {}
        return prop_value({"type": f.get("type"), f.get("type"): f.get(f.get("type"))})
    if t == "rollup":
        r = p.get("rollup") or {}
        if r.get("type") == "array":
            return ", ".join(str(prop_value(x)) for x in r.get("array") or [])
        return prop_value({"type": r.get("type"), r.get("type"): r.get(r.get("type"))})
    if t == "files":
        return ", ".join(_file_urls(p))
    return ""


def _file_urls(p):
    out = []
    for f in p.get("files") or []:
        if f.get("type") == "file":
            u = (f.get("file") or {}).get("url")
        else:
            u = (f.get("external") or {}).get("url")
        if u:
            out.append(u)
    return out


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


def map_row(page, mapping):
    """Строка Notion -> наша сделка (без скриншотов и текста страницы)."""
    props = page.get("properties") or {}
    t = {"notion_id": page.get("id") or ""}
    for field in FIELDS:
        col = mapping.get(field)
        raw = prop_value(props.get(col)) if col else ""
        fn = NORMALIZE.get(field)
        val = fn(raw) if fn else (str(raw).strip() if raw is not None else "")
        t[field] = val
    return t


# ------------------------------------------------------------- чтение страниц

def rows(token, db_id, limit=None):
    out, cursor = [], None
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        res = _req(token, "POST", "/databases/%s/query" % db_id, body)
        out.extend(res.get("results", []))
        if limit and len(out) >= limit:
            return out[:limit]
        if not res.get("has_more"):
            return out
        cursor = res.get("next_cursor")


TEXT_BLOCKS = ("paragraph", "heading_1", "heading_2", "heading_3", "quote",
               "callout", "bulleted_list_item", "numbered_list_item", "to_do", "code")


def page_content(token, page_id, depth=0):
    """Текст со страницы и картинки из неё. Заметки в Notion часто лежат
       именно в теле страницы, а не в колонке."""
    text, images, cursor = [], [], None
    while True:
        q = "?page_size=100" + ("&start_cursor=" + cursor if cursor else "")
        res = _req(token, "GET", "/blocks/%s/children%s" % (page_id, q))
        for b in res.get("results", []):
            bt = b.get("type") or ""
            if bt in TEXT_BLOCKS:
                s = _plain((b.get(bt) or {}).get("rich_text"))
                if s.strip():
                    text.append(("• " if bt.endswith("list_item") else "") + s.strip())
            elif bt == "image":
                img = b.get("image") or {}
                u = ((img.get("file") or {}).get("url")
                     if img.get("type") == "file" else (img.get("external") or {}).get("url"))
                if u:
                    images.append({"url": u, "caption": _plain(img.get("caption"))})
            # вложенные блоки — на один уровень, глубже журналы не заводят
            if b.get("has_children") and depth < 1 and bt != "image":
                sub_t, sub_i = page_content(token, b.get("id"), depth + 1)
                if sub_t:
                    text.append(sub_t)
                images.extend(sub_i)
        if not res.get("has_more"):
            break
        cursor = res.get("next_cursor")
    return "\n".join(text).strip(), images


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


def run_import(job, token, db_id, mapping, opts, shots_dir, known_pairs, existing_ids, sink):
    """
    Забирает базу целиком и отдаёт готовые сделки в sink(list).
    sink сам решает, как их сохранить — этот файл про Notion, а не про хранилище.
    """
    try:
        job.step = "читаємо базу"
        pages = rows(token, db_id)
        job.total = len(pages)

        want_notes = bool(opts.get("notes", True))
        want_shots = bool(opts.get("shots", True))
        skip_known = bool(opts.get("skipExisting", True))
        batch = []

        for page in pages:
            job.done += 1
            pid = page.get("id") or ""
            if skip_known and pid in existing_ids:
                job.skipped += 1
                continue

            t = map_row(page, mapping)
            if not (t.get("pair") or "").strip():
                job.skipped += 1
                job.warnings.append("рядок без інструмента пропущено")
                continue

            job.step = "%s · %s" % (t.get("pair") or "?", (t.get("date") or "")[:10])

            images = []
            for col, prop in (page.get("properties") or {}).items():
                if (prop or {}).get("type") == "files":
                    images += [{"url": u, "caption": col} for u in _file_urls(prop)]

            if want_notes or want_shots:
                try:
                    text, page_imgs = page_content(token, pid)
                except NotionError as ex:
                    text, page_imgs = "", []
                    job.warnings.append("сторінку не прочитали: %s" % ex)
                if want_shots:
                    images += page_imgs
                if want_notes and text:
                    t["notes"] = (t["notes"] + "\n\n" + text).strip() if t.get("notes") else text

            shots = []
            if want_shots:
                for i, im in enumerate(images):
                    try:
                        base = "notion_%s_%d" % (re.sub(r"[^0-9a-f]", "", pid)[:32], i)
                        fname = download(im["url"], shots_dir, base)
                        shots.append({"tf": guess_tf(im.get("caption"), im["url"]), "file": fname})
                        job.shots += 1
                    except Exception as ex:
                        job.warnings.append("скрін не завантажився: %s" % ex)
            t["screenshots"] = shots

            pair = (t.get("pair") or "").strip()
            if pair and pair not in known_pairs:
                known_pairs.add(pair)
                job.new_assets.append(pair)

            batch.append(t)
            job.added += 1
            if len(batch) >= 25:
                sink(batch)
                batch = []

        if batch:
            sink(batch)
        job.step = "готово"
        job.state = "done"
    except NotionError as ex:
        job.state, job.error = "error", str(ex)
    except Exception as ex:
        job.state, job.error = "error", "несподівана помилка: %s" % ex

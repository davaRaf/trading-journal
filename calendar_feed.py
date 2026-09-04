# -*- coding: utf-8 -*-
"""
Экономический календарь.
Фид Forex Factory блокирует за частые запросы, поэтому ходим за ним отсюда
раз в полчаса, а не из браузера каждого пользователя. Каждую удачную выгрузку
складываем в архив по неделям: фид отдаёт только текущую неделю, историю
иначе взять негде, и каждый пропущенный день потерян навсегда.
"""
import datetime
import hashlib
import json
import os
import threading
import time
import urllib.request

from config import ROOT

CAL_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
CAL_DIR = os.path.join(ROOT, "data", "calendar")
CAL_TTL = 1800          # секунд между походами в сеть
CAL_UA  = "Mozilla/5.0 (compatible; StatsAI/1.0; +local)"

os.makedirs(CAL_DIR, exist_ok=True)
_cal_lock = threading.Lock()
_cal = {"at": 0, "data": None, "error": None}


def _cal_week_file(iso_date):
    """Файл архива по номеру недели из даты события."""
    y, w, _ = datetime.date.fromisoformat(iso_date[:10]).isocalendar()
    return os.path.join(CAL_DIR, "%04d-W%02d.json" % (y, w))


def _cal_archive(events):
    """Дописываем события в архив, не плодя дубликаты."""
    by_week = {}
    for e in events:
        try:
            by_week.setdefault(_cal_week_file(e.get("date", "")), []).append(e)
        except Exception:
            continue
    for path, items in by_week.items():
        old = []
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    old = json.load(f)
            except Exception:
                old = []
        seen = {(x.get("date"), x.get("country"), x.get("title")) for x in old}
        for e in items:
            k = (e.get("date"), e.get("country"), e.get("title"))
            if k not in seen:
                old.append(e); seen.add(k)
        old.sort(key=lambda x: x.get("date") or "")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(old, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)


def _cal_newest_archive():
    """Если сеть недоступна — отдаём последнее, что успели сохранить."""
    files = sorted(f for f in os.listdir(CAL_DIR) if f.endswith(".json"))
    if not files:
        return None
    try:
        with open(os.path.join(CAL_DIR, files[-1]), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def calendar_events():
    """Отдаёт события недели: из памяти, из сети или из архива."""
    with _cal_lock:
        fresh = _cal["data"] is not None and (time.time() - _cal["at"]) < CAL_TTL
        if fresh:
            return _cal["data"], None
        try:
            req = urllib.request.Request(CAL_URL, headers={"User-Agent": CAL_UA})
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.loads(r.read().decode("utf-8"))
            if not isinstance(data, list):
                raise ValueError("фид вернул не список")
            _cal.update(at=time.time(), data=data, error=None)
            try:
                _cal_archive(data)
            except Exception:
                pass
            return data, None
        except Exception as ex:
            _cal["error"] = str(ex)
            if _cal["data"] is not None:
                return _cal["data"], "сеть недоступна, показываю сохранённое"
            saved = _cal_newest_archive()
            if saved is not None:
                return saved, "сеть недоступна, показываю архив"
            return [], "календарь недоступен: %s" % ex


_warming = threading.Event()


def _warm():
    try:
        calendar_events()
    except Exception:
        pass
    finally:
        _warming.clear()


def cached_events():
    """Те, що вже лежить у пам'яті або в архіві — без походу в мережу.

    Помічник підкладає новини до кожного питання, а чужий фід відповідає
    коли захоче: чекати на нього посеред відповіді не можна — краще
    відповісти без свіжого календаря, ніж мовчати півхвилини. Якщо копія
    застаріла, оновлення запускаємо у фоні, і наступне питання дістане вже
    свіже.
    """
    with _cal_lock:
        data = _cal["data"]
        fresh = data is not None and (time.time() - _cal["at"]) < CAL_TTL
    if not fresh and not _warming.is_set():
        _warming.set()
        threading.Thread(target=_warm, daemon=True).start()
    if data is not None:
        return data
    saved = _cal_newest_archive()
    return saved if saved is not None else []


# ------------------------------------------------ помощники для бота ----

def event_key(event):
    """Своего id у событий фида нет — ключуем той же тройкой, что и архив."""
    raw = "|".join([event.get("date") or "", event.get("country") or "",
                    event.get("title") or ""])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def event_time(event):
    """Дата события в фиде уже со смещением, свой часовой пояс тут не нужен."""
    try:
        return datetime.datetime.fromisoformat(event["date"])
    except Exception:
        return None


def is_high(event):
    return (event.get("impact") or "").lower() == "high"

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

# Фід віддає рівно один тиждень — той, що йде. У суботу це вже минуле: на
# питання «що там у понеділок» помічник відповідав «новин немає», бо далі
# п'ятниці не бачив нічого. Сусіднього фіда на наступний тиждень у них не
# існує (усі інші адреси віддають 404), тож майбутні дні беремо з календаря
# TradingView — він уже є в проєкті заради історії показників.
TV_COUNTRIES = "US,EU,GB,JP,CH,CA,AU,NZ,CN"
TV_AHEAD = 9            # на скільки днів уперед питаємо TradingView
# TradingView називає країну, а фід — валюту; помічник рахує саме валюти.
TV_CURRENCY = {"US": "USD", "EU": "EUR", "GB": "GBP", "JP": "JPY", "CH": "CHF",
               "CA": "CAD", "AU": "AUD", "NZ": "NZD", "CN": "CNY"}
# У TradingView важливість — число, у фіда — слово. Зводимо до слова, бо на
# нього дивиться is_high і весь код навколо.
TV_IMPACT = {1: "High", 0: "Medium", -1: "Low"}
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


def _fetch(url):
    """Одна выгрузка фида."""
    req = urllib.request.Request(url, headers={"User-Agent": CAL_UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def _from_tradingview(rows):
    """Події TradingView у тому ж вигляді, що й події фіда."""
    out = []
    for r in rows:
        cur = TV_CURRENCY.get((r.get("country") or "").upper())
        if not cur or not r.get("date"):
            continue
        out.append({
            "title": r.get("title") or "",
            "country": cur,
            "date": r.get("date"),
            "impact": TV_IMPACT.get(r.get("importance"), "Low"),
            "forecast": r.get("forecast"),
            "previous": r.get("previous"),
        })
    return out


def _ahead(after):
    """Дні після кінця фіда — з TradingView.

    Беремо тільки те, що лежить пізніше за останній день фіда: на спільних
    днях довіряємо фіду, він і так точний, а два джерела дали б дублі.
    """
    import tv_calendar          # тут, а не зверху: модуль важкий і потрібен рідко
    today = datetime.date.today()
    rows = tv_calendar._fetch(TV_COUNTRIES, today.isoformat(),
                              (today + datetime.timedelta(days=TV_AHEAD)).isoformat())
    return [e for e in _from_tradingview(rows) if str(e.get("date"))[:10] > after]


def _merge(*lists):
    """Склеиваем недели, не плодя дубликаты: события на стыке приходят дважды."""
    out, seen = [], set()
    for items in lists:
        for e in items or []:
            k = (e.get("date"), e.get("country"), e.get("title"))
            if k in seen:
                continue
            seen.add(k)
            out.append(e)
    out.sort(key=lambda x: x.get("date") or "")
    return out


def calendar_events():
    """Отдаёт события двух недель — текущей и следующей: из памяти, из сети
    или из архива."""
    with _cal_lock:
        fresh = _cal["data"] is not None and (time.time() - _cal["at"]) < CAL_TTL
        if fresh:
            return _cal["data"], None
        err = None
        try:
            data = _fetch(CAL_URL)
            if not isinstance(data, list):
                raise ValueError("фид вернул не список")
            _cal.update(at=time.time(), error=None)
            try:
                _cal_archive(data)
            except Exception:
                pass
        except Exception as ex:
            _cal["error"] = str(ex)
            if _cal["data"] is not None:
                data, err = _cal["data"], "сеть недоступна, показываю сохранённое"
            else:
                data = _cal_newest_archive()
                if data is None:
                    return [], "календарь недоступен: %s" % ex
                err = "сеть недоступна, показываю архив"
        # Майбутні дні — з TradingView, і саме тут, а не всередині вдалої
        # спроби: коли фід відповідає «429, забагато запитів», днями вперед
        # він однаково не допоможе, а календар на понеділок потрібен.
        try:
            last = max((str(e.get("date"))[:10] for e in data), default="")
            nxt = _ahead(last) if last else []
        except Exception as ex:
            print("календар уперед:", ex)
            nxt = []
        if nxt:
            data = _merge(data, nxt)
        _cal["data"] = data
        return data, err


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


# ------------------------------------------------ історія однієї події ----

# Скільки днів між випусками ще вважаємо сусідніми. Місячні показники
# виходять раз на 28-31 день; 40 лишає запас на перенесення свята.
HIST_GAP_DAYS = 40
HIST_FILES = 80          # скільки тижневих файлів переглядаємо (≈півтора року)


def _hist_rows(country, title):
    """Усі збережені випуски цієї події з архіву, від старих до нових."""
    try:
        files = sorted(f for f in os.listdir(CAL_DIR) if f.endswith(".json"))
    except OSError:
        return []
    by_date = {}
    for name in files[-HIST_FILES:]:
        try:
            with open(os.path.join(CAL_DIR, name), "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        for e in data:
            if ((e.get("title") or "").strip() == title
                    and (e.get("country") or "").strip() == country):
                by_date[e.get("date") or ""] = e
    return [by_date[k] for k in sorted(by_date) if k]


def event_history(country, title, limit=12):
    """Попередні випуски події: коли, який був прогноз і що вийшло.

    Фактичного значення фід не віддає взагалі — у ньому лише прогноз і
    «попереднє». Але «попереднє» наступного випуску і є результат цього:
    саме з ним ринок порівнює нові цифри. Тому факт беремо звідти, але
    лише коли випуски справді сусідні (див. HIST_GAP_DAYS): якщо сервер
    тиждень не працював, між збереженими рядками може загубитись ціла
    публікація, і тоді підставили б чуже число.

    Історія росте сама: фід знає тільки поточний тиждень, і кожен похід у
    мережу дописує архів. Тому в перші тижні тут буде порожньо — це не
    поламка, а просто ще не накопичилось.
    """
    country = (country or "").strip()
    title = (title or "").strip()
    if not country or not title:
        return []
    rows = _hist_rows(country, title)
    out = []
    for i, e in enumerate(rows):
        nxt = rows[i + 1] if i + 1 < len(rows) else None
        actual = ""
        if nxt:
            a, b = event_time(e), event_time(nxt)
            near = a and b and (b - a).days <= HIST_GAP_DAYS
            if near:
                actual = (nxt.get("previous") or "").strip()
        out.append({"date": e.get("date") or "",
                    "period": "",          # у фіді періоду немає, поле для однаковості
                    "forecast": (e.get("forecast") or "").strip(),
                    "previous": (e.get("previous") or "").strip(),
                    "actual": actual})
    out.reverse()
    return out[:limit]


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

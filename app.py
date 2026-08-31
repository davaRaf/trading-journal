# -*- coding: utf-8 -*-
"""
Trading Journal — локальный сервер.
Только стандартная библиотека Python. Запуск:  python app.py
Данные: data/trades.json, скриншоты: data/screenshots/
"""
import json, os, re, base64, threading, time, urllib.request, datetime, secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, unquote

import notion_import as notion
import notion_public as npub

ROOT   = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(ROOT, "static")
DATA   = os.path.join(ROOT, "data")
SHOTS  = os.path.join(DATA, "screenshots")
TRADES_FILE = os.path.join(DATA, "trades.json")
PORT   = int(os.environ.get("PORT", 8172))   # рабочая копия запускается на другом порту

os.makedirs(SHOTS, exist_ok=True)

_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Ссылки, которыми можно поделиться.
#
# Сохраняем снимок статистики файлом и выдаём короткий адрес. Снимок — уже
# посчитанные цифры, а не сами сделки: по ссылке нельзя вытащить журнал целиком.
# У каждой ссылки свой срок жизни; просроченные удаляются при обращении.
# ---------------------------------------------------------------------------
SHARE_DIR = os.path.join(DATA, "shares")
SHARE_MAX = 256 * 1024          # больше снимку не нужно
SHARE_TTL = {                   # что можно выбрать в интерфейсе, в секундах
    "1h":   3600,
    "24h":  86400,
    "7d":   604800,
    "30d":  2592000,
    "forever": 0,               # 0 — без срока
}
os.makedirs(SHARE_DIR, exist_ok=True)
_share_lock = threading.Lock()

def _share_path(sid):
    return os.path.join(SHARE_DIR, sid + ".json")

def share_create(payload, ttl_key):
    sid = secrets.token_urlsafe(9)          # 12 символов, хватает с запасом
    ttl = SHARE_TTL.get(ttl_key, SHARE_TTL["7d"])
    rec = {
        "id": sid,
        "created": int(time.time()),
        "expires": int(time.time()) + ttl if ttl else 0,
        "ttl": ttl_key,
        "data": payload,
    }
    with _share_lock:
        tmp = _share_path(sid) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False)
        os.replace(tmp, _share_path(sid))
    return rec

def share_read(sid):
    """Отдаёт снимок или None, если его нет либо срок вышел."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,32}", sid or ""):
        return None
    path = _share_path(sid)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            rec = json.load(f)
    except Exception:
        return None
    if rec.get("expires") and time.time() > rec["expires"]:
        try: os.remove(path)                # просроченное сразу убираем
        except Exception: pass
        return None
    return rec

# ---------------------------------------------------------------------------
# Экономический календарь.
# Фид Forex Factory блокирует за частые запросы, поэтому ходим за ним отсюда
# раз в полчаса, а не из браузера каждого пользователя. Каждую удачную выгрузку
# складываем в архив по неделям: фид отдаёт только текущую неделю, историю
# иначе взять негде, и каждый пропущенный день потерян навсегда.
# ---------------------------------------------------------------------------
CAL_URL  = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
CAL_DIR  = os.path.join(DATA, "calendar")
CAL_TTL  = 1800          # секунд между походами в сеть
CAL_UA   = "Mozilla/5.0 (compatible; StatsAI/1.0; +local)"

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

def _load():
    if not os.path.exists(TRADES_FILE):
        return []
    try:
        with open(TRADES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        # повреждённый файл не затираем — откладываем копию
        try:
            os.replace(TRADES_FILE, TRADES_FILE + ".broken." + str(int(time.time())))
        except Exception:
            pass
        return []

def _save(trades):
    tmp = TRADES_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(trades, f, ensure_ascii=False, indent=1)
    os.replace(tmp, TRADES_FILE)

TRADES = _load()

_id_counter = int(time.time() * 1000)
def new_id():
    global _id_counter
    _id_counter += 1
    return "t" + str(_id_counter)

DATAURL_RE = re.compile(r"^data:image/(png|jpeg|jpg|webp|gif);base64,(.+)$", re.S)

def save_screenshots(trade):
    """Скриншоты с base64-данными сохраняем в файлы; уже сохранённые оставляем."""
    out = []
    shots = trade.get("screenshots") or []
    for i, s in enumerate(shots):
        tf = re.sub(r"[^0-9A-Za-zА-Яа-я]", "", str(s.get("tf") or "img"))[:8] or "img"
        if s.get("data"):
            m = DATAURL_RE.match(s["data"])
            if not m:
                continue
            ext = m.group(1).replace("jpeg", "jpg")
            try:
                raw = base64.b64decode(m.group(2))
            except Exception:
                continue
            name = "%s_%d_%s.%s" % (trade["id"], int(time.time() * 1000) % 100000000 + i, tf, ext)
            with open(os.path.join(SHOTS, name), "wb") as f:
                f.write(raw)
            out.append({"tf": s.get("tf") or "", "file": name})
        elif s.get("file"):
            out.append({"tf": s.get("tf") or "", "file": s["file"]})
    trade["screenshots"] = out

def delete_files(names):
    for n in names:
        p = os.path.join(SHOTS, os.path.basename(n))
        if os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass

FIELDS = ["pair","date","session","position","entry_model","bias","setup","direction_type",
          "result","rr","risk","entry_details","notes","mistakes","comments"]

def clean_trade(body, tid):
    t = {"id": tid}
    for k in FIELDS:
        v = body.get(k)
        t[k] = v if v is not None else ""
    for k in ("rr", "risk"):
        try:
            t[k] = float(t[k]) if str(t[k]).strip() != "" else None
        except Exception:
            t[k] = None
    t["screenshots"] = body.get("screenshots") or []
    if body.get("hidden"): t["hidden"] = True
    # откуда сделка приехала — нужно, чтобы повторный импорт не задвоил её
    if body.get("notion_id"): t["notion_id"] = str(body["notion_id"])[:64]
    return t

# ---------------------------------------------------------------------------
# Перенос журнала из Notion по обычной публичной ссылке.
#
# Никаких ключей: человек в Notion делает Share -> Publish to web и вставляет
# сюда ссылку. Чтение живёт в notion_public.py, разбор значений — в
# notion_import.py. В data/notion.json запоминаем последнюю ссылку и сверку
# колонок, чтобы не настраивать заново.
# ---------------------------------------------------------------------------
NOTION_FILE = os.path.join(DATA, "notion.json")
_jobs = {}
_jobs_lock = threading.Lock()


def notion_conf():
    try:
        with open(NOTION_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def notion_save(conf):
    tmp = NOTION_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(conf, f, ensure_ascii=False, indent=1)
    os.replace(tmp, NOTION_FILE)


def add_trades(items):
    """Кладём пачку сделок в журнал. Вызывается из фонового потока."""
    with _lock:
        for it in items:
            t = clean_trade(it, new_id())
            t["screenshots"] = it.get("screenshots") or []
            TRADES.append(t)
        _save(TRADES)


def start_import(url, mapping, opts):
    jid = secrets.token_urlsafe(6)
    job = notion.Job(jid)
    with _jobs_lock:
        _jobs[jid] = job
        # старые задания не копим
        for old_id in list(_jobs)[:-8]:
            _jobs.pop(old_id, None)
    with _lock:
        known = {(t.get("pair") or "").strip() for t in TRADES if t.get("pair")}
        seen = {t.get("notion_id") for t in TRADES if t.get("notion_id")}
    th = threading.Thread(
        target=npub.run_public_import,
        args=(job, url, mapping, opts, SHOTS, known, seen, add_trades),
        daemon=True)
    th.start()
    return job


class H(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # тихий лог
        pass

    # ---------- ответы ----------
    def _json(self, obj, code=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _file(self, path, ctype):
        try:
            with open(path, "rb") as f:
                data = f.read()
        except Exception:
            self.send_response(404); self.end_headers(); return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        # Без этого браузер сам решает, сколько держать файл в кэше, и после
        # правки в js/css показывает старую версию — правки будто не применились.
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            return None
        raw = self.rfile.read(n)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return None

    # ---------- GET ----------
    def do_GET(self):
        p = unquote(urlparse(self.path).path)
        if p == "/api/trades":
            with _lock:
                return self._json(TRADES)
        if p == "/api/calendar":
            events, warn = calendar_events()
            return self._json({"events": events, "warning": warn})
        if p.startswith("/api/share/"):
            rec = share_read(p[len("/api/share/"):])
            if rec is None:
                return self._json({"error": "посилання не знайдено або прострочене"}, 404)
            return self._json(rec)
        if p == "/api/notion/state":
            conf = notion_conf()
            return self._json({
                "url": conf.get("url") or "",
                "title": conf.get("title") or "",
                "mapping": conf.get("mapping") or {},
                "fields": [{"k": k, "label": notion.LABELS[k]} for k in notion.FIELDS],
            })
        if p.startswith("/api/notion/job/"):
            with _jobs_lock:
                job = _jobs.get(p[len("/api/notion/job/"):])
            if not job:
                return self._json({"error": "завдання не знайдено"}, 404)
            return self._json(job.snapshot())
        if p.startswith("/s/"):
            return self._file(os.path.join(STATIC, "share.html"), "text/html; charset=utf-8")
        if p == "/login":
            return self._file(os.path.join(STATIC, "login.html"), "text/html; charset=utf-8")
        if p.startswith("/design/"):
            # прототипы: экран входа, новости, знак — чтобы смотреть с того же адреса
            name = os.path.normpath(p[len("/design/"):]).replace("\\", "/")
            if name.startswith("..") or name in ("", "."):
                self.send_response(403); self.end_headers(); return
            full = os.path.join(ROOT, "design", name)
            if os.path.isdir(full):
                full = os.path.join(full, "index.html")
            ext = full.rsplit(".", 1)[-1].lower()
            ctype = {"html":"text/html; charset=utf-8","css":"text/css; charset=utf-8",
                     "js":"application/javascript; charset=utf-8","json":"application/json; charset=utf-8",
                     "svg":"image/svg+xml","png":"image/png","md":"text/plain; charset=utf-8"
                     }.get(ext, "application/octet-stream")
            return self._file(full, ctype)
        if p.startswith("/shots/"):
            name = os.path.basename(p[len("/shots/"):])
            ext = name.rsplit(".", 1)[-1].lower()
            ctype = {"png":"image/png","jpg":"image/jpeg","jpeg":"image/jpeg",
                     "webp":"image/webp","gif":"image/gif"}.get(ext, "application/octet-stream")
            return self._file(os.path.join(SHOTS, name), ctype)
        if p in ("/", "/index.html"):
            return self._file(os.path.join(STATIC, "index.html"), "text/html; charset=utf-8")
        if p.startswith("/static/"):
            name = os.path.normpath(p[len("/static/"):]).replace("\\", "/")
            if name.startswith(".."):
                self.send_response(403); self.end_headers(); return
            ext = name.rsplit(".", 1)[-1].lower()
            ctype = {"css":"text/css; charset=utf-8","js":"application/javascript; charset=utf-8",
                     "html":"text/html; charset=utf-8","png":"image/png","svg":"image/svg+xml"}.get(ext,"application/octet-stream")
            return self._file(os.path.join(STATIC, name), ctype)
        self.send_response(404); self.end_headers()

    # ---------- POST ----------
    def do_POST(self):
        p = urlparse(self.path).path
        if p == "/api/share":
            body = self._body()
            if not isinstance(body, dict) or not isinstance(body.get("data"), dict):
                return self._json({"error": "нужен объект data"}, 400)
            raw = json.dumps(body["data"], ensure_ascii=False)
            if len(raw.encode("utf-8")) > SHARE_MAX:
                return self._json({"error": "снимок слишком большой"}, 413)
            rec = share_create(body["data"], body.get("ttl", "7d"))
            return self._json({"id": rec["id"], "url": "/s/" + rec["id"],
                               "expires": rec["expires"]}, 201)
        if p == "/api/notion/preview":
            body = self._body() or {}
            url = str(body.get("url") or "").strip()
            try:
                data = npub.preview(url, body.get("mapping"))
            except notion.NotionError as ex:
                return self._json({"error": str(ex)}, 400)
            except Exception as ex:
                return self._json({"error": "не вдалося прочитати сторінку: %s" % ex}, 502)
            conf = notion_conf()
            conf.update({"url": url, "title": data.get("title") or "",
                         "mapping": data.get("mapping") or {}})
            notion_save(conf)
            data["fields"] = [{"k": k, "label": notion.LABELS[k]} for k in notion.FIELDS]
            data.pop("source", None)
            return self._json(data)
        if p == "/api/notion/forget":
            try:
                os.remove(NOTION_FILE)
            except Exception:
                pass
            return self._json({"ok": True})
        if p == "/api/notion/import":
            body = self._body() or {}
            url = str(body.get("url") or "").strip()
            mapping = body.get("mapping") or {}
            if not url or not mapping.get("pair"):
                return self._json({"error": "потрібні посилання і колонка з інструментом"}, 400)
            conf = notion_conf()
            conf.update({"url": url, "mapping": mapping, "title": body.get("title") or ""})
            notion_save(conf)
            job = start_import(url, mapping, body.get("options") or {})
            return self._json(job.snapshot(), 202)
        if p == "/api/trades":
            body = self._body()
            if not isinstance(body, dict) or not str(body.get("pair", "")).strip():
                return self._json({"error": "bad json or empty pair"}, 400)
            with _lock:
                t = clean_trade(body, new_id())
                save_screenshots(t)
                TRADES.append(t)
                _save(TRADES)
            return self._json(t, 201)
        if p == "/api/import":
            body = self._body()
            if body is None:
                return self._json({"error": "bad json"}, 400)
            items = body if isinstance(body, list) else body.get("trades") or []
            added = 0
            with _lock:
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    t = clean_trade(it, new_id())
                    save_screenshots(t)
                    TRADES.append(t)
                    added += 1
                _save(TRADES)
            return self._json({"ok": True, "added": added})
        self.send_response(404); self.end_headers()

    # ---------- PUT ----------
    def do_PUT(self):
        p = urlparse(self.path).path
        m = re.match(r"^/api/trades/([\w-]+)$", p)
        if not m:
            self.send_response(404); self.end_headers(); return
        tid = m.group(1)
        body = self._body()
        if not isinstance(body, dict):
            return self._json({"error": "bad json"}, 400)
        with _lock:
            for i, old in enumerate(TRADES):
                if old["id"] == tid:
                    t = clean_trade(body, tid)
                    save_screenshots(t)
                    old_files = {s["file"] for s in old.get("screenshots") or [] if s.get("file")}
                    new_files = {s["file"] for s in t["screenshots"] if s.get("file")}
                    delete_files(old_files - new_files)
                    TRADES[i] = t
                    _save(TRADES)
                    return self._json(t)
        self._json({"error": "not found"}, 404)

    # ---------- DELETE ----------
    def do_DELETE(self):
        p = urlparse(self.path).path
        m = re.match(r"^/api/trades/([\w-]+)$", p)
        if not m:
            self.send_response(404); self.end_headers(); return
        tid = m.group(1)
        with _lock:
            for i, old in enumerate(TRADES):
                if old["id"] == tid:
                    delete_files([s["file"] for s in old.get("screenshots") or [] if s.get("file")])
                    TRADES.pop(i)
                    _save(TRADES)
                    return self._json({"ok": True})
        self._json({"error": "not found"}, 404)

if __name__ == "__main__":
    print("Trading Journal -> http://localhost:%d/  (Ctrl+C stop)" % PORT)
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()

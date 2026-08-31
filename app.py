# -*- coding: utf-8 -*-
"""
Trading Journal — локальный сервер.
Только стандартная библиотека Python. Запуск:  python app.py
Данные: data/trades.json, скриншоты: data/screenshots/
"""
import json, os, re, base64, threading, time, urllib.request, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, unquote

ROOT   = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(ROOT, "static")
DATA   = os.path.join(ROOT, "data")
SHOTS  = os.path.join(DATA, "screenshots")
TRADES_FILE = os.path.join(DATA, "trades.json")
PORT   = int(os.environ.get("PORT", 8172))   # рабочая копия запускается на другом порту

os.makedirs(SHOTS, exist_ok=True)

_lock = threading.Lock()

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
    return t

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

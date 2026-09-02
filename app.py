# -*- coding: utf-8 -*-
"""
Trading Journal — сервер журнала.
Только стандартная библиотека Python плюс драйвер Postgres. Запуск:  python app.py
Данные: Postgres (DATABASE_URL), скриншоты: data/screenshots/
"""
import base64
import datetime
import json
import os
import re
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, unquote

import assistant
import auth
import config
import db
import emotions
import filestore
import llm
import notion_import as notion
import notion_public as npub
import day_store
import tg_api
import ts_notion
import ts_store
from calendar_feed import calendar_events

ROOT   = config.ROOT
STATIC = os.path.join(ROOT, "static")
DATA   = config.DATA_DIR
SHOTS  = os.path.join(DATA, "screenshots")
PORT   = config.PORT

os.makedirs(SHOTS, exist_ok=True)

_id_counter = int(time.time() * 1000)
_id_lock = threading.Lock()


def new_id():
    global _id_counter
    with _id_lock:
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
            keep_file(name, raw)
            out.append({"tf": s.get("tf") or "", "file": name})
        elif s.get("file"):
            out.append({"tf": s.get("tf") or "", "file": s["file"]})
    trade["screenshots"] = out


def keep_file(name, raw):
    """Картинка живёт в базе, на диске остаётся кэшем: у контейнеров на
       хостинге файловая система временная, а база — нет."""
    try:
        filestore.put(name, raw)
    except Exception:
        pass
    try:
        with open(os.path.join(SHOTS, name), "wb") as f:
            f.write(raw)
    except OSError:
        pass


def shot_path(name):
    """Путь к картинке: с диска, а если его там нет — вытащив из базы."""
    path = os.path.join(SHOTS, os.path.basename(name))
    if os.path.exists(path):
        return path
    try:
        return filestore.cache(SHOTS, name)
    except Exception:
        return None


def delete_files(names):
    try:
        filestore.delete([os.path.basename(n) for n in names if n])
    except Exception:
        pass
    for n in names:
        p = os.path.join(SHOTS, os.path.basename(n))
        if os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass


def clean_trade(body, tid):
    t = {"id": tid}
    for k in db.FIELDS:
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
    # какое перенесение её принесло — нужно, чтобы его можно было отменить
    if body.get("import_id"): t["import_id"] = str(body["import_id"])[:32]
    return t


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
# Перенос журнала из Notion по обычной публичной ссылке.
#
# Никаких ключей: человек в Notion делает Share -> Publish to web и вставляет
# сюда ссылку. Чтение живёт в notion_public.py, разбор значений — в
# notion_import.py. Последнюю ссылку и сверку колонок помним для каждого
# пользователя отдельно: журналы у всех свои.
# ---------------------------------------------------------------------------
NOTION_DIR = os.path.join(DATA, "notion")
os.makedirs(NOTION_DIR, exist_ok=True)
_jobs = {}
_jobs_lock = threading.Lock()


def notion_file(uid):
    return os.path.join(NOTION_DIR, "user_%d.json" % uid)


def notion_conf(uid):
    try:
        with open(notion_file(uid), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def notion_save(uid, conf):
    tmp = notion_file(uid) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(conf, f, ensure_ascii=False, indent=1)
    os.replace(tmp, notion_file(uid))


def add_trades(user_id, items):
    """Кладём пачку сделок в журнал. Вызывается из фонового потока импорта."""
    batch = []
    for it in items:
        t = clean_trade(it, new_id())
        t["screenshots"] = it.get("screenshots") or []
        batch.append(t)
    db.insert_trades(user_id, batch)
    # Перенос качает картинки прямо на диск. Забираем их в базу, иначе после
    # первого же обновления кода на хостинге они пропадут.
    for t in batch:
        for sh in t["screenshots"]:
            name = sh.get("file")
            if not name:
                continue
            try:
                filestore.ingest(os.path.join(SHOTS, name), name)
            except Exception:
                pass


def drop_import(user_id, batch):
    """Отменяет перенесение целиком: убирает его сделки и их скриншоты.

    Без этого любая ошибка в сверке колонок необратима — а ошибиться там
    легко, поэтому откат нужен не «когда-нибудь», а сразу."""
    batch = str(batch or "")[:32]
    if not batch:
        return 0
    removed, orphan_files = db.drop_import(user_id, batch)
    if not removed:
        return 0
    delete_files(orphan_files)
    conf = notion_conf(user_id)
    if (conf.get("last") or {}).get("id") == batch:
        conf.pop("last", None)
        notion_save(user_id, conf)
    return removed


def start_import(user_id, tables, mapping, opts):
    jid = secrets.token_urlsafe(6)
    job = notion.Job(jid)
    job.user_id = user_id          # чтобы чужое задание нельзя было подсмотреть
    with _jobs_lock:
        _jobs[jid] = job
        # старые задания не копим
        for old_id in list(_jobs)[:-8]:
            _jobs.pop(old_id, None)
    known, seen = db.notion_known(user_id)
    th = threading.Thread(
        target=npub.run_public_import,
        args=(job, tables, mapping, opts, SHOTS, known, seen,
              lambda items: add_trades(user_id, items)),
        daemon=True)
    th.start()
    return job


def ask_emotion_later(user, trade):
    """Вопрос про эмоцию уходит в фоне — ответ сайту ждать Telegram не должен."""
    def run():
        try:
            emotions.send_prompt(user["telegram_id"], trade)
        except Exception as ex:
            print("не смог спросить про эмоцию:", ex)
    threading.Thread(target=run, daemon=True).start()


def bot_username():
    """Имя бота нужно для ссылки привязки. Спрашиваем у Telegram сами и запоминаем,
    чтобы кнопка работала и до первого запуска bot.py."""
    name = config.BOT_USERNAME or db.meta_get("bot_username")
    if name:
        return name
    try:
        name = tg_api.get_me()["username"]
    except Exception as ex:
        print("не смог узнать имя бота:", ex)
        return None
    db.meta_set("bot_username", name)
    return name


def user_public(user):
    return {"id": user["id"], "email": user["email"], "nickname": user["nickname"],
            "telegram": user["telegram_username"] or (str(user["telegram_id"])
                                                      if user["telegram_id"] else None),
            "telegram_linked": user["telegram_id"] is not None,
            "digest_hour": user["digest_hour"], "digest_minute": user["digest_minute"],
            "digest_enabled": user["digest_enabled"]}


class H(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # тихий лог
        pass

    # ---------- ответы ----------
    def _json(self, obj, code=200, cookie=None):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        if cookie:
            self.send_header("Set-Cookie", cookie)
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

    def _redirect(self, where):
        self.send_response(302)
        self.send_header("Location", where)
        self.end_headers()

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            return None
        raw = self.rfile.read(n)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return None

    def _uid(self):
        return auth.current_user_id(self)

    # ---------- GET ----------
    def do_GET(self):
        p = unquote(urlparse(self.path).path)

        # ---- открыто всем: страница по ссылке и её снимок ----
        if p.startswith("/api/share/"):
            rec = share_read(p[len("/api/share/"):])
            if rec is None:
                return self._json({"error": "посилання не знайдено або прострочене"}, 404)
            return self._json(rec)
        if p.startswith("/s/"):
            return self._file(os.path.join(STATIC, "share.html"), "text/html; charset=utf-8")

        if p == "/api/auth/me":
            uid = self._uid()
            user = db.get_user(uid) if uid else None
            return self._json({"user": user_public(user) if user else None})

        if p == "/api/trades":
            uid = self._uid()
            if not uid:
                return self._json({"error": "auth required"}, 401)
            return self._json(db.list_trades(uid))

        # ---- аналіз дня (day_store.py) ----
        if p.startswith("/api/day/"):
            uid = self._uid()
            if not uid:
                return self._json({"error": "auth required"}, 401)
            rest = p[len("/api/day/"):]
            if rest == "list":
                return self._json({"days": day_store.days(uid)})
            if rest == "stats":
                since = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
                return self._json({"notes": day_store.notes_since(uid, since), "since": since})
            if not day_store.valid_date(rest):
                return self._json({"error": "bad date"}, 400)
            return self._json({"day": day_store.get(uid, rest)})

        if p.startswith("/dnshot/"):
            uid = self._uid()
            name = os.path.basename(p[len("/dnshot/"):])
            if not uid or not day_store.owns_shot(uid, name):
                self.send_response(404); self.end_headers(); return
            ext = name.rsplit(".", 1)[-1].lower()
            ctype = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                     "webp": "image/webp", "gif": "image/gif"}.get(ext, "application/octet-stream")
            path = shot_path(name)
            if not path:
                self.send_response(404); self.end_headers(); return
            return self._file(path, ctype)

        # ---- торгова стратегія (ts_store.py, ts_notion.py) ----
        if p == "/api/ts":
            uid = self._uid()
            if not uid:
                return self._json({"error": "auth required"}, 401)
            return self._json({"ts": ts_store.get(uid)})

        if p.startswith("/tsshot/"):
            uid = self._uid()
            name = os.path.basename(p[len("/tsshot/"):])
            if not uid or not ts_store.owns_shot(uid, name):
                self.send_response(404); self.end_headers(); return
            ext = name.rsplit(".", 1)[-1].lower()
            ctype = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                     "webp": "image/webp", "gif": "image/gif"}.get(ext, "application/octet-stream")
            path = shot_path(name)
            if not path:
                self.send_response(404); self.end_headers(); return
            return self._file(path, ctype)

        if p == "/api/calendar":
            events, warn = calendar_events()
            return self._json({"events": events, "warning": warn})

        if p == "/api/notion/state":
            uid = self._uid()
            if not uid:
                return self._json({"error": "auth required"}, 401)
            conf = notion_conf(uid)
            last = conf.get("last") or None
            if last and last.get("id"):
                # считаем по журналу, а не по записанному числу: цифра верна,
                # даже если браузер закрыли посреди перенесения
                last = dict(last, count=db.count_import(uid, last["id"]))
                if not last["count"]:
                    last = None
            return self._json({
                "url": conf.get("url") or "",
                "title": conf.get("title") or "",
                "last": last,
                "mapping": conf.get("mapping") or {},
                "fields": [{"k": k, "label": notion.LABELS[k]} for k in notion.FIELDS],
            })

        if p.startswith("/api/notion/job/"):
            uid = self._uid()
            if not uid:
                return self._json({"error": "auth required"}, 401)
            with _jobs_lock:
                job = _jobs.get(p[len("/api/notion/job/"):])
            if not job or getattr(job, "user_id", None) != uid:
                return self._json({"error": "завдання не знайдено"}, 404)
            return self._json(job.snapshot())

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
            uid = self._uid()
            name = os.path.basename(p[len("/shots/"):])
            # скриншот отдаём только владельцу сделки, в которой он числится
            if not uid or not db.owns_screenshot(uid, name):
                self.send_response(404); self.end_headers(); return
            ext = name.rsplit(".", 1)[-1].lower()
            ctype = {"png":"image/png","jpg":"image/jpeg","jpeg":"image/jpeg",
                     "webp":"image/webp","gif":"image/gif"}.get(ext, "application/octet-stream")
            path = shot_path(name)
            if not path:
                self.send_response(404); self.end_headers(); return
            return self._file(path, ctype)

        if p in ("/", "/index.html"):
            if not self._uid():
                return self._redirect("/login")
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
        body = self._body()

        # ---- вход и регистрация ----
        if p == "/api/auth/register":
            if not isinstance(body, dict):
                return self._json({"error": "bad json"}, 400)
            email = str(body.get("email") or "").strip()
            nickname = str(body.get("nickname") or "").strip()
            password = str(body.get("password") or "")
            if not email or not nickname or len(password) < 6:
                return self._json({"error": "потрібні пошта, нікнейм і пароль від 6 символів"}, 400)
            pw_hash, pw_salt, iters = auth.hash_password(password)
            try:
                user = db.create_user(email, nickname, pw_hash, pw_salt, iters)
            except Exception as ex:
                if "unique" in str(ex).lower() or "duplicate" in str(ex).lower():
                    return self._json({"error": "така пошта або нікнейм уже зайняті"}, 409)
                raise
            return self._json({"user": user_public(user)}, 201,
                              cookie=auth.cookie_header(auth.make_session(user["id"])))

        if p == "/api/auth/login":
            if not isinstance(body, dict):
                return self._json({"error": "bad json"}, 400)
            user = db.get_user_by_login(body.get("login"))
            if not user or not auth.verify_password(str(body.get("password") or ""),
                                                    user["pw_hash"], user["pw_salt"],
                                                    user["pw_iters"]):
                return self._json({"error": "невірна пошта або пароль"}, 401)
            return self._json({"user": user_public(user)},
                              cookie=auth.cookie_header(auth.make_session(user["id"])))

        if p == "/api/auth/logout":
            return self._json({"ok": True}, cookie=auth.clear_cookie_header())

        # ---- дальше всё только для своих ----
        uid = self._uid()
        # ---- разовая заливка скриншотов при переезде ----
        # Работает, только если задан ADMIN_TOKEN. Нужна один раз: перенести
        # накопленные картинки со старой машины. После переезда переменную убрать.
        if p == "/api/admin/upload-shot":
            token = config.ADMIN_TOKEN
            if not token or self.headers.get("X-Admin-Token") != token:
                return self._json({"error": "no"}, 404)
            name = os.path.basename(str((body or {}).get("name") or ""))
            data = (body or {}).get("data") or ""
            if not name or not re.match(r"^[\w.\-]{4,120}$", name):
                return self._json({"error": "bad name"}, 400)
            dest = os.path.join(SHOTS, name)
            if os.path.exists(dest):
                return self._json({"ok": True, "skipped": True})
            try:
                raw = base64.b64decode(data)
            except Exception:
                return self._json({"error": "bad data"}, 400)
            if len(raw) > 8 * 1024 * 1024:
                return self._json({"error": "too big"}, 400)
            with open(dest, "wb") as f:
                f.write(raw)
            return self._json({"ok": True})

        if p.startswith("/api/") and not uid:
            return self._json({"error": "auth required"}, 401)

        if p == "/api/telegram/link-code":
            bot = bot_username()
            if not bot:
                return self._json({"error": "бот не налаштований — немає BOT_TOKEN"}, 503)
            code = db.create_link_code(uid)
            return self._json({"code": code, "bot": bot,
                               "link": "https://t.me/%s?start=%s" % (bot, code)})

        if p == "/api/telegram/unlink":
            db.unlink_telegram(uid)
            return self._json({"ok": True})

        if p == "/api/assistant/ask":
            question = str((body or {}).get("question") or "").strip()
            if not question:
                return self._json({"error": "порожнє питання"}, 400)
            if not llm.enabled():
                return self._json({"error": "помічник вимкнений — немає GEMINI_API_KEY"}, 503)
            # історія розмови приходить з браузера — беремо тільки останні репліки
            raw = (body or {}).get("history")
            history = [m for m in raw if isinstance(m, dict)][-16:] if isinstance(raw, list) else []
            return self._json({"answer": assistant.ask(uid, question, history)})

        if p == "/api/assistant/review":
            if not llm.enabled():
                return self._json({"error": "помічник вимкнений — немає GEMINI_API_KEY"}, 503)
            raw = (body or {}).get("history")
            history = [m for m in raw if isinstance(m, dict)][-16:] if isinstance(raw, list) else []
            return self._json(assistant.review(uid, history))

        if p == "/api/share":
            if not isinstance(body, dict) or not isinstance(body.get("data"), dict):
                return self._json({"error": "нужен объект data"}, 400)
            raw = json.dumps(body["data"], ensure_ascii=False)
            if len(raw.encode("utf-8")) > SHARE_MAX:
                return self._json({"error": "снимок слишком большой"}, 413)
            rec = share_create(body["data"], body.get("ttl", "7d"))
            return self._json({"id": rec["id"], "url": "/s/" + rec["id"],
                               "expires": rec["expires"]}, 201)

        if p == "/api/notion/preview":
            body = body or {}
            url = str(body.get("url") or "").strip()
            try:
                data = npub.preview(url, body.get("mapping"), body.get("table"))
            except notion.NotionError as ex:
                return self._json({"error": str(ex)}, 400)
            except Exception as ex:
                return self._json({"error": "не вдалося прочитати сторінку: %s" % ex}, 502)
            conf = notion_conf(uid)
            conf.update({"url": url, "title": data.get("title") or "",
                         "mapping": data.get("mapping") or {}})
            notion_save(uid, conf)
            data["fields"] = [{"k": k, "label": notion.LABELS[k]} for k in notion.FIELDS]
            data.pop("source", None)
            return self._json(data)
        if p.startswith("/api/notion/undo/"):
            n = drop_import(uid, p[len("/api/notion/undo/"):])
            return self._json({"removed": n})

        if p == "/api/notion/forget":
            try:
                os.remove(notion_file(uid))
            except Exception:
                pass
            return self._json({"ok": True})

        if p == "/api/notion/import":
            body = body or {}
            url = str(body.get("url") or "").strip()
            mapping = body.get("mapping") or {}
            tables = [t for t in (body.get("tables") or [])
                      if isinstance(t, dict) and t.get("collection") and t.get("view")]
            if not tables or not mapping.get("pair"):
                return self._json({"error": "потрібні таблиця і колонка з інструментом"}, 400)
            conf = notion_conf(uid)
            conf.update({"url": url, "mapping": mapping, "title": body.get("title") or ""})
            job = start_import(uid, tables, mapping, body.get("options") or {})
            conf["last"] = {"id": job.batch, "count": 0,
                            "when": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}
            notion_save(uid, conf)
            return self._json(job.snapshot(), 202)

        # ---- аналіз дня ----
        if p == "/api/day/shot":
            try:
                name = day_store.save_shot(uid, (body or {}).get("data") or "", SHOTS)
            except ValueError as e:
                return self._json({"error": str(e)}, 400)
            return self._json({"file": name})

        if p.startswith("/api/day/"):
            date = p[len("/api/day/"):]
            if not day_store.valid_date(date):
                return self._json({"error": "bad date"}, 400)
            data = (body or {}).get("day")
            if data is None:
                day_store.drop(uid, date)
            else:
                day_store.put(uid, date, dict(data))
            return self._json({"ok": True})

        # ---- торгова стратегія ----
        if p == "/api/ts":
            data = dict((body or {}).get("ts") or {})
            ts_store.put(uid, data)
            ts_store.sweep(uid, data, SHOTS)      # старі скріни за собою прибираємо
            return self._json({"ok": True})

        if p == "/api/ts/clear":
            ts_store.sweep(uid, {}, SHOTS)
            ts_store.clear(uid)
            return self._json({"ok": True})

        if p == "/api/ts/shot":
            try:
                name = ts_store.save_shot(uid, (body or {}).get("data") or "", SHOTS)
            except ValueError as e:
                return self._json({"error": str(e)}, 400)
            return self._json({"file": name})

        if p == "/api/ts/notion":
            try:
                draft = ts_notion.read((body or {}).get("url") or "", uid, SHOTS)
            except Exception as e:
                return self._json({"error": str(e) or "не вдалось прочитати сторінку"}, 400)
            return self._json({"ts": draft})

        if p == "/api/trades":
            if not isinstance(body, dict) or not str(body.get("pair", "")).strip():
                return self._json({"error": "bad json or empty pair"}, 400)
            t = clean_trade(body, new_id())
            save_screenshots(t)
            user = db.get_user(uid)
            ask = not str(t.get("emotion") or "").strip() and user["telegram_id"] is not None
            db.insert_trade(uid, t, "pending" if ask else "na")
            if ask:
                ask_emotion_later(user, t)
            return self._json(t, 201)

        if p == "/api/import":
            if body is None:
                return self._json({"error": "bad json"}, 400)
            items = body if isinstance(body, list) else body.get("trades") or []
            batch = []
            for it in items:
                if not isinstance(it, dict):
                    continue
                t = clean_trade(it, new_id())
                save_screenshots(t)
                batch.append(t)
            return self._json({"ok": True, "added": db.insert_trades(uid, batch)})

        self.send_response(404); self.end_headers()

    # ---------- PUT ----------
    def do_PUT(self):
        p = urlparse(self.path).path
        m = re.match(r"^/api/trades/([\w-]+)$", p)
        if not m:
            self.send_response(404); self.end_headers(); return
        uid = self._uid()
        if not uid:
            return self._json({"error": "auth required"}, 401)
        tid = m.group(1)
        body = self._body()
        if not isinstance(body, dict):
            return self._json({"error": "bad json"}, 400)
        old = db.get_trade(tid, uid)
        if not old:
            return self._json({"error": "not found"}, 404)
        t = clean_trade(body, tid)
        save_screenshots(t)
        old_files = {s["file"] for s in old.get("screenshots") or [] if s.get("file")}
        new_files = {s["file"] for s in t["screenshots"] if s.get("file")}
        db.update_trade(uid, t)
        delete_files(old_files - new_files)
        return self._json(t)

    # ---------- DELETE ----------
    def do_DELETE(self):
        p = urlparse(self.path).path
        m = re.match(r"^/api/trades/([\w-]+)$", p)
        if not m:
            self.send_response(404); self.end_headers(); return
        uid = self._uid()
        if not uid:
            return self._json({"error": "auth required"}, 401)
        tid = m.group(1)
        old = db.get_trade(tid, uid)
        if not old:
            return self._json({"error": "not found"}, 404)
        db.delete_trade(uid, tid)
        delete_files([s["file"] for s in old.get("screenshots") or [] if s.get("file")])
        return self._json({"ok": True})


if __name__ == "__main__":
    db.init()
    if config.RUN_BOT and config.BOT_TOKEN:
        # бот живе поруч із сайтом: на безкоштовному хостингу другий
        # процес тримати ніде, а опитування Телеграма нікому не заважає
        import bot
        threading.Thread(target=bot.main, daemon=True).start()
        print("Telegram bot -> у тому самому процесі")
    print("Trading Journal -> http://localhost:%d/  (Ctrl+C stop)" % PORT)
    ThreadingHTTPServer((config.HOST, PORT), H).serve_forever()

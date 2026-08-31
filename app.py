# -*- coding: utf-8 -*-
"""
Trading Journal — сервер журнала.
Только стандартная библиотека Python плюс драйвер Postgres. Запуск:  python app.py
Данные: Postgres (DATABASE_URL), скриншоты: data/screenshots/
"""
import base64
import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, unquote

import auth
import config
import db
import emotions
import tg_api
from calendar_feed import calendar_events

ROOT   = config.ROOT
STATIC = os.path.join(ROOT, "static")
DATA   = os.path.join(ROOT, "data")
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
    return t


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

        if p == "/api/auth/me":
            uid = self._uid()
            user = db.get_user(uid) if uid else None
            return self._json({"user": user_public(user) if user else None})

        if p == "/api/trades":
            uid = self._uid()
            if not uid:
                return self._json({"error": "auth required"}, 401)
            return self._json(db.list_trades(uid))

        if p == "/api/calendar":
            events, warn = calendar_events()
            return self._json({"events": events, "warning": warn})

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
            return self._file(os.path.join(SHOTS, name), ctype)

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
            added = 0
            for it in items:
                if not isinstance(it, dict):
                    continue
                t = clean_trade(it, new_id())
                save_screenshots(t)
                db.insert_trade(uid, t)
                added += 1
            return self._json({"ok": True, "added": added})

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
    print("Trading Journal -> http://localhost:%d/  (Ctrl+C stop)" % PORT)
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()

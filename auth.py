# -*- coding: utf-8 -*-
"""
Пароли (PBKDF2) и сессия в подписанной cookie — без таблицы сессий:
в самой cookie лежит id пользователя, срок и подпись.
"""
import base64
import hashlib
import hmac
import http.cookies
import os
import time

from config import ROOT, SESSION_SECRET

COOKIE = "statsai_session"
SESSION_TTL = 30 * 24 * 3600
PBKDF2_ITERS = 200_000
SECRET_FILE = os.path.join(ROOT, "data", ".session_secret")


_SECRET = None


def _secret():
    """Ключ підпису сесій. Змінна оточення → база (meta) → файл.

    У базі — бо на сервері папка data/ не переживає перезапуск чи
    перезбірку: ключ народжувався заново після кожного викладу, і всі
    входи злітали. База переживає все. Читаємо ліниво, на першому
    запиті: на момент імпорту таблиць ще може не бути."""
    global _SECRET
    if _SECRET:
        return _SECRET
    if SESSION_SECRET:
        _SECRET = SESSION_SECRET.encode("utf-8")
        return _SECRET
    try:
        import db
        val = db.meta_get("session_secret")
        if not val:
            val = os.urandom(32).hex()
            db.meta_set("session_secret", val)
        _SECRET = val.encode("utf-8")
        return _SECRET
    except Exception as ex:
        print("SESSION_SECRET: база недоступна (%s) — беру файл" % ex, flush=True)
    _SECRET = _file_secret()
    return _SECRET


def _file_secret():
    if not os.path.exists(SECRET_FILE):
        os.makedirs(os.path.dirname(SECRET_FILE), exist_ok=True)
        with open(SECRET_FILE, "w", encoding="utf-8") as f:
            f.write(os.urandom(32).hex())
        print("!" * 70)
        print("SESSION_SECRET не задан — сгенерирован временный ключ в data/.session_secret.")
        print("Для своей машины это нормально. На сервере — нет: там папка data/")
        print("живёт до перезапуска, ключ каждый раз новый, и все входы слетают.")
        print("На сервере задай переменную SESSION_SECRET (любая длинная случайная строка).")
        print("!" * 70)
    with open(SECRET_FILE, "r", encoding="utf-8") as f:
        return f.read().strip().encode("utf-8")


# -------------------------------------------------------------- пароли ----

def hash_password(password):
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERS)
    return digest.hex(), salt.hex(), PBKDF2_ITERS


def verify_password(password, pw_hash, pw_salt, iters):
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                 bytes.fromhex(pw_salt), iters)
    return hmac.compare_digest(digest, bytes.fromhex(pw_hash))


# ------------------------------------------------------------- сессия ----

def _sign(payload):
    return hmac.new(_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def make_session(user_id, ttl=SESSION_TTL):
    payload = "%d.%d" % (user_id, int(time.time()) + ttl)
    token = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")
    return token + "." + _sign(payload)


def read_session(value):
    if not value or "." not in value:
        return None
    token, sig = value.rsplit(".", 1)
    try:
        payload = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode("utf-8")
        uid, exp = payload.split(".")
        uid, exp = int(uid), int(exp)
    except Exception:
        return None
    if not hmac.compare_digest(sig, _sign(payload)):
        return None
    if exp < time.time():
        return None
    return uid


def is_https(handler):
    """Сайт стоит за прокси (Railway), поэтому схему берём из заголовка,
    который прокси подставляет. Своя машина ходит по http — там Secure
    не ставим, иначе Safari просто не сохранит куку."""
    proto = (handler.headers.get("X-Forwarded-Proto") or "").split(",")[0].strip().lower()
    return proto == "https"


def cookie_header(value, ttl=SESSION_TTL, secure=False):
    """Secure обязателен на https: без него браузер считает куку менее
    надёжной и охотнее выбрасывает её при чистке, а на телефоне чистка
    происходит куда чаще, чем на компьютере."""
    parts = ["%s=%s" % (COOKIE, value), "Path=/", "HttpOnly", "SameSite=Lax",
             "Max-Age=%d" % ttl]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def clear_cookie_header(secure=False):
    """Гасим куку теми же признаками, какими ставили: браузер считает
    куку с другим набором признаков другой кукой и старую не тронет."""
    return cookie_header("", ttl=0, secure=secure)


def current_user_id(handler):
    raw = handler.headers.get("Cookie")
    if not raw:
        return None
    try:
        jar = http.cookies.SimpleCookie()
        jar.load(raw)
    except Exception:
        return None
    morsel = jar.get(COOKIE)
    return read_session(morsel.value) if morsel else None

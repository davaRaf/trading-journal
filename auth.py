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


def _secret():
    if SESSION_SECRET:
        return SESSION_SECRET.encode("utf-8")
    if not os.path.exists(SECRET_FILE):
        os.makedirs(os.path.dirname(SECRET_FILE), exist_ok=True)
        with open(SECRET_FILE, "w", encoding="utf-8") as f:
            f.write(os.urandom(32).hex())
        print("SESSION_SECRET не задан — сгенерирован локальный ключ в data/.session_secret")
    with open(SECRET_FILE, "r", encoding="utf-8") as f:
        return f.read().strip().encode("utf-8")


SECRET = _secret()


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
    return hmac.new(SECRET, payload.encode("utf-8"), hashlib.sha256).hexdigest()


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


def cookie_header(value, ttl=SESSION_TTL):
    parts = ["%s=%s" % (COOKIE, value), "Path=/", "HttpOnly", "SameSite=Lax",
             "Max-Age=%d" % ttl]
    return "; ".join(parts)


def clear_cookie_header():
    return "%s=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0" % COOKIE


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

# -*- coding: utf-8 -*-
"""
Вхід через Google, Discord і Telegram.

Google і Discord — звичайний OAuth 2.0: людину відправляємо на сторінку
сервісу, той повертає її з кодом, код міняємо на профіль. Telegram —
свій віджет: він одразу віддає дані користувача, підписані ключем бота,
підпис ми й перевіряємо.

Хто вже заходив — впізнаємо по таблиці identities (сервіс + id у ньому).
Новому створюємо акаунт: пошта з профілю, а якщо сервіс її не дав
(Discord без дозволу, Telegram завжди) — службова, щоб рядок у users не
лишився порожнім. Пароль такому акаунту ставиться випадковий: заходити
він буде тим самим сервісом.

Ключі — з оточення: GOOGLE_CLIENT_ID/SECRET, DISCORD_CLIENT_ID/SECRET.
Telegram ключів не потребує — досить BOT_TOKEN, який уже є.
"""
import hashlib
import hmac
import json
import secrets
import time
import urllib.parse
import urllib.request

import auth
import config
import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS identities (
  provider   TEXT NOT NULL,
  ext_id     TEXT NOT NULL,
  user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  email      TEXT NOT NULL DEFAULT '',
  name       TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (provider, ext_id)
);
CREATE INDEX IF NOT EXISTS identities_user ON identities (user_id);
"""

_ready = False


def init():
    global _ready
    if _ready:
        return
    with db.connect() as conn:
        conn.execute(SCHEMA)
    _ready = True


PROVIDERS = {
    "google": {
        "auth": "https://accounts.google.com/o/oauth2/v2/auth",
        "token": "https://oauth2.googleapis.com/token",
        "me": "https://openidconnect.googleapis.com/v1/userinfo",
        "scope": "openid email profile",
    },
    "discord": {
        "auth": "https://discord.com/oauth2/authorize",
        "token": "https://discord.com/api/oauth2/token",
        "me": "https://discord.com/api/users/@me",
        "scope": "identify email",
    },
}


def creds(provider):
    if provider == "google":
        return config.GOOGLE_CLIENT_ID, config.GOOGLE_CLIENT_SECRET
    if provider == "discord":
        return config.DISCORD_CLIENT_ID, config.DISCORD_CLIENT_SECRET
    return "", ""


def enabled():
    """Які кнопки показувати на сторінці входу."""
    out = {}
    for p in PROVIDERS:
        cid, sec = creds(p)
        out[p] = bool(cid and sec)
    out["telegram"] = bool(config.BOT_TOKEN and config.BOT_USERNAME)
    return out


def callback_url(provider, base):
    return "%s/auth/%s/callback" % (base.rstrip("/"), provider)


# ------------------------------------------------------------ state ----
# Випадковий рядок їде і в посиланні, і в cookie: назад повернутись має
# той самий браузер, що й пішов. Підписуємо тим самим ключем, що й сесії.

def make_state():
    raw = secrets.token_urlsafe(16) + "." + str(int(time.time()))
    return raw + "." + auth._sign(raw)


def check_state(value, from_cookie):
    if not value or value != from_cookie:
        return False
    try:
        raw, sig = value.rsplit(".", 1)
        nonce, ts = raw.rsplit(".", 1)
    except ValueError:
        return False
    if not hmac.compare_digest(sig, auth._sign(raw)):
        return False
    return time.time() - int(ts) < 600           # десять хвилин на вхід


def state_cookie(value):
    return "oauth_state=%s; Path=/; Max-Age=600; HttpOnly; SameSite=Lax" % value


def clear_state_cookie():
    return "oauth_state=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax"


# ------------------------------------------------------------ OAuth ----

def start_url(provider, base):
    cid, _ = creds(provider)
    p = PROVIDERS[provider]
    state = make_state()
    q = {
        "client_id": cid,
        "redirect_uri": callback_url(provider, base),
        "response_type": "code",
        "scope": p["scope"],
        "state": state,
    }
    if provider == "google":
        q["access_type"] = "online"
        q["prompt"] = "select_account"
    return p["auth"] + "?" + urllib.parse.urlencode(q), state


def _post_form(url, data, headers=None):
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("Accept", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def _get_json(url, token):
    req = urllib.request.Request(url)
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Accept", "application/json")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_profile(provider, code, base):
    """Міняємо код на профіль. Повертає (ext_id, email, name)."""
    cid, sec = creds(provider)
    p = PROVIDERS[provider]
    tok = _post_form(p["token"], {
        "client_id": cid, "client_secret": sec, "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": callback_url(provider, base),
    })
    access = tok.get("access_token")
    if not access:
        raise ValueError("сервіс не віддав токен: %s" % tok.get("error_description", tok.get("error", "")))
    me = _get_json(p["me"], access)
    if provider == "google":
        return str(me.get("sub") or ""), str(me.get("email") or ""), str(me.get("name") or "")
    # discord
    name = me.get("global_name") or me.get("username") or ""
    email = me.get("email") if me.get("verified") else ""
    return str(me.get("id") or ""), str(email or ""), str(name)


# --------------------------------------------------------- Telegram ----

def telegram_profile(params):
    """Дані з віджета Telegram, перевірені підписом ключа бота.
    Повертає (ext_id, email, name) або кидає ValueError."""
    data = {k: v for k, v in params.items() if k != "hash" and v is not None}
    given = params.get("hash") or ""
    check = "\n".join("%s=%s" % (k, data[k]) for k in sorted(data))
    secret = hashlib.sha256(config.BOT_TOKEN.encode()).digest()
    want = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(want, given):
        raise ValueError("підпис Telegram не збігся")
    if time.time() - int(data.get("auth_date") or 0) > 600:
        raise ValueError("дані Telegram застаріли")
    name = " ".join(x for x in (data.get("first_name"), data.get("last_name")) if x) \
        or data.get("username") or "telegram"
    return str(data.get("id")), "", name, data.get("username") or ""


# ----------------------------------------------------- користувач ----

def _nickname_from(name, email, provider, ext_id):
    base = (name or (email.split("@")[0] if email else "") or provider).strip()
    base = "".join(ch for ch in base if ch.isalnum() or ch in "_- ").strip()[:24] or provider
    return base


def find_or_create_user(provider, ext_id, email, name, tg_username=""):
    """Повертає рядок users. Спершу шукаємо прив'язку, потім людину з такою
    поштою (щоб не плодити другий акаунт), і лише тоді створюємо нового."""
    init()
    with db.connect() as conn:
        row = conn.execute("SELECT user_id FROM identities WHERE provider=%s AND ext_id=%s",
                           (provider, ext_id)).fetchone()
    if row:
        user = db.get_user(row["user_id"])
        if user:
            return user

    user = None
    if email:
        with db.connect() as conn:
            u = conn.execute("SELECT id FROM users WHERE email_norm=%s",
                             (email.strip().lower(),)).fetchone()
        if u:
            user = db.get_user(u["id"])

    if not user:
        use_email = email or "%s_%s@login.statsai" % (provider, ext_id)
        pw_hash, pw_salt, iters = auth.hash_password(secrets.token_urlsafe(24))
        nick = _nickname_from(name, email, provider, ext_id)
        for attempt in range(6):
            try:
                user = db.create_user(use_email, nick if attempt == 0 else "%s-%s" % (nick, secrets.token_hex(2)),
                                      pw_hash, pw_salt, iters)
                break
            except Exception as ex:
                if "unique" not in str(ex).lower() and "duplicate" not in str(ex).lower():
                    raise
        if not user:
            raise ValueError("не вдалось створити акаунт")

    with db.connect() as conn:
        conn.execute("INSERT INTO identities (provider, ext_id, user_id, email, name) "
                     "VALUES (%s,%s,%s,%s,%s) ON CONFLICT (provider, ext_id) DO NOTHING",
                     (provider, ext_id, user["id"], email or "", name or ""))
        # вхід через Telegram — це й прив'язка бота: нагадування підуть одразу
        if provider == "telegram" and user.get("telegram_id") is None:
            try:
                conn.execute("UPDATE users SET telegram_id=%s, telegram_username=%s "
                             "WHERE id=%s AND telegram_id IS NULL",
                             (int(ext_id), tg_username or None, user["id"]))
            except Exception:
                pass
    return db.get_user(user["id"]) or user

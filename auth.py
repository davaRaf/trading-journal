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
import threading
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


def make_session(user_id, ttl=SESSION_TTL, gen=0):
    """Кука входу: хто, до коли і якого покоління (див. current_gen)."""
    payload = "%d.%d.%d" % (user_id, int(time.time()) + ttl, int(gen or 0))
    token = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")
    return token + "." + _sign(payload)


def parse_session(value):
    """(uid, покоління) з підписаної куки або None.

    Куки, видані до появи поколінь, мають лише «uid.exp» — вважаємо їх
    поколінням 0: після викладу нікого не викине, доки людина сама не
    змінить пароль чи не натисне «вийти на всіх пристроях»."""
    if not value or "." not in value:
        return None
    token, sig = value.rsplit(".", 1)
    try:
        payload = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode("utf-8")
        parts = payload.split(".")
        if len(parts) == 2:
            uid, exp, gen = int(parts[0]), int(parts[1]), 0
        elif len(parts) == 3:
            uid, exp, gen = int(parts[0]), int(parts[1]), int(parts[2])
        else:
            return None
    except Exception:
        return None
    if not hmac.compare_digest(sig, _sign(payload)):
        return None
    if exp < time.time():
        return None
    return uid, gen


def read_session(value):
    """Лише підпис і строк. Покоління звіряє current_user_id."""
    got = parse_session(value)
    return got[0] if got else None


# ------------------------------------------------------ покоління входів ----
# Номер покоління живе в базі (users.session_gen). Щоб не питати базу на
# кожен запит, тримаємо його в пам'яті. Процес у нас один, і міняє номер
# теж він (bump_gen) — тож пам'ять оновлюється в ту ж мить. Строк у пам'яті
# лише про запас: якщо номер колись змінять повз цей код.

GEN_TTL = 60
_gen_lock = threading.Lock()
_gens = {}                      # uid -> (покоління або None, коли спитали)


def current_gen(user_id):
    now = time.time()
    with _gen_lock:
        got = _gens.get(user_id)
    if got and now - got[1] < GEN_TTL:
        return got[0]
    try:
        import db
        gen = db.session_gen(user_id)
    except Exception:
        # База не відповіла: беремо, що пам'ятали. Не пам'ятали нічого —
        # пускаємо: сайт без бази однаково не працює, а викидати всіх зі
        # входу через хвилинний збій — гірше.
        return got[0] if got else "?"
    with _gen_lock:
        if len(_gens) > 20000:
            _gens.clear()
        _gens[user_id] = (gen, now)
    return gen


def bump_gen(user_id):
    """+1 до покоління: усі інші пристрої вилітають. Повертає новий номер."""
    import db
    gen = db.bump_session_gen(user_id)
    with _gen_lock:
        _gens[user_id] = (gen, time.time())
    return gen


# --------------------------------------------- проміжні ключі для 2FA ----
# Пароль правильний, але код ще не введено — повну куку не даємо. Даємо
# «пропуск на другий крок»: живе 10 хвилин і входом не є. Підпис той самий
# ключ, але з іншою приставкою — сесією його не підробиш і навпаки.

PENDING_COOKIE = "statsai_2fa"
PENDING_TTL = 600
SETUP_TTL = 900


def _pack(kind, fields):
    payload = ".".join(str(f) for f in fields)
    token = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")
    return token + "." + _sign(kind + "|" + payload)


def _unpack(kind, value, n):
    if not value or "." not in value:
        return None
    token, sig = value.rsplit(".", 1)
    try:
        payload = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode("utf-8")
    except Exception:
        return None
    if not hmac.compare_digest(sig, _sign(kind + "|" + payload)):
        return None
    parts = payload.split(".")
    if len(parts) != n:
        return None
    try:
        if int(parts[1]) < time.time():
            return None
    except ValueError:
        return None
    return parts


def make_pending(user_id, gen):
    return _pack("2fa-login", (int(user_id), int(time.time()) + PENDING_TTL, int(gen or 0)))


def read_pending(value):
    """uid, якщо пропуск справжній, не протермінований і покоління те саме."""
    parts = _unpack("2fa-login", value, 3)
    if not parts:
        return None
    uid, gen = int(parts[0]), int(parts[2])
    return uid if current_gen(uid) in (gen, "?") else None


def pending_cookie(value, secure=False):
    parts = ["%s=%s" % (PENDING_COOKIE, value), "Path=/", "HttpOnly", "SameSite=Lax",
             "Max-Age=%d" % (PENDING_TTL if value else 0)]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def make_setup(user_id, secret):
    """Ключ нового застосунку до підтвердження: у базу — лише після коду."""
    return _pack("2fa-setup", (int(user_id), int(time.time()) + SETUP_TTL, secret))


def read_setup(value, user_id):
    parts = _unpack("2fa-setup", value, 3)
    if not parts or parts[0] != str(int(user_id)):
        return None
    return parts[2]


# ---- підтвердження пошти кодом ----
# Після реєстрації (чи входу з непідтвердженою поштою) сесії ще немає —
# є лише пропуск на крок «введи код із листа». Живе довше за сам код:
# людина може попросити новий лист і не починати все спочатку.
MAILCODE_COOKIE = "statsai_mail"
MAILCODE_TTL = 3600


def make_mailcode(user_id):
    return _pack("mail-code", (int(user_id), int(time.time()) + MAILCODE_TTL))


def read_mailcode(value):
    parts = _unpack("mail-code", value, 2)
    return int(parts[0]) if parts else None


def mailcode_cookie(value, secure=False):
    parts = ["%s=%s" % (MAILCODE_COOKIE, value), "Path=/", "HttpOnly", "SameSite=Lax",
             "Max-Age=%d" % (MAILCODE_TTL if value else 0)]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


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


def read_cookie(handler, name):
    raw = handler.headers.get("Cookie")
    if not raw:
        return None
    try:
        jar = http.cookies.SimpleCookie()
        jar.load(raw)
    except Exception:
        return None
    morsel = jar.get(name)
    return morsel.value if morsel else None


def current_user_id(handler):
    got = parse_session(read_cookie(handler, COOKIE))
    if not got:
        return None
    uid, gen = got
    now = current_gen(uid)
    if now == "?":             # база мовчить — див. current_gen
        return uid
    return uid if now == gen else None

# -*- coding: utf-8 -*-
"""
Двофакторний вхід: код із застосунку (Google Authenticator, Authy, 1Password).

Код рахується за RFC 6238 (TOTP): ключ + поточні 30 секунд → шість цифр.
Застосунок і сервер рахують однаково, тому код збігається без зв'язку між
ними. Бібліотеку не тягнемо: алгоритм — десяток рядків стандартної
бібліотеки, а зайва залежність — це ще один крок на кожному сервері.

Запасні коди — на випадок, коли телефону немає під рукою. Кожен одноразовий,
у базі лежать лише їхні відбитки.
"""
import base64
import hashlib
import hmac
import secrets
import struct
import time
import urllib.parse

import db

STEP = 30               # секунд на один код
DIGITS = 6
WINDOW = 1              # скільки сусідніх кроків приймаємо: годинник телефона буває неточний
BACKUP_COUNT = 10
ISSUER = "StatsAI"


# ----------------------------------------------------------------- TOTP ----

def new_secret():
    """20 випадкових байтів у base32 — стандартна довжина для застосунків."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _key(secret):
    s = (secret or "").strip().replace(" ", "").upper()
    return base64.b32decode(s + "=" * (-len(s) % 8))


def code_at(secret, step, digits=DIGITS, algo=hashlib.sha1):
    """Код для конкретного кроку часу (RFC 4226, динамічне обрізання)."""
    h = hmac.new(_key(secret), struct.pack(">Q", int(step)), algo).digest()
    o = h[-1] & 0x0F
    n = (struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(n).zfill(digits)


def now_step(t=None):
    return int((time.time() if t is None else t) // STEP)


def match_step(secret, code, t=None):
    """Крок, якому відповідає код, або None. Сусідні кроки теж рахуються."""
    code = clean_code(code)
    if len(code) != DIGITS or not code.isdigit() or not secret:
        return None
    base = now_step(t)
    for d in range(-WINDOW, WINDOW + 1):
        if hmac.compare_digest(code_at(secret, base + d), code):
            return base + d
    return None


def uri(secret, account):
    """otpauth:// — з нього застосунок бере ключ (QR або дотик на телефоні)."""
    label = urllib.parse.quote("%s:%s" % (ISSUER, account))
    q = urllib.parse.urlencode({"secret": secret, "issuer": ISSUER,
                                "algorithm": "SHA1", "digits": DIGITS, "period": STEP})
    return "otpauth://totp/%s?%s" % (label, q)


# ------------------------------------------------------- запасні коди ----

def clean_code(code):
    return "".join(ch for ch in str(code or "") if ch.isalnum()).lower()


def backup_hash(code):
    return hashlib.sha256(("statsai-backup|" + clean_code(code)).encode("utf-8")).hexdigest()


def new_backup_codes(n=BACKUP_COUNT):
    """Коди виду «a1b2c-3d4e5»: 40 біт випадковості, читаються без плутанини."""
    out = []
    for _ in range(n):
        raw = secrets.token_hex(5)
        out.append(raw[:5] + "-" + raw[5:])
    return out


# --------------------------------------------------------- перевірка ----

def verify(user, code):
    """Пропустити людину з кодом. Повертає (чи пройшло, скільки запасних лишилось
    або None, якщо спрацював код застосунку)."""
    if not user or not user.get("twofa_secret"):
        return False, None
    step = match_step(user["twofa_secret"], code)
    if step is not None:
        # той самий код удруге не пройде, поки він ще живий
        return db.twofa_take_step(user["id"], step), None
    c = clean_code(code)
    if len(c) == 10:
        left = db.twofa_take_backup(user["id"], backup_hash(c))
        if left is not None:
            return True, left
    return False, None


def enabled(user):
    return bool(user and user.get("twofa_secret"))

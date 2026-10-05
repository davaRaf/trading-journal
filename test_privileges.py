# -*- coding: utf-8 -*-
"""
Чужі права: python test_privileges.py

Перевіряємо не «чи працює», а «чи не дає зайвого»:

* службові сторінки закриті — і закриті кожна, а не «здебільшого»;
* кука входу не підробляється, підпис платіжки без секрета не приймається;
* у відповіді про людину немає нічого, крім того, що вона й так бачить;
* угода дістається тільки разом із хазяїном;
* сервер не розповідає, якої він версії.

Ніки власників тут не менш важливі за паролі: права адміна дає збіг ніка,
тому перевіряємо, що такий нік не віддається нікому — ні в іншому регістрі,
ні з пробілами по краях.

Бази не треба: дивимось на код і на чисті функції.
"""
import io
import os
import re

os.environ.setdefault("DATABASE_URL", "postgresql://x/y")
os.environ.setdefault("SESSION_SECRET", "test-secret-for-privileges")

import app
import auth
import config
import creem
import db


def check(name, cond):
    print("  %-4s  %s" % ("ok" if cond else "ПАДАЄ", name))
    assert cond, name


def admin_routes_guarded():
    """Кожна службова адреса питає, хто прийшов. Не «більшість» — кожна."""
    src = io.open("app.py", encoding="utf-8").read().split("\n")
    route = re.compile(r'^\s+if p\s*(?:==\s*|\.startswith\()\s*"(/admin[^"]*|/api/admin[^"]*)"')
    found = 0
    for i, line in enumerate(src):
        m = route.match(line)
        if not m:
            continue
        found += 1
        block = "\n".join(src[i:i + 14])
        # або звіряємо, хто це, або ключ із оточення (разова заливка)
        ok = "_is_admin" in block or "compare_digest" in block
        check("закрито: %s" % m.group(1), ok)
    check("службові адреси взагалі знайшлись", found >= 4)


def owner_nick_is_taken():
    """Нік власника не віддається нікому — права адміна дає саме він."""
    for nick in config.ADMIN_NICKS:
        check("зайнято: %r" % nick, config.nick_reserved(nick))
        check("зайнято в іншому регістрі: %r" % nick, config.nick_reserved(nick.upper()))
        check("зайнято з пробілами: %r" % nick, config.nick_reserved("  " + nick + " "))
    check("службовий нік теж зайнятий", config.nick_reserved("admin"))
    check("звичайний нік вільний", not config.nick_reserved("trader7"))


def session_not_forged():
    """Куку входу не переписати руками: підпис не зійдеться."""
    good = auth.make_session(42)
    check("своя кука читається", auth.read_session(good) == 42)
    token, sig = good.rsplit(".", 1)
    check("чужий підпис не проходить", auth.read_session(token + ".deadbeef") is None)
    check("порожнє не проходить", auth.read_session("") is None)
    # підміна номера людини: беремо чужий id, підпис лишаємо свій
    import base64
    payload = "1.99999999999.0"
    fake = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=") + "." + sig
    check("чужий id із своїм підписом не проходить", auth.read_session(fake) is None)
    old = auth.make_session(42, ttl=-10)
    check("прострочена кука не проходить", auth.read_session(old) is None)


def webhook_needs_secret():
    """Підтвердження оплати без підпису — не підтвердження."""
    was = creem.CREEM_WEBHOOK_SECRET
    try:
        creem.CREEM_WEBHOOK_SECRET = ""
        check("без секрета не віримо нікому", not creem.verify(b"{}", "abc"))
        creem.CREEM_WEBHOOK_SECRET = "s3cret"
        check("без підпису не віримо", not creem.verify(b"{}", ""))
        check("з чужим підписом не віримо", not creem.verify(b"{}", "00" * 32))
        import hashlib
        import hmac as _hmac
        right = _hmac.new(b"s3cret", b"{}", hashlib.sha256).hexdigest()
        check("свій підпис приймаємо", creem.verify(b"{}", right))
    finally:
        creem.CREEM_WEBHOOK_SECRET = was


def profile_keeps_secrets():
    """У відповіді про людину немає ні пароля, ні ключа 2FA."""
    user = {"id": 1, "email": "a@b.c", "nickname": "n", "telegram_username": None,
            "telegram_id": None, "digest_hour": 8, "digest_minute": 0,
            "digest_enabled": True, "public_journal": False, "tz": None,
            "email_confirmed_at": None, "avatar": None,
            "twofa_secret": "JBSWY3DPEHPK3PXP", "twofa_backup": ["хеш"],
            "pw_hash": "деадбіф", "pw_salt": "сіль", "pw_iters": 200000,
            "session_gen": 0}
    out = app.user_public(user)
    plain = repr(out)
    for bad in ("pw_hash", "pw_salt", "twofa_secret", "session_gen"):
        check("назовні не йде %s" % bad, bad not in out)
    check("сам ключ 2FA теж не просочився", "JBSWY3DPEHPK3PXP" not in plain)
    check("пароль теж", "деадбіф" not in plain)
    check("скільки резервних кодів лишилось — можна", out["twofa_backup_left"] == 1)


def trade_needs_owner():
    """Угоду не дістати за самим id: хазяїн — обов'язковий."""
    import inspect
    sig = inspect.signature(db.get_trade)
    p = sig.parameters.get("user_id")
    check("у get_trade є хазяїн", p is not None)
    check("і його не можна не передати", p.default is inspect.Parameter.empty)
    try:
        db.get_trade("t1")
        ok = False
    except TypeError:
        ok = True
    check("без хазяїна викликати не вийде", ok)


def server_stays_quiet():
    """Сервер не називає версію мови — з цього починають підбір діри."""
    check("своя назва", app.H.server_version == "StatsAI")
    check("версія мови не їде", app.H.sys_version == "")
    line = app.H.version_string(app.H)
    check("у підписі немає слова Python", "Python" not in line)


def main():
    print("службові сторінки")
    admin_routes_guarded()
    print("нік власника")
    owner_nick_is_taken()
    print("кука входу")
    session_not_forged()
    print("підпис платіжки")
    webhook_needs_secret()
    print("профіль")
    profile_keeps_secrets()
    print("чужа угода")
    trade_needs_owner()
    print("підпис сервера")
    server_stays_quiet()
    print("\nвсе гаразд")


if __name__ == "__main__":
    main()

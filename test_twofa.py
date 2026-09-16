# -*- coding: utf-8 -*-
"""2FA і покоління входів: коди застосунку, запасні коди, куки, пропуски.

База не потрібна: там, де код ходить у базу, підставляємо свою пам'ять.
"""
import base64
import hashlib
import os
import time

os.environ.setdefault("SESSION_SECRET", "x" * 40)

import auth
import db
import twofa


def check(name, cond):
    print("  %-4s  %s" % ("ok" if cond else "ПАДАЄ", name))
    assert cond, name


def check_rfc():
    """Офіційні вектори RFC 6238 (додаток B): застосунок і ми рахуємо однаково."""
    secret = base64.b32encode(b"12345678901234567890").decode()
    for t, want in ((59, "94287082"), (1111111109, "07081804"), (1111111111, "14050471"),
                    (1234567890, "89005924"), (2000000000, "69279037"), (20000000000, "65353130")):
        got = twofa.code_at(secret, t // 30, digits=8)
        check("RFC 6238, T=%d → %s" % (t, want), got == want)
    check("шість цифр — хвіст восьми", twofa.code_at(secret, 59 // 30) == "287082")


def check_match():
    s = twofa.new_secret()
    t = 1_700_000_000
    step = twofa.now_step(t)
    check("новий ключ — 32 символи base32, 20 байтів", len(s) == 32 and len(twofa._key(s)) == 20)
    check("свій крок підходить", twofa.match_step(s, twofa.code_at(s, step), t) == step)
    check("сусідній крок теж (годинник телефона)", twofa.match_step(s, twofa.code_at(s, step - 1), t) == step - 1)
    check("два кроки тому — ні", twofa.match_step(s, twofa.code_at(s, step - 2), t) is None)
    check("пробіли в коді не заважають", twofa.match_step(s, " ".join(twofa.code_at(s, step)), t) == step)
    check("літери замість цифр — ні", twofa.match_step(s, "abcdef", t) is None)
    check("порожнє — ні", twofa.match_step(s, "", t) is None)
    u = twofa.uri(s, "trader@mail.com")
    check("otpauth-посилання з ключем і назвою",
          u.startswith("otpauth://totp/StatsAI%3Atrader%40mail.com?") and "secret=" + s in u)


def check_backup():
    codes = twofa.new_backup_codes()
    check("десять запасних кодів", len(codes) == 10 and len(set(codes)) == 10)
    check("формат xxxxx-xxxxx", all(len(c) == 11 and c[5] == "-" for c in codes))
    c = codes[0]
    check("відбиток не залежить від дефіса й регістру",
          twofa.backup_hash(c) == twofa.backup_hash(c.replace("-", "").upper()))
    check("у відбитку немає самого коду", c.replace("-", "") not in twofa.backup_hash(c))


def check_verify():
    """Той самий код удруге не проходить; запасний — один раз."""
    s = twofa.new_secret()
    mem = {"last": None, "backup": {twofa.backup_hash("aaaaa-bbbbb")}}

    def take_step(uid, step):
        if mem["last"] is not None and mem["last"] >= step:
            return False
        mem["last"] = step
        return True

    def take_backup(uid, h):
        if h not in mem["backup"]:
            return None
        mem["backup"].discard(h)
        return len(mem["backup"])

    real = db.twofa_take_step, db.twofa_take_backup
    db.twofa_take_step, db.twofa_take_backup = take_step, take_backup
    try:
        user = {"id": 1, "twofa_secret": s}
        code = twofa.code_at(s, twofa.now_step())
        check("код із застосунку впускає", twofa.verify(user, code) == (True, None))
        check("той самий код удруге — ні", twofa.verify(user, code)[0] is False)
        check("чужий код — ні", twofa.verify(user, "000000" if code != "000000" else "111111")[0] is False)
        check("запасний код впускає й каже, скільки лишилось",
              twofa.verify(user, "AAAAA-BBBBB") == (True, 0))
        check("запасний код удруге — ні", twofa.verify(user, "aaaaa-bbbbb")[0] is False)
        check("без 2FA verify нікого не впускає", twofa.verify({"id": 2, "twofa_secret": None}, code)[0] is False)
    finally:
        db.twofa_take_step, db.twofa_take_backup = real


def check_sessions():
    """Покоління входів у куці й звірка з тим, що в базі."""
    gens = {7: 3}
    real = db.session_gen
    db.session_gen = lambda uid: gens.get(uid)
    auth._gens.clear()
    try:
        new = auth.make_session(7, gen=3)
        check("нова кука несе покоління", auth.parse_session(new) == (7, 3))

        # кука старого формату «uid.exp» — як видавали до цього оновлення
        payload = "%d.%d" % (7, int(time.time()) + 3600)
        old = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=") + "." + auth._sign(payload)
        check("стара кука читається як покоління 0", auth.parse_session(old) == (7, 0))
        check("read_session як і раніше віддає лише id", auth.read_session(new) == 7)

        class H:
            def __init__(self, cookie):
                self.headers = {"Cookie": "%s=%s" % (auth.COOKIE, cookie)}

        check("кука поточного покоління пускає", auth.current_user_id(H(new)) == 7)
        check("кука старшого покоління — ні", auth.current_user_id(H(auth.make_session(7, gen=2))) is None)

        gens[7] = 0
        auth._gens.clear()
        check("стара кука пускає, поки покоління 0", auth.current_user_id(H(old)) == 7)

        # «вийти на всіх пристроях»: bump_gen оновлює пам'ять одразу
        db_bump = db.bump_session_gen
        db.bump_session_gen = lambda uid: gens.__setitem__(uid, gens[uid] + 1) or gens[uid]
        try:
            g = auth.bump_gen(7)
            check("після виходу скрізь стара кука не пускає — одразу", auth.current_user_id(H(old)) is None)
            check("нова кука цього пристрою пускає", auth.current_user_id(H(auth.make_session(7, gen=g))) == 7)
        finally:
            db.bump_session_gen = db_bump

        gens.pop(7)
        auth._gens.clear()
        check("видаленого акаунта кука не пускає", auth.current_user_id(H(new)) is None)
        check("підробка підпису — ні", auth.parse_session(new[:-1] + ("0" if new[-1] != "0" else "1")) is None)
    finally:
        db.session_gen = real
        auth._gens.clear()


def check_tokens():
    gens = {5: 1}
    real = db.session_gen
    db.session_gen = lambda uid: gens.get(uid)
    auth._gens.clear()
    try:
        p = auth.make_pending(5, 1)
        check("пропуск на другий крок читається", auth.read_pending(p) == 5)
        check("пропуск — не кука входу", auth.parse_session(p) is None)
        check("кука входу — не пропуск", auth.read_pending(auth.make_session(5, gen=1)) is None)
        gens[5] = 2
        auth._gens.clear()
        check("після виходу скрізь старий пропуск не діє", auth.read_pending(p) is None)

        s = auth.make_setup(5, "ABCDEFGHIJKLMNOP")
        check("ключ налаштування повертається своїй людині", auth.read_setup(s, 5) == "ABCDEFGHIJKLMNOP")
        check("чужій — ні", auth.read_setup(s, 6) is None)
        check("ключ налаштування — не пропуск", auth.read_pending(s) is None)
        expired = auth._pack("2fa-login", (5, int(time.time()) - 1, 2))
        check("протермінований пропуск — ні", auth.read_pending(expired) is None)
    finally:
        db.session_gen = real
        auth._gens.clear()


check_rfc()
check_match()
check_backup()
check_verify()
check_sessions()
check_tokens()
print("\nусе добре")

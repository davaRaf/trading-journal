# -*- coding: utf-8 -*-
"""Порція диктувань: скільки дають, коли відмовляють, коли оновлюється."""
import datetime
import os
import sys

sys.path.insert(0, os.getcwd())

import billing
import config
import db

fails = []


def case(name, got, want):
    ok = got == want
    print(("  ok  " if ok else "ПОМИЛКА") + "  " + name +
          ("" if ok else "  → отримали %r, чекали %r" % (got, want)))
    if not ok:
        fails.append(name)


def main():
    print("порція на безкоштовному: %d" % config.FREE_VOICE)
    tag = "vq_%d" % int(datetime.datetime.now().timestamp())
    uid = db.create_user(tag + "@example.com", tag, "h", "s", 1)["id"]
    try:
        print("\nбез підписки дають рівно порцію")
        case("спершу можна", billing.can_voice(uid), (True, ""))
        case("витрачено нуль", billing.voice_used(uid), 0)
        for i in range(config.FREE_VOICE):
            billing.spend_voice(uid)
        case("витрачено все", billing.voice_used(uid), config.FREE_VOICE)
        case("більше не можна", billing.can_voice(uid),
             (False, billing.VOICE_LIMIT))
        case("привід той самий, що на фронті", billing.VOICE_LIMIT, "voice_limit")

        print("\nвідмова має формат плашки")
        d = billing.deny(uid, billing.VOICE_LIMIT)
        case("код для api()", d.get("code"), "need_sub")
        case("привід усередині", d.get("reason"), "voice_limit")

        print("\nпідписка знімає межу й нічого не витрачає")
        billing.grant(uid, 30, "month")
        case("можна попри вичерпану порцію", billing.can_voice(uid), (True, ""))
        was = billing.voice_used(uid)
        billing.spend_voice(uid)
        case("лічильник не ворухнувся", billing.voice_used(uid), was)

        print("\nвікно минуло — порція нова")
        billing.revoke(uid)
        with db.connect() as conn:
            conn.execute("UPDATE users SET voice_reset_at = now() - interval "
                         "'1 day' WHERE id=%s", (uid,))
            conn.commit()
        case("витрачене забулось", billing.voice_used(uid), 0)
        case("знову можна", billing.can_voice(uid), (True, ""))
        billing.spend_voice(uid)
        case("перше диктування почало нове вікно",
             billing.voice_used(uid), 1)

        print("\nадмін може дати більше руками")
        with db.connect() as conn:
            conn.execute("UPDATE users SET voice_cap = 99, voice_used = 50 "
                         "WHERE id=%s", (uid,))
            conn.commit()
        case("своя стеля важливіша за загальну",
             billing.can_voice(uid), (True, ""))
    finally:
        with db.connect() as conn:
            conn.execute("DELETE FROM users WHERE id=%s", (uid,))
            conn.commit()
        print("  ok    тимчасового користувача прибрано")

    print("\n" + ("усе добре" if not fails
                  else "є помилки: " + ", ".join(fails)))
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())

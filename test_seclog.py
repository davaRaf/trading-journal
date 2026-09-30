# -*- coding: utf-8 -*-
"""
Слід безпеки: python test_seclog.py

Перевіряємо дві речі, і друга важливіша за першу:

1. подія взагалі записується — одним рядком, який видно в journalctl;
2. у ній немає нічого, чого там бути не повинно: пароля, коду,
   куки, повної пошти.

Слід читатимуть, коли буде погано, і читати його, найімовірніше, буде не
лише власник — тому зайвого в ньому лежати не має.
"""
import io
import sys

import seclog


def check(name, cond):
    print("  %-4s  %s" % ("ok" if cond else "ПАДАЄ", name))
    assert cond, name


def caught(*args, **kw):
    """Що саме надрукувалось."""
    was = sys.stdout
    sys.stdout = buf = io.StringIO()
    try:
        seclog.event(*args, **kw)
    finally:
        sys.stdout = was
    return buf.getvalue().strip()


USER = {"id": 7, "nickname": "trader7", "email": "danylo@gmail.com"}


def writes_one_line():
    line = caught("вхід", True, user=USER, ip="1.2.3.4")
    check("рядок один", line.count("\n") == 0)
    check("подія названа", "вхід" in line)
    check("видно, що вийшло", " ok" in line)
    check("є номер людини", "uid=7" in line)
    check("є адреса", "ip=1.2.3.4" in line)
    check("є мітка для пошуку", line.startswith(seclog.TAG))


def failures_stand_out():
    line = caught("вхід", False, login="danylo@gmail.com", ip="9.9.9.9")
    check("невдачу видно здалеку", "ЗБІЙ" in line)
    check("пошта обрізана", "danylo@gmail.com" not in line)
    check("але свою впізнаєш", "d***@gmail.com" in line)


def keeps_quiet_about_secrets():
    """Головне: у слід не можна занести те, чого ми не знаємо напам'ять."""
    line = caught("вхід", True, user=USER, ip="1.2.3.4")
    for bad in ("pw_hash", "пароль=", "code=", "cookie", "danylo@gmail.com"):
        check("у сліді немає %r" % bad, bad not in line)
    check("маска без пошти взагалі", seclog.mask("") == "—")
    check("маска для ніка без собачки", seclog.mask("trader7").endswith("***"))


def never_breaks_the_request():
    """Слід — не привід завалити запит: що б не сталось, далі йдемо."""
    class Bad:
        def __str__(self):
            raise RuntimeError("зіпсоване значення")
    ok = True
    try:
        caught("вхід", True, user=USER, дивне=Bad())
    except Exception:
        ok = False
    check("падіння всередині не виривається назовні", ok)


def main():
    print("рядок сліду")
    writes_one_line()
    print("невдачі")
    failures_stand_out()
    print("секрети")
    keeps_quiet_about_secrets()
    print("надійність")
    never_breaks_the_request()
    print("\nвсе гаразд")


if __name__ == "__main__":
    main()

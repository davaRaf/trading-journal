# -*- coding: utf-8 -*-
"""
Перенесення вже записаних угод на рахунок: python test_attach.py

Перевіряємо `db.assign_sql` — умови, за якими правка знаходить угоди.
Це єдина гуртова правка чужих записів у журналі, і відкотити її можна
лише таким самим перенесенням назад. Тому дивимось саме на межі:

  • бектест не має потрапляти під правку взагалі;
  • період без меж означає «за весь час», а не «нічого»;
  • сам рахунок не може бути джерелом — інакше правка переписала б
    його ж угоди їхніми ж іменами й порахувала це за роботу.

Бази не треба: `assign_sql` тільки збирає запит.
"""
import os

os.environ.setdefault("DATABASE_URL", "postgresql://x/y")

import db


def case(name, got, want):
    ok = got == want
    print(("  ok  " if ok else "ПОМИЛКА") + "  " + name +
          ("" if ok else "\n        отримали %r\n        чекали   %r" % (got, want)))
    return ok


def main():
    ok = True

    # --- нічого робити ---
    ok &= case("порожній список джерел — запиту немає",
               db.assign_sql(1, "FTMO", [])[0], None)
    ok &= case("сам рахунок джерелом бути не може",
               db.assign_sql(1, "FTMO", ["FTMO"])[0], None)
    ok &= case("рахунок відсіюється, решта лишається",
               db.assign_sql(1, "FTMO", ["FTMO", ""])[1][2], [""])

    # --- бектест ---
    sql, args = db.assign_sql(1, "FTMO", [""])
    ok &= case("бектест під правку не потрапляє", '"kind"=%s' in sql, True)
    ok &= case("і саме реальні угоди", args[3], "")

    # --- період ---
    sql, args = db.assign_sql(7, "FTMO", [""])
    ok &= case("без дат меж у запиті немає", "left(" in sql, False)
    ok &= case("без дат аргументів рівно чотири", len(args), 4)

    sql, args = db.assign_sql(7, "FTMO", [""], "2026-08-01", "")
    ok &= case("тільки нижня межа", sql.count("left("), 1)
    ok &= case("і вона на місці", args[-1], "2026-08-01")
    ok &= case("нижня межа включно", '>= %s' in sql, True)

    sql, args = db.assign_sql(7, "FTMO", [""], "", "2026-08-31")
    ok &= case("тільки верхня межа", sql.count("left("), 1)
    ok &= case("верхня межа включно", "<= %s" in sql, True)

    sql, args = db.assign_sql(7, "FTMO", ["", "Стар"], "2026-08-01", "2026-08-31")
    ok &= case("обидві межі", sql.count("left("), 2)
    ok &= case("порядок аргументів: куди, хто, звідки, режим, з, по",
               args, ["FTMO", 7, ["", "Стар"], "", "2026-08-01", "2026-08-31"])
    ok &= case("плейсхолдерів стільки ж, скільки аргументів",
               sql.count("%s"), len(args))

    # --- дрібниці ---
    ok &= case("None замість списку не падає",
               db.assign_sql(1, "FTMO", None)[0], None)

    print("\n" + ("Усе зійшлось." if ok else "Є розбіжності."))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

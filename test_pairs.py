# -*- coding: utf-8 -*-
"""
Один інструмент — одне написання: python test_pairs.py

Поле інструмента вільне: сьогодні «GER40», завтра «ger 40» — і в статистиці
це два різні інструменти. Перед записом підставляємо те написання, яке в
журналі вже є (db.py: _one_spelling). Головне тут — не «звели», а «не звели
зайвого»: «US30» і «US100» мусять лишитись різними.

Бази не треба: з'єднання підмінене, перевіряємо саме правило.
"""
import os

os.environ.setdefault("DATABASE_URL", "postgresql://x/y")

import db


class Conn:
    """З'єднання-заглушка: віддає, як інструменти записані в журналі."""

    def __init__(self, journal=()):
        self.journal = [{"p": p, "n": n} for p, n in journal]
        self.sql = ""

    def execute(self, sql, args=None):
        self.sql = sql
        return self

    def fetchall(self):
        return self.journal


def canon(value, journal=(), skip_id=None):
    t = {"pair": value, "id": "t1"}
    db._one_spelling(Conn(journal), "u1", [t], skip_id=skip_id)
    return t["pair"]


def case(name, got, want):
    ok = got == want
    print(("  ok  " if ok else "ПОМИЛКА") + "  " + name +
          ("" if ok else "  → отримали %r, чекали %r" % (got, want)))
    return ok


def main():
    ok = True
    had = (("GER40", 3), ("NAS100", 1))          # що вже лежить у журналі

    # --- що має звестись до знайомого написання ---
    ok &= case("пробіл усередині", canon("GER 40", had), "GER40")
    ok &= case("регістр", canon("Ger40", had), "GER40")
    ok &= case("і те, і те", canon("ger 40", had), "GER40")
    ok &= case("дефіс", canon("GER-40", had), "GER40")
    ok &= case("пробіли по краях", canon("  nas 100  ", had), "NAS100")

    # --- чого чіпати не можна ---
    ok &= case("незнайомий інструмент лишається як написаний",
               canon("UK100", had), "UK100")
    ok &= case("схожі індекси — різні інструменти",
               canon("US30", (("US100", 5),)), "US30")
    ok &= case("інші імена того самого індексу зводить людина",
               canon("USTEC", (("NAS100", 5),)), "USTEC")
    ok &= case("порожнє поле не чіпаємо", canon("", had), "")

    # --- як обирається еталон ---
    ok &= case("беремо частіше написання",
               canon("ger40", (("GER 40", 9), ("GER40", 2))), "GER 40")
    ok &= case("порівну — щоразу те саме",
               canon("ger40", (("GER40", 2), ("GER 40", 2))), "GER 40")

    # --- пачка: перенесення з таблиці ---
    batch = [{"pair": "ftse 100"}, {"pair": "FTSE100"}, {"pair": "Ftse-100"}]
    db._one_spelling(Conn(), "u1", batch)
    ok &= case("у пачці незнайомий інструмент задає написання решті",
               sorted({t["pair"] for t in batch}), ["ftse 100"])

    # --- правка угоди ---
    c = Conn(had)
    db._one_spelling(c, "u1", [{"pair": "ger 40", "id": "t7"}], skip_id="t7")
    ok &= case("своє ж старе написання собі не еталон",
               "id<>%s" in c.sql, True)

    print("\n" + ("усе добре" if ok else "є помилки"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

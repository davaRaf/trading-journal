# -*- coding: utf-8 -*-
"""
Ключ тижня: python test_week.py

Тиждень у базі лежить під датою понеділка. Якщо сюди пройде будь-який інший
день, та сама сімка днів розповзеться по базі під різними ключами: друга
правка не знайде першу, і людина побачить порожній тиждень замість свого
розбору. Тому перевіряємо саме межу — що проходить усередину і в який
понеділок зводиться довільна дата.

Бази не треба: перевіряємо чисті функції.
"""
import os

os.environ.setdefault("DATABASE_URL", "postgresql://x/y")

import week_store


def case(name, got, want):
    ok = got == want
    print(("  ok  " if ok else "ПОМИЛКА") + "  " + name +
          ("" if ok else "  → отримали %r, чекали %r" % (got, want)))
    return ok


def main():
    ok = True

    # --- що проходить у базу ---
    ok &= case("понеділок проходить", week_store.valid_week("2026-10-05"), True)
    ok &= case("вівторок не проходить", week_store.valid_week("2026-10-06"), False)
    ok &= case("неділя не проходить", week_store.valid_week("2026-10-11"), False)
    ok &= case("без нуля в числі не проходить", week_store.valid_week("2026-10-5"), False)
    ok &= case("номер тижня не проходить", week_store.valid_week("2026-W41"), False)
    ok &= case("дати, якої немає, теж немає", week_store.valid_week("2026-02-30"), False)
    ok &= case("порожнє не проходить", week_store.valid_week(""), False)
    ok &= case("ніщо не ламає перевірку", week_store.valid_week(None), False)

    # --- у який тиждень потрапляє дата ---
    ok &= case("понеділок лишається собою", week_store.monday("2026-10-05"), "2026-10-05")
    ok &= case("середина тижня тягнеться назад", week_store.monday("2026-10-08"), "2026-10-05")
    # неділя належить тому тижню, що почався в понеділок, а не наступному:
    # інакше розбір вихідних лягав би вже в новий тиждень
    ok &= case("неділя — кінець свого тижня", week_store.monday("2026-10-11"), "2026-10-05")
    ok &= case("наступний понеділок — новий тиждень",
               week_store.monday("2026-10-12"), "2026-10-12")
    ok &= case("межа року не плутає тижні", week_store.monday("2027-01-01"), "2026-12-28")
    ok &= case("сміття не дає ключа", week_store.monday("каша"), None)
    ok &= case("ніщо не дає ключа", week_store.monday(None), None)

    # --- те, що дав monday(), завжди приймає valid_week() ---
    import datetime
    day = datetime.date(2026, 1, 1)
    for _ in range(400):
        if not week_store.valid_week(week_store.monday(day.isoformat())):
            ok &= case("понеділок з %s не прийнявся" % day, False, True)
            break
        day += datetime.timedelta(days=1)
    else:
        ok &= case("400 днів поспіль зводяться у свій понеділок", True, True)

    print("\n" + ("усе добре" if ok else "є помилки"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

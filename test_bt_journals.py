# -*- coding: utf-8 -*-
"""
Журнали бектесту: python test_bt_journals.py

Перевіряємо чисті функції `bt_journals_store` — те, що приходить з
браузера, перед тим як лягти в базу, і підбір вільної назви. Бази не
треба.
"""
import os

os.environ.setdefault("DATABASE_URL", "postgresql://x/y")

import bt_journals_store as bj

fails = []


def eq(got, want, what):
    if got != want:
        fails.append("%s: %r != %r" % (what, got, want))


# назва й актив — без зайвих пробілів, зокрема нерозривних
c = bj.clean({"name": "  US100  березень ", "asset": " US100 "})
eq(c["name"], "US100 березень", "назва")
eq(c["asset"], "US100", "актив")

# дата тільки у вигляді РРРР-ММ-ДД, решта — порожньо
c = bj.clean({"name": "x", "period_from": "2024-03-01T10:00", "period_to": "березень"})
eq(c["period_from"], "2024-03-01", "дата з часом")
eq(c["period_to"], "", "не дата")

# переплутані краї періоду міняються місцями
c = bj.clean({"name": "x", "period_from": "2024-06-30", "period_to": "2024-01-01"})
eq((c["period_from"], c["period_to"]), ("2024-01-01", "2024-06-30"), "краї періоду")

# нотатка довша за 200, але не безмежна
c = bj.clean({"name": "x", "note": "a" * 5000})
eq(len(c["note"]), 1000, "довжина нотатки")

# вільна назва: номер дописується, наявний номер нарощується
eq(bj.pick_free("US100", set()), "US100", "вільна")
eq(bj.pick_free("US100", {"us100"}), "US100 2", "зайнята")
eq(bj.pick_free("US100", {"us100", "us100 2"}), "US100 3", "двічі зайнята")
eq(bj.pick_free("Gold 2", {"gold 2"}), "Gold 3", "вже з номером")
eq(bj.pick_free("", {"x"}), "", "порожня")

if fails:
    print("\n".join(fails))
    raise SystemExit(1)
print("усе добре")

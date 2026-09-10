# -*- coding: utf-8 -*-
"""
Реальна угода чи бектест: python test_kind.py

Тип приходить із браузера, тому головне тут — що всередину проходить тільки
«bt», а все інше лишається торгівлею. Помилитись в інший бік дорого: прогін
на історії, записаний як справжня угода, тихо зіпсує винрейт і профіт-фактор.

Бази не треба: перевіряємо чисті функції.
"""
import os

os.environ.setdefault("DATABASE_URL", "postgresql://x/y")

import app
import db


def case(name, got, want):
    ok = got == want
    print(("  ok  " if ok else "ПОМИЛКА") + "  " + name +
          ("" if ok else "  → отримали %r, чекали %r" % (got, want)))
    return ok


def kind_of(body):
    return app.clean_trade(dict(body, pair="GER40"), "t1")["kind"]


def main():
    ok = True

    # --- що приходить із браузера ---
    ok &= case("бектест позначається", kind_of({"kind": "bt"}), "bt")
    ok &= case("без поля — реальна угода", kind_of({}), "")
    ok &= case("порожнє поле — реальна угода", kind_of({"kind": ""}), "")
    ok &= case("чуже значення не проходить", kind_of({"kind": "backtest"}), "")
    ok &= case("не рядок не ламає запис", kind_of({"kind": 1}), "")
    ok &= case("пробіли по краях", kind_of({"kind": " bt "}), "bt")

    # --- що йде в базу ---
    vals = db._trade_values({"pair": "GER40", "kind": "bt"})
    ok &= case("тип іде останнім значенням", vals[-1], "bt")
    ok &= case("сміття не доїде й сюди",
               db._trade_values({"pair": "GER40", "kind": "хочу"})[-1], "")
    ok &= case("значень стільки, скільки колонок",
               len(vals), len(db.FIELDS) + 3)

    # --- підпис прогону — звичайне поле угоди ---
    ok &= case("прогін лежить серед полів", "bt_run" in db.TEXT_FIELDS, True)
    ok &= case("прогін зберігається",
               app.clean_trade({"pair": "GER40", "bt_run": "EURUSD H1"},
                               "t2")["bt_run"], "EURUSD H1")

    print("\n" + ("усе добре" if ok else "є помилки"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""
Вивантаження журналу: py test_export_csv.py

Один файл на весь журнал рятує все, але віддати комусь один прогін ним
не можна: реальні угоди й бектест лежать упереміш. Тут перевіряємо те,
що звужує вибірку й розкладає її таблицею, — чисті функції, без бази.

Головне, чого боїмось:
  * бектест, який просочився у вивантаження реальної торгівлі (і навпаки);
  * прогін, який не знайшовся через зайвий пробіл у назві;
  * таблиця, яку Excel відкриє кракозябрами або розсипле на комі всередині
    нотатки.
"""
import csv
import datetime
import io
import os

os.environ.setdefault("DATABASE_URL", "postgresql://x/y")

import backup


def case(name, got, want):
    ok = got == want
    print(("  ok  " if ok else "ПОМИЛКА") + "  " + name +
          ("" if ok else "  → отримали %r, чекали %r" % (got, want)))
    return ok


TRADES = [
    {"id": "a", "kind": "", "bt_run": "", "pair": "EURUSD", "rr": 2.0},
    {"id": "b", "kind": "bt", "bt_run": "US100 березень", "pair": "US100", "rr": 1.5},
    {"id": "c", "kind": "bt", "bt_run": "US100  Березень", "pair": "US100", "rr": -1.0},
    {"id": "d", "kind": "bt", "bt_run": "золото рік", "pair": "XAUUSD", "rr": 3.0},
    {"id": "e", "kind": "bt", "bt_run": "", "pair": "GER40", "rr": 0.5},
]


def ids(rows):
    return [t["id"] for t in rows]


def main():
    ok = True

    # ---- звуження ----
    ok &= case("без звуження беремо все",
               ids(backup.only(TRADES)), ["a", "b", "c", "d", "e"])
    ok &= case("тільки бектест",
               ids(backup.only(TRADES, "bt")), ["b", "c", "d", "e"])
    ok &= case("тільки справжня торгівля",
               ids(backup.only(TRADES, "live")), ["a"])
    # Зайвий пробіл і регістр у назві — звичайна річ, коли журнал заводили
    # руками. Прогін має знайтись однаково.
    ok &= case("прогін знаходиться попри пробіли й регістр",
               ids(backup.only(TRADES, "bt", "US100 Березень")), ["b", "c"])
    ok &= case("нерозривний пробіл у назві теж не заважає",
               ids(backup.only(TRADES, "bt", "US100 березень")), ["b", "c"])
    # «Без журналу» — окремий випадок: порожній рядок звужує, а None — ні.
    ok &= case("порожня назва — це «без журналу», а не «усі»",
               ids(backup.only(TRADES, "bt", "")), ["e"])

    # ---- зліпок під вибірку ----
    snap = {"trades": TRADES, "strategy": {"x": 1}, "strategy_bt": {"y": 2},
            "bt_journals": [{"name": "US100 березень", "asset": "US100"},
                            {"name": "золото рік", "asset": "XAUUSD"}]}
    bt = backup.narrow(snap, "bt")
    ok &= case("у вивантаженні бектесту нема ТС реальної торгівлі",
               "strategy" in bt, False)
    ok &= case("а ТС бектесту лишається", bt.get("strategy_bt"), {"y": 2})
    live = backup.narrow(snap, "live")
    ok &= case("у реальному вивантаженні нема ні ТС бектесту, ні журналів",
               ("strategy_bt" in live, "bt_journals" in live), (False, False))
    one = backup.narrow(snap, "bt", "US100 березень")
    ok &= case("картка прогону їде разом з його угодами",
               [j["name"] for j in one["bt_journals"]], ["US100 березень"])
    ok &= case("і сам зліпок каже, що він звужений",
               one["only"], {"kind": "bt", "run": "US100 березень"})

    # ---- таблиця ----
    raw = backup.trades_csv(backup.only(TRADES, "bt", "US100 березень"))
    ok &= case("таблиця починається з BOM — інакше Excel зіпсує кирилицю",
               raw[:3], b"\xef\xbb\xbf")
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
    ok &= case("заголовок на місці", rows[0][:3], ["id", "kind", "bt_run"])
    ok &= case("рядків стільки ж, скільки угод", len(rows), 3)
    ok &= case("угода лягла в рядок", rows[1][:3], ["b", "bt", "US100 березень"])

    # Кома й лапки всередині нотатки не мають розсипати таблицю.
    tricky = [{"id": "x", "kind": "", "notes": 'купив, бо "пробій"',
               "screenshots": ["s1.png", "s2.png"], "rr": None}]
    back = list(csv.reader(io.StringIO(
        backup.trades_csv(tricky).decode("utf-8-sig"))))
    col = {h: i for i, h in enumerate(back[0])}
    ok &= case("кома й лапки в нотатці не ламають рядок",
               back[1][col["notes"]], 'купив, бо "пробій"')
    ok &= case("скріни збираються в одну клітинку",
               back[1][col["screenshots"]], "s1.png; s2.png")
    ok &= case("порожнє число лишається порожнім", back[1][col["rr"]], "")

    # ---- ім'я файла ----
    day = datetime.date(2026, 10, 14)
    ok &= case("весь журнал", backup.file_name("all", None, "json", day),
               "journal-2026-10-14.json")
    ok &= case("тільки бектест", backup.file_name("bt", None, "csv", day),
               "backtest-2026-10-14.csv")
    ok &= case("один прогін — латиницею в назві",
               backup.file_name("bt", "US100 березень", "csv", day),
               "backtest-US100-2026-10-14.csv")
    # Назва без жодної латинської літери не має лишити файл без імені.
    ok &= case("назва без латиниці не з'їдає ім'я",
               backup.file_name("bt", "золото", "json", day),
               "backtest-run-2026-10-14.json")

    print("\n" + ("ВСЕ ДОБРЕ" if ok else "Є ПОМИЛКИ"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

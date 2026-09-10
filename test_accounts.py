# -*- coding: utf-8 -*-
"""
Опис рахунку: python test_accounts.py

Перевіряємо `accounts_store.clean` — те, що приходить з браузера, перед тим
як лягти в базу. Тут два місця, де помилка коштує дорого:

  • порожній ліміт мусить лишатись порожнім, а не ставати нулем. Нуль
    означає «ліміт нуль відсотків», тобто рахунок злитий з першої угоди;
  • живий рахунок не має носити дату закриття й причину — інакше картка
    показувала б «активний» і поруч «злитий тоді-то».

Бази не треба: перевіряємо чисту функцію.
"""
import datetime
import os

os.environ.setdefault("DATABASE_URL", "postgresql://x/y")

import accounts_store


class _Rows(object):
    """Заглушка бази: `free_name` ходить по список уже заведених назв.

    Справжнього зʼєднання тут не треба — перевіряємо саме підбір назви.
    """

    def __init__(self, names):
        self.names = names

    def execute(self, sql, args=None):
        return self

    def fetchall(self):
        return [{"id": i + 1, "name": nm} for i, nm in enumerate(self.names)]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def free(name, existing, skip_id=None):
    accounts_store._ready = True                 # схему не створюємо
    was = accounts_store.db.connect
    accounts_store.db.connect = lambda: _Rows(existing)
    try:
        return accounts_store.free_name(1, name, skip_id)
    finally:
        accounts_store.db.connect = was


def case(name, got, want):
    ok = got == want
    print(("  ok  " if ok else "ПОМИЛКА") + "  " + name +
          ("" if ok else "  → отримали %r, чекали %r" % (got, want)))
    return ok


def main():
    ok = True

    # --- числа ---
    a = accounts_store.clean({"name": "FTMO", "start_balance": "100000",
                              "target_pct": "10", "dd_total_pct": "", "dd_daily_pct": None})
    ok &= case("баланс числом", a["start_balance"], 100000.0)
    ok &= case("ціль числом", a["target_pct"], 10.0)
    ok &= case("порожній ліміт — не нуль", a["dd_total_pct"], None)
    ok &= case("відсутній ліміт — не нуль", a["dd_daily_pct"], None)
    ok &= case("сміття замість числа — порожньо",
               accounts_store.clean({"start_balance": "сто тисяч"})["start_balance"], None)
    ok &= case("нуль лишається нулем",
               accounts_store.clean({"dd_daily_pct": 0})["dd_daily_pct"], 0.0)

    # --- баланс з кабінету фірми ---
    b = accounts_store.clean({"start_balance": 100000, "current_balance": 103000})
    ok &= case("баланс зараз числом", b["current_balance"], 103000.0)
    ok &= case("порожній баланс зараз — не нуль",
               accounts_store.clean({"current_balance": ""})["current_balance"], None)
    ok &= case("мінус проходить",
               accounts_store.clean({"current_balance": -500})["current_balance"], -500.0)
    ok &= case("сміття замість балансу — порожньо",
               accounts_store.clean({"current_balance": "багато"})["current_balance"], None)
    ok &= case("баланс зараз є серед полів",
               "current_balance" in accounts_store.FIELDS, True)

    # --- перелічення ---
    ok &= case("свій тип проходить",
               accounts_store.clean({"kind": "challenge"})["kind"], "challenge")
    ok &= case("чужий тип — свій депозит",
               accounts_store.clean({"kind": "prop"})["kind"], "own")
    ok &= case("чужий стан — активний",
               accounts_store.clean({"status": "blown"})["status"], "active")
    ok &= case("злитий проходить",
               accounts_store.clean({"status": "failed"})["status"], "failed")

    # --- стан залежить від типу ---
    ok &= case("фандед не буває пройденим",
               accounts_store.clean({"kind": "funded", "status": "passed"})["status"], "active")
    ok &= case("фандед не буває закритим",
               accounts_store.clean({"kind": "funded", "status": "closed"})["status"], "active")
    ok &= case("злитий фандед лишається злитим",
               accounts_store.clean({"kind": "funded", "status": "failed"})["status"], "failed")
    ok &= case("у челенджа пройдений лишається",
               accounts_store.clean({"kind": "challenge", "status": "passed"})["status"], "passed")
    ok &= case("свій депозит не буває пройденим",
               accounts_store.clean({"kind": "own", "status": "passed"})["status"], "active")
    ok &= case("свій депозит можна закрити",
               accounts_store.clean({"kind": "own", "status": "closed"})["status"], "closed")
    ok &= case("свій депозит можна злити",
               accounts_store.clean({"kind": "own", "status": "failed"})["status"], "failed")

    # --- живий рахунок не носить причини ---
    live = accounts_store.clean({"name": "Свій", "status": "active",
                                 "closed_at": "2026-09-05", "reason": "злив"})
    ok &= case("у живого немає дати закриття", live["closed_at"], "")
    ok &= case("у живого немає причини", live["reason"], "")
    dead = accounts_store.clean({"name": "FTMO", "status": "failed",
                                 "closed_at": "2026-09-05", "reason": "денний ліміт"})
    ok &= case("у злитого дата лишається", dead["closed_at"], "2026-09-05")
    ok &= case("у злитого причина лишається", dead["reason"], "денний ліміт")

    # --- дати ---
    ok &= case("дата як є", accounts_store.clean({"opened_at": "2026-08-12"})["opened_at"],
               "2026-08-12")
    ok &= case("час у даті відрізається",
               accounts_store.clean({"opened_at": "2026-08-12T10:00:00"})["opened_at"],
               "2026-08-12")
    ok &= case("крива дата — порожньо",
               accounts_store.clean({"opened_at": "12.08.2026"})["opened_at"], "")

    # --- імʼя рахунку ---
    # Звʼязок з угодами йде саме по імені, і невидима різниця в ньому
    # лишає картку зовсім без угод.
    n = accounts_store.norm_name
    ok &= case("пробіли по краях назви",
               accounts_store.clean({"name": "  FTMO 100k  "})["name"], "FTMO 100k")
    ok &= case("подвійний пробіл усередині", n("FTMO   100k"), "FTMO 100k")
    ok &= case("нерозривний пробіл — звичайний", n("FTMO\u00a0100k"), "FTMO 100k")
    ok &= case("вузький нерозривний теж", n("FTMO\u202f100k"), "FTMO 100k")
    ok &= case("перенос рядка з буфера", n("FTMO\n100k"), "FTMO 100k")
    ok &= case("порожнє лишається порожнім", n("   "), "")
    ok &= case("назва в clean теж нормалізується",
               accounts_store.clean({"name": "FTMO\u00a0 100k"})["name"], "FTMO 100k")

    # --- вільна назва: замість відмови дописуємо номер ---
    ok &= case("вільна назва лишається собою",
               free("FTMO 100k", ["Свій депозит"]), "FTMO 100k")
    ok &= case("зайнята отримує двійку",
               free("FTMO 100k", ["FTMO 100k"]), "FTMO 100k 2")
    ok &= case("регістр не рятує від збігу",
               free("ftmo 100k", ["FTMO 100k"]), "ftmo 100k 2")
    ok &= case("пробіли не рятують від збігу",
               free("  FTMO   100k ", ["FTMO 100k"]), "FTMO 100k 2")
    ok &= case("номер росте далі, а не множиться",
               free("FTMO 100k", ["FTMO 100k", "FTMO 100k 2"]), "FTMO 100k 3")
    ok &= case("пронумеровану назву нарощуємо від основи",
               free("FTMO 100k 2", ["FTMO 100k 2"]), "FTMO 100k 3")
    ok &= case("свою ж назву не рахуємо зайнятою",
               free("FTMO 100k", ["FTMO 100k"], skip_id=1), "FTMO 100k")
    ok &= case("порожню назву не нумеруємо", free("", ["FTMO"]), "")

    # --- дата, на яку правдивий вписаний баланс ---
    # Без неї цифра з кабінету застигала: угоди після неї не враховувались.
    stamp = accounts_store._stamp_balance
    fresh = stamp(accounts_store.clean({"current_balance": 103000}))
    ok &= case("новий баланс отримує сьогоднішню дату",
               fresh["balance_at"], datetime.date.today().isoformat())
    ok &= case("без балансу дати немає",
               stamp(accounts_store.clean({}))["balance_at"], "")
    keep = stamp(accounts_store.clean({"current_balance": 103000}),
                 {"current_balance": 103000.0, "balance_at": "2026-09-01"})
    ok &= case("незмінний баланс не зсуває дату", keep["balance_at"], "2026-09-01")
    moved = stamp(accounts_store.clean({"current_balance": 104000}),
                  {"current_balance": 103000.0, "balance_at": "2026-09-01"})
    ok &= case("новий баланс — нова дата",
               moved["balance_at"], datetime.date.today().isoformat())

    # --- дрібниці ---
    ok &= case("валюта за замовчуванням", accounts_store.clean({})["currency"], "USD")

    print("\n" + ("Усе зійшлось." if ok else "Є розбіжності."))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

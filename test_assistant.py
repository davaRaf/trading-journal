# -*- coding: utf-8 -*-
"""Помічник: чи бачить він журнал так само, як людина.

Перевіряємо те, на чому він уже спотикався:
  * «US100», «NASDAQ» і «NQ» — один інструмент, а не три;
  * серія стопів піврічної давнини не має спливати щодня;
  * він помічає, що в журналі з'явилось нового;
  * одну й ту саму думку не повторює тиждень поспіль.

Майже все — чиста арифметика, бази не треба. Остання перевірка ходить
у базу: пам'ять про сказане лежить саме там.
"""
import datetime
import sys

import assistant
import db

bad = 0


def check(name, cond, extra=""):
    global bad
    if not cond:
        bad += 1
    print("  %-6s %s%s" % ("ok" if cond else "ПАДАЄ", name,
                           ("  -> " + str(extra)) if extra else ""))


def trade(day, pair="US100", result="Win", rr=1.0, **kw):
    t = {"date": day.strftime("%Y-%m-%dT%H:%M"), "pair": pair,
         "result": result, "rr": rr, "net": 1.0 if result != "Loss" else -1.0}
    t.update(kw)
    return t


def days_ago(n, hour=10):
    d = datetime.datetime.now() - datetime.timedelta(days=n)
    return d.replace(hour=hour, minute=0)


def rules(trades):
    return [r for r, _ in assistant.news(trades, "uk", tagged=True)]


def main():
    print("один актив під різними іменами")
    trades = ([trade(days_ago(i), "US100") for i in range(1, 6)]
              + [trade(days_ago(i), "NASDAQ") for i in range(6, 9)]
              + [trade(days_ago(i), "NQ") for i in range(9, 11)]
              + [trade(days_ago(i), "US30") for i in range(11, 13)])
    by = assistant.by_field(trades, "pair")
    check("інструментів два, а не чотири", len(by) == 2, sorted(by))
    name = [k for k in by if assistant.tidy.key(k) == assistant.tidy.key("US100")]
    check("назва — та, якою людина пише частіше", name == ["US100"], name)
    check("усі десять угод в одному зрізі",
          by.get("US100", {}).get("n") == 10, by.get("US100"))
    check("US30 не злився з US100", by.get("US30", {}).get("n") == 2)

    print("")
    print("сесії теж зводяться")
    ses = assistant.by_field(
        [trade(days_ago(1), session="LO"), trade(days_ago(2), session="LONDON"),
         trade(days_ago(3), session="NY")], "session")
    check("LO і LONDON — одна сесія", len(ses) == 2, sorted(ses))

    print("")
    print("серія стопів")
    old = ([trade(days_ago(120 + i), result="Loss") for i in range(4)]
           + [trade(days_ago(i), result="Win") for i in range(1, 6)])
    got = [r for r, _ in assistant.observations(old, "uk", tagged=True)]
    check("торішня серія вже не спливає", "streak" not in got, got)

    fresh = ([trade(days_ago(10 + i), result="Loss") for i in range(4)]
             + [trade(days_ago(i), result="Win") for i in range(1, 4)])
    got = [r for r, _ in assistant.observations(fresh, "uk", tagged=True)]
    check("свіжа серія спливає", "streak" in got, got)

    now = [trade(days_ago(i), result="Loss") for i in range(1, 5)]
    facts = assistant.observations(now, "uk", tagged=True)
    check("поточна серія названа поточною",
          bool(facts) and facts[0][0] == "streak" and "4" in facts[0][1],
          facts[0][1] if facts else None)

    print("")
    print("що нового в журналі")
    base = [trade(days_ago(30 + i), "US100", "Win" if i % 2 else "Loss")
            for i in range(20)]

    newpair = base + [trade(days_ago(i), "US500") for i in (2, 3, 4)]
    check("новий інструмент помічено",
          any(r.startswith("pair:") for r in rules(newpair)), rules(newpair))

    same = base + [trade(days_ago(2))]
    check("старий інструмент за новий не видаємо",
          not any(r.startswith("pair:") for r in rules(same)), rules(same))

    one = base + [trade(days_ago(2), "US500")]
    check("одна угода новим інструментом ще не новина",
          not any(r.startswith("pair:") for r in rules(one)), rules(one))

    setup = base + [trade(days_ago(i), setup="SFP") for i in (2, 3)]
    check("новий сетап помічено",
          any(r.startswith("setup:") for r in rules(setup)), rules(setup))

    pause = ([trade(days_ago(60 + i)) for i in range(10)]
             + [trade(days_ago(i)) for i in (1, 2, 3)])
    check("повернення після перерви", "back" in rules(pause), rules(pause))

    wins = base + [trade(days_ago(i), result="Win") for i in (1, 2, 3, 4)]
    check("серія плюсових — теж новина", "win_streak" in rules(wins), rules(wins))

    check("у новому журналі новин не шукаємо",
          assistant.news([trade(days_ago(1))] * 3, "uk", tagged=True) == [])

    print("")
    print("новину кажемо один раз, думку — не частіше разу на тиждень")
    email = "assist-test-%d@example.com" % int(db.now().timestamp())
    uid = db.create_user(email, email.split("@")[0], "x", "y", 1)["id"]
    try:
        week = "%s-%s" % datetime.date.today().isocalendar()[:2]
        first = db.record_notified(uid, "streak:%s" % week, "nudge")
        again = db.record_notified(uid, "streak:%s" % week, "nudge")
        check("перший раз сказали", first)
        check("вдруге за той самий тиждень — мовчимо", not again)
        other = db.record_notified(uid, "hurry:%s" % week, "nudge")
        check("інша думка того ж тижня — можна", other)
        nxt = db.record_notified(uid, "streak:%s-%s" % (2099, 1), "nudge")
        check("наступного тижня та сама думка — знову можна", nxt)
        check("новий інструмент — один раз назавжди",
              db.record_notified(uid, "pair:US500", "nudge")
              and not db.record_notified(uid, "pair:US500", "nudge"))
        check("інший новий інструмент — окремо",
              db.record_notified(uid, "pair:GER40", "nudge"))
    finally:
        with db.connect() as c:
            c.execute("DELETE FROM notified_events WHERE user_id=%s", (uid,))
            c.execute("DELETE FROM users WHERE id=%s", (uid,))
            c.commit()
        print("")
        print("тимчасовий акаунт прибрано")

    print("")
    print("ЄСТЬ ПАДІННЯ: %d" % bad if bad else "усе сходиться")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""
Перевірка звірки угоди з ТС: python test_ts_check.py

Головне, що тут перевіряється, — не «спрацювало», а «мовчить, коли має
мовчати». Помічник, який чіпляється до кожної угоди, вимикається першим.
"""
import ts_check

TS = {
    "assets": ["US100", "GER40"],
    "models": [{"name": "cisd"}, {"name": "sweep"}],
    "windows": [{"name": "Лондон", "time": "09:00 – 12:00"},
                {"name": "Нью-Йорк", "time": "15:30 – 18:00"}],
    "days": "пропускаю: П'ятниця",
    "maxtrades": "2",
    "risk": {"per": "0.5%, 1%", "rr": "2", "day": "2%"},
}

# середа, лондонська сесія, все за правилами
GOOD = {"pair": "US100", "date": "2026-09-02T10:15", "entry_model": "cisd",
        "result": "Win", "rr": 2.5, "risk": 0.5}


def codes(ts, trade, day=None):
    return [x["code"] for x in ts_check.check(ts, trade, day)]


def case(name, got, want):
    ok = got == want
    print(("  ok  " if ok else "ПОМИЛКА") + "  " + name +
          ("" if ok else "  → отримали %s, чекали %s" % (got, want)))
    return ok


def main():
    ok = True

    ok &= case("угода за правилами — мовчимо", codes(TS, GOOD), [])
    ok &= case("порожня ТС — мовчимо", codes({}, GOOD), [])
    ok &= case("ТС без чисел — мовчимо",
               codes({"assets": [], "models": [], "risk": {}}, GOOD), [])

    ok &= case("чужий інструмент",
               codes(TS, dict(GOOD, pair="XAUUSD")), ["asset"])
    ok &= case("пара іншим написанням — свій",
               codes(TS, dict(GOOD, pair="us 100")), [])
    ok &= case("чужа модель входу",
               codes(TS, dict(GOOD, entry_model="навмання")), ["model"])
    ok &= case("модель не вказана — не чіпляємось",
               codes(TS, dict(GOOD, entry_model="")), [])

    ok &= case("вхід поза вікнами (13:20)",
               codes(TS, dict(GOOD, date="2026-09-02T13:20")), ["window"])
    ok &= case("вхід у друге вікно (16:00)",
               codes(TS, dict(GOOD, date="2026-09-02T16:00")), [])
    ok &= case("нічне вікно через північ",
               codes({"windows": [{"name": "Азія", "time": "22:00 – 02:00"}]},
                     dict(GOOD, date="2026-09-02T23:40")), [])

    ok &= case("п'ятниця, яку пропускає",
               codes(TS, dict(GOOD, date="2026-09-04T10:15")), ["weekday"])
    ok &= case("«торгую пн-пт» забороною не рахуємо",
               codes({"days": "торгую пн-пт"}, dict(GOOD, date="2026-09-04T10:15")), [])

    ok &= case("ризик більший за оголошений",
               codes(TS, dict(GOOD, risk=2)), ["risk"])
    ok &= case("ризик на межі — мовчимо", codes(TS, dict(GOOD, risk=1)), [])
    ok &= case("RR нижчий за мінімальний",
               codes(TS, dict(GOOD, rr=1.2)), ["rr"])

    day = [dict(GOOD, result="Loss", risk=1.2), dict(GOOD, result="Loss", risk=1.2)]
    ok &= case("денний ліміт збитку перебито",
               [c for c in codes(TS, day[1], day) if c == "dayloss"], ["dayloss"])

    three = [GOOD, GOOD, GOOD]
    ok &= case("угод за день більше ліміту",
               [c for c in codes(TS, GOOD, three) if c == "maxtrades"], ["maxtrades"])
    ok &= case("рівно ліміт — мовчимо",
               [c for c in codes(TS, GOOD, [GOOD, GOOD]) if c == "maxtrades"], [])

    ok &= case("не більше чотирьох за раз",
               len(ts_check.check(TS, {"pair": "XAUUSD", "date": "2026-09-04T13:20",
                                       "entry_model": "навмання", "result": "Loss",
                                       "rr": 0.5, "risk": 3})) <= 4, True)

    print("\n" + ("усе зійшлось" if ok else "є розбіжності"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

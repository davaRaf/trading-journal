# -*- coding: utf-8 -*-
"""Розбір угоди з живого тексту: що приймаємо від моделі, а що ні.

Модель підмінена — перевіряємо власну частину: дешевий фільтр перед
запитом, коди результату, числа, дату й те, що вигадане поле не поїде
в журнал.
"""
import json
import sys
import types

fake_db = types.ModuleType("db")
fake_db.frequent_values = lambda uid, field, limit=12: {
    "pair": ["EURUSD", "NQ"], "session": ["Лондон"]}.get(field, [])

fake_llm = types.ModuleType("llm")
ANSWER = {"value": ""}
fake_llm.enabled = lambda: True
fake_llm.ask = lambda *a, **kw: ANSWER["value"]

sys.modules["db"] = fake_db
sys.modules["llm"] = fake_llm

import trade_ai as ta                                        # noqa: E402


def check(name, cond):
    print("  %-5s %s" % ("ok" if cond else "ПАДАЄ", name))
    assert cond, name


def answer(**fields):
    data = {"is_trade": True}
    data.update(fields)
    ANSWER["value"] = json.dumps(data, ensure_ascii=False)


def check_filter():
    """Модель смикаємо лише там, де схоже на угоду."""
    check("прямий намір", ta.wants_trade("запиши сделку EURUSD"))
    check("опис без слова «запиши»", ta.wants_trade("EU лонг по Лондону, +2R"))
    check("балачка не рахується", not ta.wants_trade("как дела?"))
    check("питання про новини не рахується", not ta.wants_trade("что там по новостям"))
    check("короткий вигук не рахується", not ta.wants_trade("ок"))


def check_parse():
    """Поля з відповіді моделі: коди, числа, дата."""
    answer(pair="EURUSD", position="Long", session="Лондон", result="Win",
           rr=2, risk="1,5", date="2026-09-05", emotion="Спокій")
    out = ta.parse(1, "EU лонг по Лондону, взял 2R")
    check("пара на місці", out["pair"] == "EURUSD")
    check("напрямок кодом", out["position"] == "Long")
    check("результат кодом", out["result"] == "Win")
    check("числа числами", out["rr"] == 2.0 and out["risk"] == 1.5)
    check("дата як у журналі", out["date"] == "2026-09-05")
    check("порожні поля порожні, не None", out["setup"] == "" and out["notes"] == "")


def check_garbage():
    """Чого модель не мала права сказати — не пускаємо в журнал."""
    answer(pair="NQ", position="лонг", result="профит", rr="дві")
    out = ta.parse(1, "NQ лонг, профит")
    check("чужий напрямок відкинули", out["position"] == "")
    check("чужий результат відкинули", out["result"] == "")
    check("нечисло відкинули", out["rr"] is None)
    check("дата підставилась сьогоднішня", len(out["date"]) == 10)

    answer(pair="", result="Win")
    check("без пари це не угода", ta.parse(1, "взял 2R") is None)

    ANSWER["value"] = json.dumps({"is_trade": False})
    check("модель сказала «не угода» — вірим", ta.parse(1, "что по EU?") is None)

    ANSWER["value"] = "не JSON зовсім"
    check("сміття замість JSON не валить розбір", ta.parse(1, "EU лонг 2R") is None)

    ANSWER["value"] = None
    check("модель мовчить — просто None", ta.parse(1, "EU лонг 2R") is None)


check_filter()
check_parse()
check_garbage()
print("\nусе добре")

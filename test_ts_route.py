# -*- coding: utf-8 -*-
"""
Розкладка розділів ТС по вкладках: python test_ts_route.py

Підказка в правилах — це прохання до моделі, а не гарантія: вона однаково
зносила цілі розділи в «Додатково», і людина бачила там «Синхронізацію»,
«Psychology» і «Entry models» (22.09.2026). Тому блоки з упізнаваним
заголовком розкладає вже код, після відповіді.

Головне, що тут перевіряється, — не «переклало», а «нічого не загубило»:
переносимо блок тільки туди, де вміститься і текст, і його скріни. Не
впізнали заголовок — блок лишається в «Додатково», і людина перекладе руками.
"""
import ts_ai

TFS = ["1W", "1D", "4H", "2H", "1H", "30M", "15M", "5M", "3M", "1M"]
SHOTS = [{"file": "s%d.png" % i, "caption": ""} for i in range(1, 9)]
NO_TF = lambda s: []

CASES = []


def case(name, fn):
    CASES.append((name, fn))


def shape(raw):
    return ts_ai.shape(raw, SHOTS, TFS, NO_TF)


# ---------------------------------------------------- сторінка власника ----
# Те, що реально лежало в «Додатково»: розділи окремими сторінками Notion,
# назви двома мовами, у двох блоках — по шість скрінів.
PAGE = shape({
    "assets": ["EURUSD", "GBPUSD", "GER40", "US100"],
    "models": [{"name": "BOS", "note": "злам структури", "shots": [7]}],
    "extra": [
        {"k": "Синхронизация и рассинхронизация ТФ",
         "v": "Синхронизация: 4h лонг OF, 1h лонг OF. Рассинхронизация: 4h лонг OF.",
         "shots": [1, 2, 3, 4, 5, 6]},
        {"k": "Entry models",
         "v": "Модели входа использую через BOS/Shift. BOS должен быть в рамках сессии.",
         "shots": [1, 2, 3, 4, 5, 6]},
        {"k": "Order Flow", "v": "У моего OF должен быть четкий таргет."},
        {"k": "Psychology",
         "v": "1. Не смотреть за тем что другие открывают. 2. Не брать сделки "
              "с воздуха. 3. Не сидеть за чартом. 4. Не торговать, когда тилт."},
        {"k": "Pairs and correlations", "v": "(EUR/USD, GBPUSD) – DXY. GER40 – EU50."},
        {"k": "General", "v": "Если инвалидация контекста далеко, то валидация будет "
                              "подтверждением смены направления."},
    ],
})

case("синхронізація ТФ — у «Контексті»",
     lambda: "Синхронизация и рассинхронизация ТФ" in [c["k"] for c in PAGE["ctx"]])
case("її шість скрінів цілі",
     lambda: len([c for c in PAGE["ctx"] if c["k"].startswith("Синхрон")][0]["shots"]) == 6)
case("Order Flow — у «Контексті»", lambda: "Order Flow" in [c["k"] for c in PAGE["ctx"]])
case("General про контекст — теж у «Контексті»",
     lambda: "General" in [c["k"] for c in PAGE["ctx"]])
case("Entry models — у моделях входу",
     lambda: "Entry models" in [m["name"] for m in PAGE["models"]])
case("їхні шість скрінів цілі",
     lambda: len([m for m in PAGE["models"] if m["name"] == "Entry models"][0]["shots"]) == 6)
case("модель, яку модель знайшла сама, не зникла",
     lambda: "BOS" in [m["name"] for m in PAGE["models"]])
case("психологія — чотирма окремими правилами", lambda: len(PAGE["psy"]) == 4)
case("перше правило психології ціле",
     lambda: PAGE["psy"][0]["v"].startswith("Не смотреть"))
case("останнє правило психології ціле",
     lambda: PAGE["psy"][3]["v"].startswith("Не торговать"))
case("кореляції стали біля своїх активів",
     lambda: PAGE["corr"] == {"EURUSD": "DXY", "GBPUSD": "DXY", "GER40": "EU50"})
case("«Додатково» спорожніло", lambda: PAGE["extra"] == [])


# ------------------------------------------------- нічого не губимо --------
case("психологія зі скріном лишається в «Додатково»: скрін нікуди подіти",
     lambda: (lambda d: [b["k"] for b in d["extra"]] == ["Psychology"] and not d["psy"])(
         shape({"extra": [{"k": "Psychology", "v": "правило", "shots": [1]}]})))

case("кореляція з незнайомим активом не ріжеться, блок лишається",
     lambda: (lambda d: d["corr"] == {} and [b["k"] for b in d["extra"]] == ["Correlations"])(
         shape({"assets": ["EURUSD"],
                "extra": [{"k": "Correlations", "v": "EURUSD – DXY. ЩОСЬ – XXX."}]})))

case("незнайомий заголовок лишається в «Додатково»",
     lambda: [b["k"] for b in shape(
         {"extra": [{"k": "Мої дивні нотатки", "v": "щось своє"}]})["extra"]] == ["Мої дивні нотатки"])

case("«General» не про контекст лишається в «Додатково»",
     lambda: (lambda d: [b["k"] for b in d["extra"]] == ["General"] and not d["ctx"])(
         shape({"extra": [{"k": "General", "v": "Ризик на угоду 1%, максимум 3 угоди."}]})))

case("загальні правила входу не затираються другим блоком",
     lambda: (lambda d: d["modelsNote"] == "вже є правило"
              and [b["k"] for b in d["extra"]] == ["Entry models"])(
         shape({"modelsNote": "вже є правило",
                "extra": [{"k": "Entry models", "v": "ще правило"}]})))


# ------------------------------------------------- решта напрямків --------
REST = shape({"extra": [
    {"k": "Skip", "v": "1. Червоні новини. 2. Перші 15 хвилин."},
    {"k": "Чек-лист перед входом", "v": "1. Біас. 2. Ліквідність."},
    {"k": "Супровід угоди", "v": "БЗ після 1R", "shots": [1]},
]})
case("Skip — у «Не входжу»",
     lambda: REST["no"]["market"] == ["Червоні новини.", "Перші 15 хвилин."])
case("чек-лист — у «Перед входом»", lambda: REST["check"] == ["Біас.", "Ліквідність."])
case("супровід переїхав разом зі скріном",
     lambda: len(REST["manage"]) == 1 and REST["manage"][0]["shots"] == ["s1.png"])
case("моделі без скрінів стають загальними правилами входу",
     lambda: shape({"extra": [{"k": "Entry models", "v": "спершу зняття ліквідності"}]}
                   )["modelsNote"] == "спершу зняття ліквідності")


# ------------------------------------------------- старе не зламалось -----
PLAIN = shape({"tfs": [{"tf": "1D", "role": "контекст", "what": "напрямок"}],
               "models": [{"name": "BOS", "shots": [1]}],
               "risk": {"per": "1%"}, "check": ["біас"], "mind": "дисципліна"})
case("звичайний розбір без «Додатково» цілий",
     lambda: PLAIN["tfs"][0]["tf"] == "1D" and PLAIN["models"][0]["shots"] == ["s1.png"]
     and PLAIN["risk"]["per"] == "1%" and PLAIN["check"] == ["біас"])
case("порожня відповідь так само вважається порожньою",
     lambda: ts_ai.is_empty(ts_ai.shape({}, [], TFS, NO_TF)))


def main():
    ok = True
    for name, fn in CASES:
        try:
            good = bool(fn())
        except Exception as e:
            good = False
            name += " (впало: %s)" % e
        ok = ok and good
        print(("OK   " if good else "НЕ ТАК") + "  " + name)
    print("\n" + ("усе зійшлось" if ok else "є розбіжності"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

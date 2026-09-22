# -*- coding: utf-8 -*-
"""
Перевірка розбору сторінки з ТС.

Ловить рівно те, на що скаржився власник журналу: таймфрейми, написані
словами, скріни, що не лягли на свої рядки, і моделі входу, вигадані з
випадкової згадки слова.

    python test_ts_notion.py

Ключа не потребує: розбір моделлю перевіряємо на заздалегідь записаній
відповіді, а не живим запитом.
"""
import ts_ai
import ts_notion as tn

PAGE = """Моя ТС
Торгую US100 та золото.
Weekly — загальний контекст, дивлюсь глобальний напрям.
Daily — де ліквідність, звідки піде рух.
H4 — уточнюю зону.
1m — вхід по CISD після зняття ліквідності.
Вхід тільки CISD на 1m по маркету.
FVG не використовую, входити в імбаланс не буду.
Ризик 1% на угоду, денний ліміт 3%.
Мінімальний RR 3.
Не більше 2 угод на день.
Стоп за структурою, під свінгом.
Правило: після беззбитку руками не чіпаю.
Не входжу перед новинами.
Головне: не тягнути стоп.
"""

SHOTS = [
    {"file": "ts4_a.png", "caption": "Weekly"},
    {"file": "ts4_b.png", "caption": "Daily"},
    {"file": "ts4_c.png", "caption": "1m вхід"},
]

# так відповідає модель: номери скрінів, а не імена файлів
ANSWER = """```json
{"assets":["US100","XAUUSD"],
 "tfs":[{"tf":"1W","role":"контекст","what":"глобальний напрям","shot":1},
        {"tf":"1D","role":"ліквідність","what":"звідки піде рух","shot":2},
        {"tf":"4H","role":"зона","what":"уточнюю зону","shot":""},
        {"tf":"1M","role":"вхід","what":"CISD після зняття ліквідності","shot":3}],
 "models":[{"name":"CISD","note":"вхід по маркету на 1m","shot":3}],
 "risk":{"per":"1%","rr":"3","day":"3%","week":""},
 "maxtrades":"2 угоди",
 "stop":{"v":"За структурою, під свінгом","shot":""},
 "target":{"v":"","shot":""},
 "manage":[{"k":"беззбиток","v":"Після беззбитку руками не чіпаю"}],
 "no":{"market":[],"time":["Не входжу перед новинами"],"self":[]},
 "mind":"Не тягнути стоп",
 "windows":[],"riskCases":[],"check":[],"days":"","news":"","bias":""}
```"""


def check_timeframes():
    """Таймфрейм пишуть як заманеться — усі записи мають зводитись до одного."""
    cases = {
        "Weekly": "1W", "тижневий": "1W", "Daily": "1D", "денний": "1D",
        "H4": "4H", "4h": "4H", "M15": "15M", "15 хвилин": "15M", "1m": "1M",
        "H1": "1H", "1 година": "1H",
    }
    for text, want in cases.items():
        got = tn._tfs_in(text)
        assert want in got, "%r -> %r, чекали %s" % (text, got, want)
    assert tn._tfs_in("просто текст без таймфреймів") == []
    print("таймфрейми: ок")


def check_shape():
    """Відповідь моделі: номери скрінів стають файлами, зайве відсікається."""
    raw = ts_ai.loads(ANSWER)
    assert raw, "JSON не розібрався"
    d = ts_ai.shape(raw, SHOTS, tn.TFS, tn._tfs_in)

    assert [r["tf"] for r in d["tfs"]] == ["1D", "4H", "1M"] or \
           [r["tf"] for r in d["tfs"]] == ["1W", "1D", "4H", "1M"], d["tfs"]
    assert d["tfs"][0]["tf"] == "1W", "старший ТФ має бути першим"
    assert d["tfs"][0]["shot"] == "ts4_a.png", "скрін не ліг на Weekly"
    assert d["tfs"][1]["shot"] == "ts4_b.png", "скрін не ліг на Daily"
    assert d["tfs"][2]["shot"] == "", "на 4H скріна не було"

    names = [m["name"].lower() for m in d["models"]]
    assert names == ["cisd"], "моделі входу: %r" % names
    assert d["maxtrades"] == "2", d["maxtrades"]
    assert d["risk"] == {"per": "1%", "rr": "3", "day": "3%", "week": ""}, d["risk"]
    assert d["manage"] and d["manage"][0]["shots"] == []
    assert d["no"]["time"] and not d["no"]["market"]
    assert not ts_ai.is_empty(d)
    print("розбір моделлю: ок")


def check_garbage():
    """Модель мовчить або меле дурню — вертаємо None, щоб пішов запасний розбір."""
    assert ts_ai.loads("вибач, не можу") is None
    assert ts_ai.loads("") is None
    d = ts_ai.shape({"tfs": "не список", "models": [1, 2], "risk": 7,
                     "assets": None, "hack": "drop table"}, [], tn.TFS, tn._tfs_in)
    assert "hack" not in d and d["tfs"] == [] and d["models"] == []
    assert ts_ai.is_empty(d)
    print("сміття від моделі: ок")


def check_fallback():
    """Без ключа працює старий розбір — сторінка не лишається порожньою."""
    d = tn.parse(PAGE)
    assert "US100" in d["assets"], d["assets"]
    assert [r["tf"] for r in d["tfs"]], "запасний розбір не знайшов жодного ТФ"
    assert d["risk"]["per"] == "1%", d["risk"]
    print("запасний розбір: ок")


if __name__ == "__main__":
    check_timeframes()
    check_shape()
    check_garbage()
    check_fallback()
    print("усе зійшлось")

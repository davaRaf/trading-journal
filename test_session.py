# -*- coding: utf-8 -*-
"""Сесія з Notion: впізнавання колонки і дозапис у вже перенесені угоди.

Ловимо те, через що сесій у журналі не було: колонку «Сесія» скасовували,
бо її значення («NY AM», «London Killzone») не збігалися зі списком назв
слово в слово.
"""
import notion_import as ni


def check(name, cond):
    print("  %-4s  %s" % ("ok" if cond else "ПАДАЄ", name))
    assert cond, name


def check_column():
    """Колонку із живими назвами сесій беремо, а не викидаємо."""
    m = ni.guess_mapping(
        {"Дата": "date", "Сесія": "select", "Інструмент": "title", "Результат": "select"},
        {"Дата": ["2025-01-02", "2025-01-03", "2025-01-06"],
         "Сесія": ["NY AM", "London Killzone", "NY PM", "Silver Bullet"],
         "Інструмент": ["NQ", "ES", "NQ"],
         "Результат": ["win", "loss", "win"]})
    check("назва «Сесія» + живі значення", m.get("session") == "Сесія")
    check("дата й інструмент на місці", m.get("date") == "Дата" and m.get("pair") == "Інструмент")

    m2 = ni.guess_mapping(
        {"A": "select", "B": "title", "C": "date"},
        {"A": ["London", "NY AM", "Азія"], "B": ["NQ", "ES", "NQ"],
         "C": ["2025-01-02", "2025-01-03", "2025-01-06"]})
    check("колонка без назви — впізнали за вмістом", m2.get("session") == "A")

    m3 = ni.guess_mapping({"Час": "text", "Пара": "title"},
                          {"Час": ["LONDON", "NY", "LONDON"], "Пара": ["NQ", "ES", "NQ"]})
    check("«Час» із сесіями всередині — не дата", m3.get("session") == "Час" and "date" not in m3)

    # Головне: підпис колонки — сильніший сигнал за наш словник. Сесії в
    # журналах звуть по-своєму, і незнайоме слово не має скасовувати підпис.
    m4 = ni.guess_mapping(
        {"Дата": "date", "Сесія": "select", "Інструмент": "title"},
        {"Дата": ["2025-01-02", "2025-01-03", "2025-01-06"],
         "Сесія": ["Ранок", "KZ-1", "OB", "Вечір"],
         "Інструмент": ["NQ", "ES", "NQ"]})
    check("свій словник назв — підпису віримо", m4.get("session") == "Сесія")

    # Але явно чуже забираємо: у «Результаті» числа — це RR, а не результат.
    m5 = ni.guess_mapping(
        {"Результат": "number", "Пара": "title", "Коли": "date"},
        {"Результат": ["1.5", "2", "3.2", "2.4"], "Пара": ["NQ", "ES", "NQ"],
         "Коли": ["2025-01-02", "2025-01-03", "2025-01-06"]})
    check("числа в «Результаті» — це RR", m5.get("result") != "Результат")


def check_values():
    check("NY AM", ni.is_session("NY AM"))
    check("Азія (ранок)", ni.is_session("Азія (ранок)"))
    check("опис сетапу — не сесія",
          not ni.is_session("London reversal after the Asian range sweep"))
    check("порожнє — не сесія", not ni.is_session(""))
    check("одне ім'я — один рядок статистики",
          ni.norm_session("London Killzone") == ni.norm_session("london killzone"))
    check("New York = NY", ni.norm_session("New York") == "NY")


def check_fill():
    """Дозапис чіпає лише порожні поля і лише дозволені."""
    import db

    seen = {}

    class FakeCur(object):
        rowcount = 1

    class FakeConn(object):
        def execute(self, sql, vals):
            seen["sql"], seen["vals"] = sql, vals
            return FakeCur()
        def commit(self): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False

    real, db.connect = db.connect, lambda: FakeConn()
    try:
        n = db.fill_blanks(7, "t-1", {"session": "NY AM", "pair": "", "emotion": "жадібність",
                                      "notion_id": "хай-но", "rr": 2.0, "risk": None})
        check("угоду оновили", n == 1)
        check("сесія в запиті", '"session"=CASE' in seen["sql"])
        check("порожнє поле не пишемо", '"pair"=CASE' not in seen["sql"])
        check("емоцію не чіпаємо", "emotion" not in seen["sql"])
        check("службові поля не чіпаємо", "notion_id=CASE" not in seen["sql"])
        check("значення передані параметрами", "NY AM" in seen["vals"] and 2.0 in seen["vals"])
        check("оновлюємо лише там, де порожньо", 'IS NULL OR "session"=' in seen["sql"])

        seen.clear()
        check("нічого дописувати — не ходимо в базу",
              db.fill_blanks(7, "t-1", {"session": "", "rr": None}) == 0 and not seen)
        check("угоди не знайшли — не ходимо в базу",
              db.fill_blanks(7, None, {"session": "NY AM"}) == 0 and not seen)
    finally:
        db.connect = real


def check_finder():
    """Угоду знаходимо і за notion_id, і за відбитком — кожну по разу."""
    import app, db

    asked = []
    real, db.fill_blanks = db.fill_blanks, lambda uid, tid, t: (asked.append(tid), 1)[1]
    try:
        rows = [
            {"id": "a", "notion_id": "n1", "date": "2025-01-02", "pair": "NQ",
             "position": "long", "result": "win"},
            # перенесена з іншої бази: свого notion_id в журналі немає
            {"id": "b", "notion_id": "", "date": "2025-01-03", "pair": "ES",
             "position": "short", "result": "loss"},
            {"id": "c", "notion_id": "", "date": "2025-01-03", "pair": "ES",
             "position": "short", "result": "loss"},
        ]
        fill = app.blank_filler(1, rows)

        fill("n1", dict(rows[0], id=None))
        check("знайшли за notion_id", asked == ["a"])

        fill("n-нове", dict(rows[1], id=None))
        fill("n-нове-2", dict(rows[2], id=None))
        check("два однакових входи — два різних рядки", asked[1:] == ["b", "c"])

        fill("n-нове-3", dict(rows[2], id=None))
        check("третього такого в журналі немає — нічого не чіпаємо", len(asked) == 3)

        fill("n1", dict(rows[0], id=None))
        check("той самий notion_id двічі — не дописуємо двічі", len(asked) == 3)
    finally:
        db.fill_blanks = real


check_column()
check_values()
check_fill()
check_finder()
print("\nусе добре")

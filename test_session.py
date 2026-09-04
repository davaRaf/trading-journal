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
        n = db.fill_blanks(7, "abc", {"session": "NY AM", "pair": "", "emotion": "жадібність",
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
              db.fill_blanks(7, "abc", {"session": "", "rr": None}) == 0 and not seen)
    finally:
        db.connect = real


check_column()
check_values()
check_fill()
print("\nусе добре")

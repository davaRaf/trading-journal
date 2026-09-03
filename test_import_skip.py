# -*- coding: utf-8 -*-
"""
Перевірка, що перенесення не задвоює журнал: python test_import_skip.py

Мережі тут немає: читання Notion підміняємо заздалегідь записаними рядками,
а перевіряємо справжній цикл перенесення — той самий, що працює на живій базі.

Головне питання: та сама угода, записана в другому журналі, приходить зі своїм
notion_id, і за ним її не впізнати. Впізнаємо за відбитком — день, інструмент,
напрямок, результат.
"""
import notion_public as npub
import tidy
from notion_import import Job

SCHEMA = {"c1": {"name": "Інструмент", "type": "title"},
          "c2": {"name": "Дата", "type": "date"},
          "c3": {"name": "Напрямок", "type": "select"},
          "c4": {"name": "Результат", "type": "select"}}

MAPPING = {"pair": "Інструмент", "date": "Дата",
           "position": "Напрямок", "result": "Результат"}

TABLE = [{"collection": "c", "view": "v", "space": "s"}]


def row(pair, date, position="Long", result="Win"):
    return {"Інструмент": pair, "Дата": date,
            "Напрямок": position, "Результат": result}


def fake_source(rows, prefix):
    """Підміняємо читання Notion: рядки беремо звідси, у мережу не ходимо.
    prefix — щоб id рядків у двох «базах» були різні, як воно і буває."""
    ids = ["%s-%d" % (prefix, i) for i in range(len(rows))]
    blocks = {i: {"__row": r} for i, r in zip(ids, rows)}
    npub.query = lambda *a, **k: {"recordMap": {"block": blocks}}
    npub.rows_of = lambda res: (ids, len(ids))
    npub.schema_of = lambda rm, cid: (SCHEMA, "Журнал")
    npub.prefetch_relations = lambda *a, **k: None
    npub._unwrap = lambda rec: rec
    npub.row_props = lambda block, schema: (block.get("__row") or {}, [])


def run(rows, prefix, seen=None, skip_similar=True):
    """Одне перенесення. Повертає (що доїхало, завдання)."""
    got = []
    job = Job("t")
    npub.run_public_import(
        job, TABLE, MAPPING,
        {"notes": False, "shots": False, "skipSimilar": skip_similar},
        ".", set(), set(), lambda items: got.extend(items), seen or {})
    return got, job


def case(name, got, want):
    ok = got == want
    print(("  ok  " if ok else "ПОМИЛКА") + "  " + name +
          ("" if ok else "  → отримали %s, чекали %s" % (got, want)))
    return ok


def main():
    ok = True

    # перший журнал: три угоди
    first = [row("US100", "2026-05-04"), row("US100", "2026-05-05"),
             row("XAUUSD", "2026-05-06", "Short", "Loss")]
    fake_source(first, "a")
    got, job = run(first, "a")
    ok &= case("порожній журнал — беремо все", (len(got), job.similar), (3, 0))

    journal = got                      # тепер це вміст журналу
    marks = tidy.prints(journal)

    # другий журнал: ті самі угоди, але свої id і своє написання інструмента
    second = [row("NAS 100", "2026-05-04"), row("US100", "2026-05-05"),
              row("xauusd", "2026-05-06", "short", "loss")]
    fake_source(second, "b")
    got, job = run(second, "b", marks)
    ok &= case("та сама угода з іншої бази — пропускаємо",
               (len(got), job.similar), (0, 3))

    # те саме, але людина зняла галочку
    fake_source(second, "b")
    got, job = run(second, "b", marks, skip_similar=False)
    ok &= case("галочку знято — переносимо все", (len(got), job.similar), (3, 0))

    # у другій базі є й нова угода
    third = [row("US100", "2026-05-04"), row("GER40", "2026-05-07")]
    fake_source(third, "c")
    got, job = run(third, "c", marks)
    ok &= case("нову угоду беремо, стару пропускаємо",
               ([t["pair"] for t in got], job.similar), (["GER40"], 1))

    # три однакових входи за день — це три угоди, а не одна
    day = [row("US100", "2026-06-01")] * 3
    fake_source(day, "d")
    got, _ = run(day, "d")
    ok &= case("три однакових входи за день доїжджають усі", len(got), 3)

    fake_source(day, "e")
    got, job = run(day, "e", tidy.prints(got[:2]))
    ok &= case("два вже є — беремо третій", (len(got), job.similar), (1, 2))

    print("\n" + ("усе добре" if ok else "є помилки"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""
Запити до бази — тільки параметрами: python test_sql_safe.py

Перевірка на майбутнє, а не на сьогодні: зараз усе чисто, і завдання
цього тесту — щоб так і лишилось. Варто одного разу зібрати запит із
рядків («... WHERE pair = '" + pair + "'»), і той, хто назве інструмент
`' OR 1=1 --`, читатиме чужі угоди.

Правильно — залишати в запиті `%s` і віддавати значення другим аргументом:
драйвер сам їх екранує, і рядок із лапками лишається рядком.

Що дозволено. Іноді в запит підставляють не значення, а ІМ'Я поля чи
таблиці — його `%s` замінити не може. Такі місця є, вони безпечні, поки
ім'я береться зі свого списку, а не з того, що надіслав гість. Дозволяємо
їх двома способами:

  * підставляється константа модуля (ВЕЛИКИМИ_ЛІТЕРАМИ) або готовий рядок;
  * у рядку стоїть мітка `sql-ok:` з поясненням, звідки взялось ім'я.

Мітка — не спосіб замовчати тест, а розписка: хто її ставить, той щойно
подивився, звідки приходить значення. Нових міток має бути мало, і кожна
пояснює себе сама.

Дивимось не на текст, а на розбір коду: так «execute(» всередині
коментаря чи рядка нас не обмане.
"""
import ast
import io
import os

SKIP = {".venv", "__pycache__", ".git", "node_modules"}
CALLS = {"execute", "executemany"}
MARK = "sql-ok"


def check(name, cond):
    print("  %-4s  %s" % ("ok" if cond else "ПАДАЄ", name))
    assert cond, name


def files():
    for root, dirs, names in os.walk("."):
        dirs[:] = [d for d in dirs if d not in SKIP]
        for n in names:
            if n.endswith(".py") and n != os.path.basename(__file__):
                yield os.path.join(root, n)


def names_in(node):
    """Усі імена, які підставляють у рядок."""
    out = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name):
            out.append(sub.id)
        elif isinstance(sub, ast.Attribute):
            out.append(sub.attr)
    return out


def safe_value(node, known=None, seen=()):
    """Чи можна підставити оце в текст запиту.

    Безпечне — те, що складено з наших власних рядків: константа модуля
    (ВЕЛИКИМИ_ЛІТЕРАМИ), готовий рядок і все, що з них зібрано, включно з
    ", ".join(... for k in FIELDS). Небезпечне — все, що прийшло ззовні:
    насамперед аргументи функції, бо саме туди потрапляє те, що надіслав
    гість.
    """
    known = known or {}
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.IfExp):             # "data_bt" if ... else "data"
        return safe_value(node.body, known, seen) and safe_value(node.orelse, known, seen)
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return all(safe_value(x, known, seen) for x in node.elts)
    if isinstance(node, ast.BinOp):
        return (safe_value(node.left, known, seen)
                and safe_value(node.right, known, seen))
    if isinstance(node, ast.JoinedStr):
        return all(safe_value(v.value if isinstance(v, ast.FormattedValue) else v,
                              known, seen) for v in node.values)
    if isinstance(node, (ast.GeneratorExp, ast.ListComp, ast.SetComp)):
        # "%s=%%s" % k for k in FIELDS — дивимось і на те, що беремо, і звідки
        inner = dict(known)
        for gen in node.generators:
            if not safe_value(gen.iter, known, seen):
                return False
            for name in names_in(gen.target):
                inner[name] = None              # прийшло з безпечного списку
        return safe_value(node.elt, inner, seen)
    if isinstance(node, ast.Call):
        # ", ".join(...), "{0}={0}".format(col) — безпечні, поки безпечні частини
        fn = node.func
        if isinstance(fn, ast.Attribute) and fn.attr in ("join", "format"):
            return (safe_value(fn.value, known, seen)
                    and all(safe_value(a, known, seen) for a in node.args))
        # len(FIELDS), sorted(...) — число чи той самий перелік, не чужий рядок
        if isinstance(fn, ast.Name) and fn.id in ("len", "int", "str", "sorted",
                                                  "list", "tuple", "range"):
            return all(safe_value(a, known, seen) for a in node.args)
        return False
    if isinstance(node, ast.Name):
        if node.id.upper() == node.id:          # FIELDS, _COLS, PER_USER_TABLES
            return True
        if node.id in seen:
            return False
        if node.id in known:
            values = known[node.id]
            if values is None:                  # взято з безпечного переліку
                return True
            return bool(values) and all(
                safe_value(v, known, seen + (node.id,)) for v in values)
    return False


def bad_sql(node, assigns, seen=()):
    """(рядок, у чому біда) для аргумента execute(). (0, "") — все гаразд."""
    if isinstance(node, ast.JoinedStr):
        return node.lineno, "запит зібраний f-рядком"
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Mod, ast.Add)):
        if not safe_value(node.right, assigns):
            return node.lineno, "у запит підставлено значення (%s)" % ", ".join(
                names_in(node.right) or ["?"])
        return bad_sql(node.left, assigns, seen)
    if isinstance(node, ast.Name) and node.id not in seen:
        # запит зібрали в змінну вище — дивимось, з чого саме
        for value in assigns.get(node.id, []):
            where, why = bad_sql(value, assigns, seen + (node.id,))
            if why:
                return where, why
    return 0, ""


def assigns_by_scope(tree):
    """Що чому присвоювали — окремо в кожній функції.

    Окремо, бо змінна `sql` є в десятку функцій: зваливши їх докупи, тест
    лаявся б на чистий запит через сусідній.
    """
    out = []
    for scope in [tree] + [n for n in ast.walk(tree)
                           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        found = {}
        for node in ast.walk(scope):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        found.setdefault(target.id, []).append(node.value)
            elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
                found.setdefault(node.target.id, []).append(node.value)
            elif isinstance(node, (ast.For, ast.AsyncFor)):
                # for table in PER_USER_TABLES — ім'я не гірше за сам список
                tgt, it = node.target, node.iter
                pairs = (isinstance(tgt, ast.Tuple) and isinstance(it, (ast.Tuple, ast.List))
                         and all(isinstance(e, (ast.Tuple, ast.List))
                                 and len(e.elts) == len(tgt.elts) for e in it.elts))
                if pairs:
                    # for col, n in (("trades_cap", trades), ...) — по стовпчиках:
                    # ліворуч самі назви полів, праворуч числа, і плутати їх не треба
                    for i, part in enumerate(tgt.elts):
                        for name in names_in(part):
                            for e in it.elts:
                                found.setdefault(name, []).append(e.elts[i])
                else:
                    for name in names_in(tgt):
                        found.setdefault(name, []).append(it)
            elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                  and node.func.attr in ("append", "extend")
                  and isinstance(node.func.value, ast.Name) and node.args):
                # sets = []; sets.append('"поле"=%s') — список росте так само
                found.setdefault(node.func.value.id, []).append(node.args[0])
        out.append((scope, found))
    return out


def scan(path):
    """Список (рядок, у чому біда) для одного файла."""
    src = io.open(path, encoding="utf-8").read()
    lines = src.split("\n")
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return [(0, "файл не розбирається")]

    out = []
    for scope, assigns in assigns_by_scope(tree):
        for node in ast.walk(scope):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if name not in CALLS or not node.args:
                continue
            where, why = bad_sql(node.args[0], assigns)
            if not why:
                continue
            # розписка поруч: рядок із міткою або той, що над ним
            near = "\n".join(lines[max(0, where - 3):where])
            if MARK in near:
                continue
            if (where, why) not in out:
                out.append((where, why))
    return sorted(set(out))


def main():
    print("запити до бази")
    seen, bad = 0, []
    for path in files():
        seen += 1
        for line, why in scan(path):
            bad.append("%s:%d — %s" % (path.replace(os.sep, "/"), line, why))
    for one in bad:
        print("      " + one)
    check("файли взагалі знайшлись", seen > 20)
    check("жоден запит не зібраний із рядків", not bad)

    # А тепер навпаки: переконаємось, що сторож не сліпий.
    sample = ("def f(conn, pair):\n"
              "    conn.execute('SELECT * FROM trades WHERE pair = ' + pair)\n"
              "def g(conn, pair):\n"
              "    sql = 'SELECT * FROM trades WHERE pair = %s' % pair\n"
              "    conn.execute(sql)\n"
              "def h(conn, pair):\n"
              "    conn.execute(f'SELECT * FROM trades WHERE pair = {pair}')\n")
    tree = ast.parse(sample)
    caught = 0
    for scope, assigns in assigns_by_scope(tree):
        for node in ast.walk(scope):
            if isinstance(node, ast.Call) and node.args and getattr(
                    node.func, "attr", "") in CALLS:
                if bad_sql(node.args[0], assigns)[1]:
                    caught += 1
    check("ловимо і склейку, і %s, і f-рядок", caught >= 3)
    print("\nвсе гаразд")


if __name__ == "__main__":
    main()

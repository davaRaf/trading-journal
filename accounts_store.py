# -*- coding: utf-8 -*-
"""
Рахунки, на яких людина торгує: свій депозит і рахунки проп-фірм.

Навіщо окрема сутність. В угоді вже є поле `account` — вільний рядок, який
людина пише сама. Його достатньо, щоб розкласти угоди по рахунках, але не
досить, щоб сказати «на рахунку зараз $52 300» чи «до ліміту просадки
лишилось 1.2%»: журнал рахує все у відсотках від депозиту, а розміру
депозиту він ніколи не знав.

Тому тут лежить те, чого немає в угоді: скільки грошей було на старті, у
якій валюті, яка ціль і які ліміти просадки поставила фірма. Відсотки
беруться з угод, гроші — звідси.

Звʼязок з угодами — по імені, а не по id. Так нічого не треба міняти в
самих угодах: рахунок можна завести пізніше, ніж записані угоди, і вони
самі до нього підтягнуться. Ціна цього — перейменував рахунок, і звʼязок
розпався; тому перейменування веде за собою `db.rename_value`.

Один людський рахунок — один рядок. Видалення рахунку не чіпає угод:
угоди лишаються, просто без картки.
"""
import datetime
import re

import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
  id            BIGSERIAL PRIMARY KEY,
  user_id       BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name          TEXT NOT NULL DEFAULT '',
  firm          TEXT NOT NULL DEFAULT '',
  kind          TEXT NOT NULL DEFAULT 'own',
  start_balance DOUBLE PRECISION,
  current_balance DOUBLE PRECISION,
  currency      TEXT NOT NULL DEFAULT 'USD',
  target_pct    DOUBLE PRECISION,
  dd_daily_pct  DOUBLE PRECISION,
  dd_total_pct  DOUBLE PRECISION,
  opened_at     TEXT NOT NULL DEFAULT '',
  closed_at     TEXT NOT NULL DEFAULT '',
  status        TEXT NOT NULL DEFAULT 'active',
  reason        TEXT NOT NULL DEFAULT '',
  note          TEXT NOT NULL DEFAULT '',
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS accounts_user ON accounts (user_id, id);
-- Два рахунки з однаковою назвою в однієї людини не мають сенсу: угоди
-- звʼязані саме по імені, і розрізнити їх було б нічим.
CREATE UNIQUE INDEX IF NOT EXISTS accounts_user_name ON accounts (user_id, lower(name));

-- Баланс, переписаний з кабінету фірми. Зʼявився пізніше за саму таблицю:
-- журнал рахує баланс сам, але його арифметика знає лише ті угоди, що в
-- ньому записані. Хто прийшов у журнал посеред челенджу, бачив розбіжність
-- із кабінетом і не мав чим її виправити.
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS current_balance DOUBLE PRECISION;

-- На яку дату той баланс правдивий. Без цієї дати вписана цифра застигала
-- назавжди: людина переписала баланс з кабінету, записала ще десять угод —
-- а картка показувала те саме число, ніби угод не було.
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS balance_at TEXT NOT NULL DEFAULT '';

-- Скільки угод цього рахунку вже лежало в журналі, коли баланс вписали.
-- Дата для цього замало точна: угоди того самого дня, що й сам баланс,
-- випадали з підрахунку зовсім — людина заводила рахунок і тут-таки
-- записувала дві угоди, а картка показувала колишнє число.
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS balance_n INTEGER NOT NULL DEFAULT 0;
-- Множник журналу на мить, коли баланс вписали. NULL — позначки ще
-- немає: така картка рахується по-старому, до першого перезапису.
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS balance_f DOUBLE PRECISION;

-- Разова чистка імен, які лягли в базу до нормалізації: пробіл на кінці
-- робив «FTMO » і «FTMO» різними рахунками, а в браузері вони склеювались
-- в одну картку. Пари, де чисте імʼя вже зайняте, не чіпаємо — інакше
-- впав би унікальний індекс; їх розведе нумерація при наступному збереженні.
UPDATE accounts a SET name = btrim(regexp_replace(name, '[[:space:]]+', ' ', 'g'))
 WHERE name <> btrim(regexp_replace(name, '[[:space:]]+', ' ', 'g'))
   AND NOT EXISTS (SELECT 1 FROM accounts b WHERE b.user_id = a.user_id
                     AND b.id <> a.id
                     AND lower(b.name)
                       = lower(btrim(regexp_replace(a.name, '[[:space:]]+', ' ', 'g'))));
"""

_ready = False


def init():
    global _ready
    if _ready:
        return
    with db.connect() as conn:
        conn.execute(SCHEMA)
    _ready = True


# Статуси: активний; пройдений (челендж здано); злитий (порушено ліміт);
# закритий (людина сама пішла). «Злитий» і «закритий» — різні речі, і в
# розборі вони читаються по-різному.
STATUS = ("active", "passed", "failed", "closed")
STATUS_FOR = {
    "funded": ("active", "failed"),
    "own": ("active", "failed", "closed"),
    "challenge": STATUS,
}
KINDS = ("own", "challenge", "funded")

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Будь-який пробільний символ, зокрема нерозривний: такі приїжджають
# із буфера обміну й на око не відрізняються від звичайного.
SPACE_RE = re.compile(r"[\s\u00a0\u202f\u2007]+")

NUM_FIELDS = ("start_balance", "current_balance", "target_pct",
               "dd_daily_pct", "dd_total_pct", "balance_f")
TEXT_FIELDS = ("name", "firm", "kind", "currency", "opened_at", "closed_at",
               "status", "reason", "note", "balance_at")
# Лічильник угод — окремо: це ціле число, і зберігати його дробовим було б
# просто неправдою про те, що воно означає.
INT_FIELDS = ("balance_n",)
FIELDS = TEXT_FIELDS + NUM_FIELDS + INT_FIELDS


def _num(v):
    """Порожнє поле — це «не задано», а не нуль: ліміт 0% і відсутній
    ліміт виглядають однаково, але означають протилежне."""
    if v is None or v == "":
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and abs(f) != float("inf") else None


def _date(v):
    v = str(v or "").strip()[:10]
    return v if DATE_RE.match(v) else ""


def norm_name(v):
    """Імʼя рахунку до одного вигляду.

    Звʼязок з угодами йде саме по імені, і будь-яка невидима різниця в
    ньому — пробіл на кінці, два пробіли поспіль, нерозривний пробіл з
    буфера обміну — залишає картку без угод, хоча на око все збігається.
    Тому пробіли зводимо до одного звичайного, а краї обрізаємо.
    """
    return SPACE_RE.sub(" ", str(v or "")).strip()[:200]


# Хвіст-лічильник у кінці імені: «FTMO 100k 2». Другий рахунок під тією ж
# назвою отримує двійку — перший лишається без номера, бо він і був перший.
_TAIL_RE = re.compile(r"^(.*?)\s+(\d{1,3})$")


def free_name(user_id, name, skip_id=None):
    """Вільне імʼя для рахунку: якщо таке вже є, дописуємо номер.

    Раніше сервер відповідав «назва зайнята» і не зберігав нічого. Але два
    челенджі однієї фірми одного розміру — звичайна річ, і людині все одно
    доводилось вигадувати назву руками. Тепер вигадуємо ми: «FTMO 100k»,
    «FTMO 100k 2», «FTMO 100k 3».
    """
    init()
    base = norm_name(name)
    if not base:
        return base
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT id, name FROM accounts WHERE user_id=%s", (user_id,)).fetchall()
    taken = set()
    for r in rows:
        if skip_id is not None and r["id"] == skip_id:
            continue
        taken.add(norm_name(r["name"]).lower())
    if base.lower() not in taken:
        return base
    # Уже пронумероване імʼя нарощуємо далі, а не ліпимо номер до номера:
    # інакше з «FTMO 2» вийшло б «FTMO 2 2».
    m = _TAIL_RE.match(base)
    stem = m.group(1) if m else base
    n = 2
    while n < 1000:
        cand = "%s %d" % (stem, n)
        if cand.lower() not in taken:
            return cand[:200]
        n += 1
    return base


def clean(body):
    """Що прийшло з браузера — до вигляду, який кладеться в базу."""
    a = {}
    for k in TEXT_FIELDS:
        a[k] = str((body or {}).get(k) or "").strip()[:200]
    for k in NUM_FIELDS:
        a[k] = _num((body or {}).get(k))
    for k in INT_FIELDS:
        n = _num((body or {}).get(k))
        a[k] = max(0, int(n)) if n is not None else 0
    a["kind"] = a["kind"] if a["kind"] in KINDS else "own"
    a["status"] = a["status"] if a["status"] in STATUS else "active"
    a["currency"] = (a["currency"] or "USD")[:8]
    a["name"] = norm_name(a["name"])
    a["opened_at"] = _date(a["opened_at"])
    a["closed_at"] = _date(a["closed_at"])
    a["balance_at"] = _date(a["balance_at"])
    # Дата й лічильник без самого балансу нічого не означають.
    if a["current_balance"] is None:
        a["balance_at"] = ""
        a["balance_n"] = 0
        a["balance_f"] = None
    # Не кожен стан має сенс для кожного типу. «Пройдений» буває тільки в
    # челенджа — це його єдина мета; свій депозит і фандед проходити нема
    # куди. Фандед ще й не «закривають»: його торгують або зливають.
    #
    # Те саме правило стоїть у формі; тут воно на випадок, якщо тип змінили,
    # а стан лишився від попереднього життя рахунку.
    if a["status"] not in STATUS_FOR.get(a["kind"], STATUS):
        a["status"] = "active"
    # Поки рахунок живий, дати закриття й причини бути не може: інакше
    # картка показувала б «активний» і поруч «злитий тоді-то».
    if a["status"] == "active":
        a["closed_at"] = ""
        a["reason"] = ""
    return a


def _row(r):
    a = {k: r[k] for k in FIELDS}
    a["id"] = r["id"]
    return a


def lst(user_id):
    init()
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM accounts WHERE user_id=%s ORDER BY "
            # спершу живі рахунки, всередині — свіжіші зверху
            "(status='active') DESC, coalesce(nullif(opened_at,''), '0000') DESC, id DESC",
            (user_id,)).fetchall()
    return [_row(r) for r in rows]


def get(user_id, acc_id):
    init()
    with db.connect() as conn:
        r = conn.execute("SELECT * FROM accounts WHERE user_id=%s AND id=%s",
                         (user_id, acc_id)).fetchone()
    return _row(r) if r else None


def _stamp_balance(a, old=None):
    """Дата, на яку правдивий вписаний руками баланс.

    Окремим полем у формі її не питаємо: людина переписує баланс з кабінету
    саме сьогодні, і зайве питання тут нікому не потрібне. Стару дату
    зберігаємо, поки саме число не змінилось, — інакше кожне збереження
    картки (правка нотатки, ліміту) зсувало б мітку вперед і викидало з
    підрахунку всі угоди, записані після неї.

    Разом із датою тримаємо `balance_f` — множник журналу на ту мить.
    Баланс потім рахується як вписане × (множник зараз / множник тоді),
    тож кожна угода рухає його рівно на свій результат. `balance_n` —
    попередня, гірша мірка (число угод); лишається заради карток,
    записаних до цієї зміни.

    Раніше тут було: `balance_n` — скільки угод цього рахунку вже
    було в журналі, коли баланс вписали. Саме він і рахує: угоди після
    цієї позначки додаються до балансу, попередні вважаються врахованими
    в цифрі з кабінету. Лічильник приходить із браузера, бо тільки він
    бачить угоди в момент збереження; дата лишається для підпису на картці.
    """
    if a["current_balance"] is None:
        a["balance_at"] = ""
        a["balance_n"] = 0
        a["balance_f"] = None
        return a
    same = old is not None and old.get("current_balance") == a["current_balance"]
    if same and old.get("balance_at"):
        a["balance_at"] = old["balance_at"]
        a["balance_n"] = old.get("balance_n") or 0
        # Множника може не бути зовсім: картки, заведені до його появи,
        # живуть із самим лічильником. Тоді беремо свіжий, що приїхав із
        # браузера, — інакше така картка лишилась би на старому, гіршому
        # підрахунку назавжди, бо саме число балансу людина не міняє.
        if old.get("balance_f"):
            a["balance_f"] = old["balance_f"]
    elif not a["balance_at"] or not same:
        a["balance_at"] = datetime.date.today().isoformat()
    return a


def add(user_id, body):
    init()
    a = _stamp_balance(clean(body))
    # Назву підбираємо вільну: два челенджі однієї фірми одного розміру —
    # звичайна річ, і відмовляти через збіг імен означало б змушувати
    # людину вигадувати назву руками.
    a["name"] = free_name(user_id, a["name"])
    cols = ", ".join(FIELDS)
    marks = ", ".join(["%s"] * len(FIELDS))
    with db.connect() as conn:
        r = conn.execute(
            "INSERT INTO accounts (user_id, %s) VALUES (%%s, %s) RETURNING id" % (cols, marks),
            tuple([user_id] + [a[k] for k in FIELDS])).fetchone()
    a["id"] = r["id"]
    return a


def put(user_id, acc_id, body):
    """Правка рахунку. Перейменування веде за собою угоди: звʼязок у нас
    по імені, і без цього всі угоди старої назви лишились би без картки.

    Обидві дії їдуть однією транзакцією. Раніше картка й угоди зберігались
    окремо, а помилка перейменування ще й глушилась мовчки — картка
    отримувала нове імʼя, угоди лишались на старому, і рахунок на очах
    ставав порожнім без жодного слова.
    """
    init()
    old = get(user_id, acc_id)
    if not old:
        return None
    a = _stamp_balance(clean(body), old)
    a["name"] = free_name(user_id, a["name"], acc_id)
    sets = ", ".join("%s=%%s" % k for k in FIELDS)
    with db.connect() as conn:
        conn.execute("UPDATE accounts SET %s, updated_at=now() "
                     "WHERE user_id=%%s AND id=%%s" % sets,
                     tuple([a[k] for k in FIELDS] + [user_id, acc_id]))
        if old["name"] and a["name"] and old["name"] != a["name"]:
            db.rename_value(user_id, "account", [old["name"]], a["name"], conn=conn)
        conn.commit()
    a["id"] = acc_id
    return a


def drop(user_id, acc_id):
    """Прибираємо тільки картку. Угоди лишаються як були: людина
    видаляє опис рахунку, а не свою історію.

    Через це картка з тією самою назвою, заведена пізніше, підбере ті самі
    угоди. Це навмисно — саме так рахунок можна завести заднім числом, —
    але сказати про це людина має право заздалегідь, тому у вікні
    підтвердження стоїть кількість угод, які лишаються з цією назвою.
    """
    init()
    with db.connect() as conn:
        conn.execute("DELETE FROM accounts WHERE user_id=%s AND id=%s", (user_id, acc_id))

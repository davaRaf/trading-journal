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
KINDS = ("own", "challenge", "funded")

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

NUM_FIELDS = ("start_balance", "current_balance", "target_pct",
               "dd_daily_pct", "dd_total_pct")
TEXT_FIELDS = ("name", "firm", "kind", "currency", "opened_at", "closed_at",
               "status", "reason", "note")
FIELDS = TEXT_FIELDS + NUM_FIELDS


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


def clean(body):
    """Що прийшло з браузера — до вигляду, який кладеться в базу."""
    a = {}
    for k in TEXT_FIELDS:
        a[k] = str((body or {}).get(k) or "").strip()[:200]
    for k in NUM_FIELDS:
        a[k] = _num((body or {}).get(k))
    a["kind"] = a["kind"] if a["kind"] in KINDS else "own"
    a["status"] = a["status"] if a["status"] in STATUS else "active"
    a["currency"] = (a["currency"] or "USD")[:8]
    a["opened_at"] = _date(a["opened_at"])
    a["closed_at"] = _date(a["closed_at"])
    # Фандед-рахунок нема де «пройти» і нема сенсу «закривати»: челендж
    # лишився позаду, далі його або торгують, або зливають. Те саме
    # правило стоїть у формі; тут воно на випадок, якщо тип змінили,
    # а стан лишився від попереднього життя рахунку.
    if a["kind"] == "funded" and a["status"] not in ("active", "failed"):
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


def name_taken(user_id, name, skip_id=None):
    init()
    with db.connect() as conn:
        r = conn.execute(
            "SELECT id FROM accounts WHERE user_id=%s AND lower(name)=lower(%s) "
            "AND (%s::bigint IS NULL OR id<>%s::bigint)",
            (user_id, str(name or "").strip(), skip_id, skip_id)).fetchone()
    return bool(r)


def add(user_id, body):
    init()
    a = clean(body)
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
    по імені, і без цього всі угоди старої назви лишились би без картки."""
    init()
    old = get(user_id, acc_id)
    if not old:
        return None
    a = clean(body)
    sets = ", ".join("%s=%%s" % k for k in FIELDS)
    with db.connect() as conn:
        conn.execute("UPDATE accounts SET %s, updated_at=now() "
                     "WHERE user_id=%%s AND id=%%s" % sets,
                     tuple([a[k] for k in FIELDS] + [user_id, acc_id]))
    if old["name"] and a["name"] and old["name"] != a["name"]:
        try:
            db.rename_value(user_id, "account", [old["name"]], a["name"])
        except Exception:
            pass
    a["id"] = acc_id
    return a


def drop(user_id, acc_id):
    """Прибираємо тільки картку. Угоди лишаються як були: людина
    видаляє опис рахунку, а не свою історію."""
    init()
    with db.connect() as conn:
        conn.execute("DELETE FROM accounts WHERE user_id=%s AND id=%s", (user_id, acc_id))

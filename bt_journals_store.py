# -*- coding: utf-8 -*-
"""
Журнали бектесту: окремі набори прогонів на історії.

Навіщо. Бектест ганяють по кілька штук паралельно — US100 за березень,
золото за рік, та сама ТС на іншому активі — і статистика одного прогону
не має змішуватись з іншим. Тому в режимі бектесту журнал обирають, і
«Огляд», «Журнал» та «Аналітика» показують тільки його угоди.

Звʼязок з угодами — по імені, як у рахунків: в угоді є поле `bt_run`
(колись підпис «Прогін»), і журнал — це те саме імʼя плюс опис: актив,
період історії, нотатка. Угоди міняти не треба, а старі прогони стають
журналами самі.

На відміну від рахунку, журнал без угод нічого не варт: видалити журнал —
значить видалити й його угоди. Про це питаємо у вікні підтвердження з
числом угод.
"""
import re

import accounts_store
import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS bt_journals (
  id          BIGSERIAL PRIMARY KEY,
  user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name        TEXT NOT NULL DEFAULT '',
  asset       TEXT NOT NULL DEFAULT '',
  period_from TEXT NOT NULL DEFAULT '',
  period_to   TEXT NOT NULL DEFAULT '',
  note        TEXT NOT NULL DEFAULT '',
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS bt_journals_user ON bt_journals (user_id, id);
-- Угоди звʼязані з журналом по імені, тож два однакових імені в однієї
-- людини розрізнити було б нічим.
CREATE UNIQUE INDEX IF NOT EXISTS bt_journals_user_name ON bt_journals (user_id, lower(name));
"""

_ready = False


def init():
    global _ready
    if _ready:
        return
    with db.connect() as conn:
        conn.execute(SCHEMA)
    _ready = True


TEXT_FIELDS = ("name", "asset", "period_from", "period_to", "note")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TAIL_RE = re.compile(r"^(.*?)\s+(\d{1,3})$")

norm_name = accounts_store.norm_name


def _date(v):
    v = str(v or "").strip()[:10]
    return v if DATE_RE.match(v) else ""


def clean(body):
    """Що прийшло з браузера — до вигляду, який кладеться в базу."""
    j = {k: str((body or {}).get(k) or "").strip()[:200] for k in TEXT_FIELDS}
    j["name"] = norm_name(j["name"])
    j["asset"] = norm_name(j["asset"])[:60]
    j["note"] = str((body or {}).get("note") or "").strip()[:1000]
    j["period_from"] = _date(j["period_from"])
    j["period_to"] = _date(j["period_to"])
    # Переплутані краї періоду — не причина відмовляти: міняємо місцями.
    if j["period_from"] and j["period_to"] and j["period_from"] > j["period_to"]:
        j["period_from"], j["period_to"] = j["period_to"], j["period_from"]
    return j


def pick_free(base, taken):
    """Вільне імʼя серед зайнятих (`taken` — у нижньому регістрі):
    «US100», «US100 2», «US100 3». Як у рахунків — не відмовляємо через
    збіг, а дописуємо номер."""
    if not base or base.lower() not in taken:
        return base
    m = _TAIL_RE.match(base)
    stem = m.group(1) if m else base
    n = 2
    while n < 1000:
        cand = "%s %d" % (stem, n)
        if cand.lower() not in taken:
            return cand[:200]
        n += 1
    return base


def free_name(user_id, name, skip_id=None):
    init()
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT id, name FROM bt_journals WHERE user_id=%s", (user_id,)).fetchall()
    taken = {norm_name(r["name"]).lower() for r in rows
             if skip_id is None or r["id"] != skip_id}
    return pick_free(norm_name(name), taken)


def _row(r):
    j = {k: r[k] for k in TEXT_FIELDS}
    j["id"] = r["id"]
    return j


def lst(user_id):
    init()
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM bt_journals WHERE user_id=%s ORDER BY id DESC",
            (user_id,)).fetchall()
    return [_row(r) for r in rows]


def get(user_id, jid):
    init()
    with db.connect() as conn:
        r = conn.execute("SELECT * FROM bt_journals WHERE user_id=%s AND id=%s",
                         (user_id, jid)).fetchone()
    return _row(r) if r else None


def add(user_id, body, adopt=None):
    """Новий журнал. `adopt` — імʼя, під яким угоди вже лежать (зокрема
    порожнє: прогони без підпису). Їх переносимо в новий журнал тією ж
    транзакцією, інакше журнал зʼявився б порожнім, а угоди — без журналу."""
    init()
    j = clean(body)
    j["name"] = free_name(user_id, j["name"])
    cols = ", ".join(TEXT_FIELDS)
    marks = ", ".join(["%s"] * len(TEXT_FIELDS))
    with db.connect() as conn:
        r = conn.execute(
            "INSERT INTO bt_journals (user_id, %s) VALUES (%%s, %s) RETURNING id" % (cols, marks),
            tuple([user_id] + [j[k] for k in TEXT_FIELDS])).fetchone()
        if adopt is not None and adopt != j["name"]:
            _rename_trades(conn, user_id, adopt, j["name"])
        conn.commit()
    j["id"] = r["id"]
    return j


def put(user_id, jid, body):
    """Правка журналу. Перейменування веде за собою угоди — однією
    транзакцією, щоб журнал не лишився порожнім на пів дороги."""
    init()
    old = get(user_id, jid)
    if not old:
        return None
    j = clean(body)
    j["name"] = free_name(user_id, j["name"], jid)
    sets = ", ".join("%s=%%s" % k for k in TEXT_FIELDS)
    with db.connect() as conn:
        conn.execute("UPDATE bt_journals SET %s, updated_at=now() "
                     "WHERE user_id=%%s AND id=%%s" % sets,
                     tuple([j[k] for k in TEXT_FIELDS] + [user_id, jid]))
        if old["name"] != j["name"]:
            _rename_trades(conn, user_id, old["name"], j["name"])
        conn.commit()
    j["id"] = jid
    return j


def _rename_trades(conn, user_id, old, new):
    # Порівнюємо без регістру й зайвих пробілів — так само браузер
    # розкладає угоди по журналах. `bt_run` немає серед полів, які
    # зводить db.rename_value, тож пишемо запит тут.
    conn.execute(
        "UPDATE trades SET bt_run=%s WHERE user_id=%s AND kind='bt' "
        "AND lower(btrim(regexp_replace(bt_run, '[[:space:]]+', ' ', 'g'))) = lower(%s)",
        (new, user_id, norm_name(old)))


def drop(user_id, jid):
    """Прибирає журнал разом з його угодами. Повертає (скільки угод
    прибрали, файли скриншотів) — файли видаляє app.py, як і для угоди.
    None — такого журналу немає."""
    init()
    j = get(user_id, jid)
    if not j:
        return None
    with db.connect() as conn:
        rows = conn.execute(
            "DELETE FROM trades WHERE user_id=%s AND kind='bt' "
            "AND lower(btrim(regexp_replace(bt_run, '[[:space:]]+', ' ', 'g'))) = lower(%s) "
            "RETURNING screenshots",
            (user_id, norm_name(j["name"]))).fetchall()
        conn.execute("DELETE FROM bt_journals WHERE user_id=%s AND id=%s", (user_id, jid))
        conn.commit()
    files = []
    for r in rows:
        for sh in r["screenshots"] or []:
            if isinstance(sh, dict) and sh.get("file"):
                files.append(sh["file"])
    return len(rows), files

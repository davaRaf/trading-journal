"""
Щоденний зліпок журналу.

Навіщо. Журнал живе в одній базі, і всі способи його втратити — тихі:
невдале перенесення з Notion затерло поля, зайве натискання «видалити»,
збій на боці бази. Помічають таке не одразу, і відкотити нема куди.

Де тримаємо. У самій базі, окремою таблицею, а не файлом на диску:
контейнер хостингу стирається при кожному оновленні коду, тож файл там
живе до найближчого деплою. Зліпок у базі переживає і перезапуск, і
оновлення, і покриває найчастіший випадок — коли дані зіпсував не збій
бази, а дія в журналі.

Скільки. Останні 14 днів на людину; глибше вже нікому не треба, а
місце воно їсть щодня.

Це не заміна вивантаженню собі: кнопка «Завантажити журнал» у
налаштуваннях віддає той самий зліпок файлом, і ось він уже лежить поза
нашими руками.
"""
import datetime
import json
import threading
import time

import db
import day_store
import ts_store

KEEP = 14                  # скільки денних зліпків тримаємо на людину
EVERY = 3600               # як часто прокидаємось і дивимось на дату
VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS backups (
  user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  made_on DATE NOT NULL,
  made_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  trades  INT NOT NULL DEFAULT 0,
  data    JSONB NOT NULL,
  PRIMARY KEY (user_id, made_on)
);
"""
_ready = False
_lock = threading.Lock()


def init():
    global _ready
    if _ready:
        return
    with _lock:
        if _ready:
            return
        with db.connect() as conn:
            conn.execute(SCHEMA)
        _ready = True


def _plain(x):
    """Дати й Decimal у звичайні типи — щоб це можна було покласти в JSON."""
    return json.loads(json.dumps(x, ensure_ascii=False, default=str))


def _notion(uid):
    """Налаштування перенесення, якщо таблиця вже є (її створює app.py)."""
    try:
        with db.connect() as conn:
            row = conn.execute("SELECT data FROM notion_conf WHERE user_id=%s",
                               (uid,)).fetchone()
        return dict(row["data"]) if row and row["data"] else {}
    except Exception:
        return {}


def snapshot(uid):
    """Усе, що людина вносила руками. Скріни не беремо: це файли, і в
    JSON вони перетворили б зліпок на десятки мегабайт — у ньому лишаються
    їхні імена, самі картинки лежать окремо."""
    user = db.get_user(uid) or {}
    return _plain({
        "version": VERSION,
        "made": datetime.datetime.now(datetime.timezone.utc)
                        .replace(microsecond=0).isoformat(),
        "user": {"id": uid, "email": user.get("email"),
                 "nickname": user.get("nickname")},
        "trades": db.list_trades(uid),
        "days": day_store.notes_since(uid, "0001-01-01"),
        "strategy": ts_store.get(uid),
        "notion": _notion(uid),
    })


def _worth(snap):
    """Порожній журнал зберігати нема сенсу — лише сміття в таблиці."""
    return bool(snap.get("trades") or snap.get("days") or snap.get("strategy"))


def save(uid, snap=None):
    """Зліпок за сьогодні. Другий виклик того самого дня просто оновлює."""
    init()
    snap = snap or snapshot(uid)
    if not _worth(snap):
        return False
    from psycopg.types.json import Jsonb
    today = datetime.date.today()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO backups (user_id, made_on, trades, data) VALUES (%s,%s,%s,%s) "
            "ON CONFLICT (user_id, made_on) DO UPDATE SET "
            "data=EXCLUDED.data, trades=EXCLUDED.trades, made_at=now()",
            (uid, today, len(snap.get("trades") or []), Jsonb(snap)))
        conn.execute(
            "DELETE FROM backups WHERE user_id=%s AND made_on NOT IN ("
            "  SELECT made_on FROM backups WHERE user_id=%s "
            "  ORDER BY made_on DESC LIMIT %s)", (uid, uid, KEEP))
    return True


def have_today(uid):
    init()
    with db.connect() as conn:
        row = conn.execute("SELECT 1 FROM backups WHERE user_id=%s AND made_on=%s",
                           (uid, datetime.date.today())).fetchone()
    return bool(row)


def listing(uid):
    """Які зліпки є — для відповіді в налаштуваннях."""
    init()
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT made_on, made_at, trades FROM backups WHERE user_id=%s "
            "ORDER BY made_on DESC", (uid,)).fetchall()
    return [{"date": str(r["made_on"]), "at": r["made_at"].isoformat(),
             "trades": r["trades"]} for r in rows]


def _users():
    with db.connect() as conn:
        rows = conn.execute("SELECT id FROM users ORDER BY id").fetchall()
    return [r["id"] for r in rows]


def run_once():
    """Кому сьогодні ще не робили — зробити. Повертає, скільком зробили."""
    made = 0
    for uid in _users():
        try:
            if have_today(uid):
                continue
            if save(uid):
                made += 1
        except Exception as ex:
            print("backup:", uid, ex)
    return made


def loop():
    """Фоновий потік: щогодини дивимось, чи є зліпок за сьогодні.

    Саме так, а не «раз на 24 години від запуску»: сервер перезапускається
    частіше, ніж раз на добу, і відлік від старту весь час збивався б."""
    time.sleep(90)                       # дати серверу піднятись
    while True:
        try:
            n = run_once()
            if n:
                print("backup: зліпків зроблено —", n)
        except Exception as ex:
            print("backup loop:", ex)
        time.sleep(EVERY)


def start():
    threading.Thread(target=loop, daemon=True, name="backup").start()

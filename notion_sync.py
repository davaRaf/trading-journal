"""
Сам перечитує Notion — раз на дві години.

Досі оновлення було ручним: зайди в «Підключення», натисни на базу, з
якої переносив, і нові угоди доїдуть. Працює, але про це треба пам'ятати,
а журнал тим часом відстає від Notion на кілька днів.

Тут те саме, тільки без натискання. Для кожної збереженої бази робимо той
самий прохід, що й людина руками: читаємо таблиці за посиланням і
переносимо з тим самим зіставленням колонок. Нові угоди додаються, старі
не задвоюються — кожна пам'ятає свій id у Notion, а ті, що приїхали з
іншої бази, впізнаються за відбитком (день, інструмент, напрямок,
результат). Порожні поля в уже записаних угодах дозаповнюються.

Що НЕ робимо: не видаляємо. Якщо угоду прибрали в Notion, у журналі вона
лишиться — журнал тут головний, і мовчки викидати з нього записи через
чужу правку було б найгіршим із можливих сюрпризів.

Нові угоди позначаємо тим самим ключем перенесення, що й початкове:
тоді кнопка «прибрати» біля бази й далі прибирає її цілком, а не лише те,
що переносили руками.
"""
import datetime
import secrets
import threading
import time

import db
import notion_import as notion
import notion_public as npub
import tidy

EVERY = 2 * 3600           # раз на дві години
FIRST = 300                # перший прохід — через 5 хв після старту сервера
GAP = 20                   # пауза між базами, щоб не довбати Notion поспіль
MAX_TABLES = 12            # більше таблиць в одному журналі не буває
OPTS = {"notes": True, "shots": True, "skipExisting": True, "skipSimilar": True}

# те, що дає app.py: воно знає і про диск зі скрінами, і про журнал
_hooks = {}


def _tables_for(url):
    """Які таблиці читати. Людина вибирала їх руками, і ми цього вибору
    не зберігали, тож повторюємо логіку вікна: беремо найкращу таблицю
    й усі рівні їй за кількістю впізнаних колонок. Журнал, розбитий по
    місяцях, — це саме такі таблиці-близнюки, а випадкове оглавлення
    поруч має впізнаних колонок менше й сюди не потрапляє."""
    tables, _notes = npub.find_tables(url)
    if not tables:
        return []
    best = tables[0].get("matched") or 0
    if not best:
        return []
    same = [t for t in tables if (t.get("matched") or 0) >= best]
    return same[:MAX_TABLES]


def sync_source(uid, src):
    """Одна база. Повертає, скільки додали і скільки дозаповнили."""
    mapping = src.get("mapping") or {}
    if not src.get("url") or not mapping.get("pair"):
        return 0, 0                       # старий запис без зіставлення
    tables = _tables_for(src["url"])
    if not tables:
        return 0, 0

    job = notion.Job(secrets.token_urlsafe(6))
    # нові угоди належать тому самому перенесенню, що й попередні
    job.batch = src["id"]
    known, seen = db.notion_known(uid)
    rows = db.list_trades(uid)
    npub.run_public_import(
        job, tables, mapping, OPTS, _hooks["shots"], known, seen,
        lambda items: _hooks["add"](uid, items), tidy.prints(rows),
        fill=_hooks["fill"](uid, rows))
    if job.state == "error":
        raise RuntimeError(job.error or "перенесення обірвалось")
    return job.added, job.filled


def sync_user(uid):
    """Усі бази однієї людини. Пише в conf, коли й чим закінчилось."""
    conf = _hooks["conf"](uid)
    src = [s for s in (conf.get("sources") or []) if s.get("url")]
    if not src:
        return None
    added = filled = 0
    trouble = ""
    for i, one in enumerate(src):
        if i:
            time.sleep(GAP)
        try:
            a, f = sync_source(uid, one)
            added += a
            filled += f
        except Exception as ex:
            trouble = str(ex)[:200]
            print("notion_sync:", uid, one.get("id"), ex)
    # conf перечитуємо: поки читали Notion, людина могла щось змінити
    conf = _hooks["conf"](uid)
    conf["auto"] = {"when": datetime.datetime.now(datetime.timezone.utc)
                            .replace(microsecond=0).isoformat(),
                    "added": added, "filled": filled, "error": trouble}
    _hooks["save"](uid, conf)
    return {"added": added, "filled": filled, "error": trouble}


def _users_with_notion():
    """Кому є що оновлювати — питаємо базу, а не перебираємо всіх."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT user_id FROM notion_conf "
            "WHERE jsonb_array_length(COALESCE(data->'sources','[]'::jsonb)) > 0 "
            "ORDER BY user_id").fetchall()
    return [r["user_id"] for r in rows]


def run_once():
    out = {}
    try:
        uids = _users_with_notion()
    except Exception as ex:
        print("notion_sync: не змогли прочитати список —", ex)
        return out
    for uid in uids:
        if _hooks["busy"](uid):
            continue                      # людина саме переносить руками
        try:
            got = sync_user(uid)
            if got and (got["added"] or got["filled"]):
                out[uid] = got
                print("notion_sync: %s — додано %d, дозаповнено %d"
                      % (uid, got["added"], got["filled"]))
        except Exception as ex:
            print("notion_sync:", uid, ex)
    return out


def loop():
    time.sleep(FIRST)
    while True:
        try:
            run_once()
        except Exception as ex:
            print("notion_sync loop:", ex)
        time.sleep(EVERY)


def start(add, fill, conf, save, shots, busy):
    """app.py віддає сюди свої руки: чим класти угоди, звідки брати
    налаштування і як дізнатись, що людина зараз переносить сама."""
    _hooks.update(add=add, fill=fill, conf=conf, save=save,
                  shots=shots, busy=busy)
    threading.Thread(target=loop, daemon=True, name="notion-sync").start()

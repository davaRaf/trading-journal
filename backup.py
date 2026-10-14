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
import codecs
import csv
import datetime
import io
import json
import re
import threading
import time

import db
import accounts_store
import bt_journals_store
import day_store
import week_store
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
        # kind="all" — вместе с бэктестом: часы работы над прогоном стоит
        # спасать наравне с реальными сделками, различить их можно по полю.
        "trades": db.list_trades(uid, "all"),
        # Картки журналів бектесту. Угоди підписані іменем прогону
        # (bt_run), а назва — це ще не все: в картці лежать актив, період
        # історії й нотатка. Без них зліпок рятував угоди й губив те,
        # заради чого прогін узагалі робили.
        "bt_journals": bt_journals_store.lst(uid),
        "days": day_store.notes_since(uid, "0001-01-01"),
        # розбори тижнів — така сама робота руками, як і денні
        "weeks": week_store.notes_since(uid, "0001-01-01"),
        "strategy": ts_store.get(uid),
        # ТС бектесту — окремий документ, і в зліпку теж окремо. seed=False:
        # зліпок тільки дивиться, копію заводить сама людина, коли заходить
        "strategy_bt": ts_store.get(uid, "bt", seed=False),
        # додаткові стратегії (strategy — перша з них)
        "strategies": [dict(s, data=ts_store.get(uid, seed=False, sid=s["id"]))
                       for s in ts_store.lst(uid) if s["id"]],
        # Рахунки: опис того, на чому людина торгувала. Самі гроші тут не
        # лежать — вони рахуються з угод, але без стартового балансу й
        # лімітів порахувати їх удруге не вийде.
        "accounts": accounts_store.lst(uid),
        "notion": _notion(uid),
    })


# ------------------------------------------------- вибірка і таблиця ----

# Один файл на весь журнал годиться, щоб нічого не втратити, але не
# годиться, щоб віддати комусь один прогін. Тому ті самі дані вміємо
# звузити — режимом і назвою прогону — і покласти не лише в JSON.

_SPACES = re.compile(r"[\s\u00a0\u202f\u2007]+")


def run_key(name):
    """Назва прогону до спільного вигляду. Так само, як у btj.js: зайві
    пробіли в один, краї геть, регістр не рахується. Інакше «US100 Март»
    із кнопки не знайде угод, підписаних «US100  март»."""
    return _SPACES.sub(" ", str(name if name is not None else "")).strip().lower()


def only(trades, kind="all", run=None):
    """Угоди, що лишаються після звуження.

    `kind`: "all" — усі, "bt" — лише бектест, "live" — лише справжня
    торгівля. `run` — назва журналу бектесту; порожній рядок означає
    «без журналу», і це не те саме, що None («не звужуємо»).
    """
    want = str(kind or "all")
    rk = None if run is None else run_key(run)
    out = []
    for t in trades or []:
        bt = str(t.get("kind") or "") == "bt"
        if want == "bt" and not bt:
            continue
        if want == "live" and bt:
            continue
        if rk is not None and run_key(t.get("bt_run")) != rk:
            continue
        out.append(t)
    return out


def narrow(snap, kind="all", run=None):
    """Зліпок під ту саму вибірку. Крім угод прибираємо й те, що до цього
    режиму не стосується: у вивантаженні бектесту нема чого робити ТС
    реальної торгівлі, і навпаки."""
    out = dict(snap)
    out["trades"] = only(snap.get("trades"), kind, run)
    out["only"] = {"kind": str(kind or "all"),
                   "run": None if run is None else str(run)}
    if str(kind or "all") == "bt":
        out.pop("strategy", None)
    elif str(kind or "all") == "live":
        out.pop("strategy_bt", None)
        out.pop("bt_journals", None)
    if run is not None:
        rk = run_key(run)
        out["bt_journals"] = [j for j in (snap.get("bt_journals") or [])
                              if run_key(j.get("name")) == rk]
    return out


# Порядок колонок у таблиці: спершу те, за чим угоду впізнають, потім
# числа, потім довгі тексти. Поля ті самі, що в JSON, — таблиця нічого
# свого не вигадує, лише розкладає рядком.
CSV_FIELDS = ["id", "kind", "bt_run", "date", "pair", "session", "position",
              "bias", "direction_type", "entry_model", "setup", "result",
              "rr", "rr_plan", "risk", "account", "ts",
              "entry_details", "notes", "mistakes", "comments", "emotion",
              "screenshots"]


def _cell(v):
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        return "; ".join(str(x) for x in v)
    if isinstance(v, bool):
        return "1" if v else ""
    return str(v)


def trades_csv(trades):
    """Таблиця угод. Коми між колонками — так її приймають і Notion, і
    Google Sheets; попереду BOM, інакше Excel відкриє кирилицю кракозябрами."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(CSV_FIELDS)
    for t in trades or []:
        w.writerow([_cell(t.get(f)) for f in CSV_FIELDS])
    return codecs.BOM_UTF8 + buf.getvalue().encode("utf-8")


_SLUG = re.compile(r"[^A-Za-z0-9]+")


def file_name(kind="all", run=None, ext="json", today=None):
    """Ім'я файла, яке людина впізнає через півроку. Назву прогону
    перекладаємо на латиницю-цифри: не-ASCII в заголовку відповіді
    довелось би окремо кодувати, а користі з того на ім'я файла немає."""
    day = (today or datetime.date.today()).isoformat()
    want = str(kind or "all")
    head = "backtest" if want == "bt" else ("journal" if want != "live" else "journal-live")
    if run is not None:
        slug = _SLUG.sub("-", str(run)).strip("-")
        head += "-" + (slug if slug else "run")
    return "%s-%s.%s" % (head, day, ext)


def _worth(snap):
    """Порожній журнал зберігати нема сенсу — лише сміття в таблиці."""
    return bool(snap.get("trades") or snap.get("days") or snap.get("weeks")
                or snap.get("strategy") or snap.get("accounts"))


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


def strategies(uid):
    """ТС з денних зліпків, новіші першими: дата і сама стратегія.
    Для адмінки — повернути людині її систему, якщо її затерло."""
    init()
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT made_on, data->'strategy' AS ts FROM backups WHERE user_id=%s "
            "ORDER BY made_on DESC", (uid,)).fetchall()
    return [(str(r["made_on"]), r["ts"]) for r in rows if r["ts"]]


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

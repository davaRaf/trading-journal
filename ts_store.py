# -*- coding: utf-8 -*-
"""
Торгова стратегія людини: правила, за якими вона входить у ринок.

Лежить окремою таблицею, по одному запису на користувача, і зберігається
цілим документом (JSON). Розбивати на колонки не стали: набір полів у
кожного свій — хтось описує чотири таймфрейми, хтось два, хтось додає
свої випадки для беззбитку. Плюс форма ще змінюватиметься.

Скріни до правил кладуться в ту саму теку, що й скріни угод, але з
іменем `ts<id користувача>_...`. Так власника видно з самого імені файлу,
і чужий скрін не віддасться, навіть якщо хтось вгадає назву.
"""
import base64
import os
import re
import time

from psycopg.types.json import Jsonb

import ts_ai

import db
import filestore

SCHEMA = """
CREATE TABLE IF NOT EXISTS strategies (
  user_id    BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  data       JSONB NOT NULL DEFAULT '{}'::jsonb,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Стратегій у людини дві: для реальної торгівлі і для бектесту. Другу
-- кладемо сусідньою колонкою, а не окремим рядком.
--
-- Спершу спробували рядок на кожен вид: user_id перестав бути унікальним,
-- первинний ключ довелось зняти — і код, який ще не виклали, зламався на
-- ON CONFLICT (user_id). Колонка так не робить: старий код бачить таблицю
-- рівно такою, як була, і працює далі.
--
-- NULL у data_bt — копію ще не знімали; '{}' — людина прибрала стратегію
-- бектесту сама, і копіювати вдруге не треба.
ALTER TABLE strategies ADD COLUMN IF NOT EXISTS data_bt JSONB;

DO $$
BEGIN
  -- прибираємо ту саму спробу з окремими рядками, якщо вона встигла лягти
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_name = 'strategies' AND column_name = 'kind') THEN
    INSERT INTO strategies (user_id, data, data_bt)
      SELECT b.user_id, '{}'::jsonb, b.data FROM strategies b
       WHERE b.kind = 'bt' AND NOT EXISTS (
             SELECT 1 FROM strategies s WHERE s.user_id = b.user_id AND s.kind = '');
    UPDATE strategies s SET data_bt = b.data FROM strategies b
     WHERE b.user_id = s.user_id AND b.kind = 'bt' AND s.kind = ''
       AND s.data_bt IS NULL;
    DELETE FROM strategies WHERE kind = 'bt';
    DROP INDEX IF EXISTS strategies_user_kind;
    ALTER TABLE strategies DROP COLUMN kind;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                  WHERE conrelid = 'strategies'::regclass AND contype = 'p') THEN
    ALTER TABLE strategies ADD CONSTRAINT strategies_pkey PRIMARY KEY (user_id);
  END IF;
END $$;
"""

# Кілька стратегій (власник, 05.10.2026). Перша — та сама, що й була
# (strategies.data, sid 0), щоб нічого зі старого коду не ламалось; решта
# лежать окремими рядками тут. Угода знає свою стратегію полем trades.ts
# ("" — перша).
MULTI = """
ALTER TABLE strategies ADD COLUMN IF NOT EXISTS name TEXT NOT NULL DEFAULT '';
CREATE TABLE IF NOT EXISTS ts_multi (
  id         BIGSERIAL PRIMARY KEY,
  user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name       TEXT NOT NULL DEFAULT '',
  data       JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ts_multi_user ON ts_multi (user_id, id);
"""
MAX_TS = 10            # стратегій на людину; більше — уже не система, а каша

_ready = False


def init():
    """Таблиця створюється при першому зверненні: так модуль не залежить
    від того, чи згадали про нього в db.init()."""
    global _ready
    if _ready:
        return
    with db.connect() as conn:
        conn.execute(SCHEMA)
        conn.execute(MULTI)
    _ready = True


def _sid(sid):
    try:
        return max(0, int(sid or 0))
    except (TypeError, ValueError):
        return 0


def lst(user_id):
    """Усі стратегії людини: перша (id 0) і додані. Назва може бути
    порожньою — тоді сторінка підпише «ТС 1», «ТС 2»…"""
    init()
    with db.connect() as conn:
        row = conn.execute("SELECT name, data FROM strategies WHERE user_id=%s",
                           (user_id,)).fetchone()
        rows = conn.execute("SELECT id, name, data FROM ts_multi WHERE user_id=%s ORDER BY id",
                            (user_id,)).fetchall()
    out = [{"id": 0, "name": (row or {}).get("name") or "", "has": bool(row and row["data"])}]
    out += [{"id": r["id"], "name": r["name"], "has": bool(r["data"])} for r in rows]
    return out


def create(user_id, name="", copy_from=None):
    """Нова стратегія: порожня або копія вже наявної (copy_from — її sid)."""
    init()
    data = {}
    if copy_from is not None:
        data = get(user_id, "", seed=False, sid=copy_from) or {}
    with db.connect() as conn:
        n = conn.execute("SELECT count(*) AS n FROM ts_multi WHERE user_id=%s",
                         (user_id,)).fetchone()["n"]
        if n + 1 >= MAX_TS:
            return None
        row = conn.execute("INSERT INTO ts_multi (user_id, name, data) VALUES (%s,%s,%s) "
                           "RETURNING id", (user_id, str(name or "").strip()[:60], Jsonb(data))).fetchone()
    return row["id"]


def rename(user_id, sid, name):
    init()
    sid, name = _sid(sid), str(name or "").strip()[:60]
    with db.connect() as conn:
        if sid:
            conn.execute("UPDATE ts_multi SET name=%s WHERE id=%s AND user_id=%s",
                         (name, sid, user_id))
        else:
            conn.execute("INSERT INTO strategies (user_id, name) VALUES (%s,%s) "
                         "ON CONFLICT (user_id) DO UPDATE SET name=EXCLUDED.name",
                         (user_id, name))


def drop(user_id, sid):
    """Прибрати додану стратегію. Першу не прибираємо — її можна лише
    очистити. Угоди стратегії переходять у першу: журнал не губимо."""
    init()
    sid = _sid(sid)
    if not sid:
        return False
    with db.connect() as conn:
        got = conn.execute("DELETE FROM ts_multi WHERE id=%s AND user_id=%s RETURNING id",
                           (sid, user_id)).fetchone()
        if got:
            conn.execute("UPDATE trades SET ts='' WHERE user_id=%s AND ts=%s",
                         (user_id, str(sid)))
    return bool(got)


def _kind(kind):
    return "bt" if kind == "bt" else ""


def _row(conn, user_id):
    return conn.execute("SELECT data, data_bt FROM strategies WHERE user_id=%s",
                        (user_id,)).fetchone()


def get(user_id, kind="", seed=True, sid=0):
    """Стратегія того журналу, в якому людина зараз.

    Перший захід у бектест знімає копію з реальної ТС: людина не описує
    свою систему двічі. Далі це вже два окремі документи — правки в
    бектесті не течуть у справжню торгівлю, і навпаки.

    Прибрана стратегія бектесту лишається прибраною: у колонці стоїть
    порожній документ, і копію вдруге ми вже не знімаємо.

    `seed=False` — тільки прочитати, копію не робити. Так дивиться щоденний
    зліпок для бекапу: він ходить по всіх людях підряд, і заводити їм копію
    бектесту, якого вони не відкривали, ні до чого.
    """
    init()
    sid = _sid(sid)
    if sid and _kind(kind) != "bt":
        with db.connect() as conn:
            r = conn.execute("SELECT data FROM ts_multi WHERE id=%s AND user_id=%s",
                             (sid, user_id)).fetchone()
        return ts_ai.route_saved((r or {}).get("data") or None)
    with db.connect() as conn:
        row = _row(conn, user_id)
        if row is None:
            return None
        if _kind(kind) != "bt":
            return ts_ai.route_saved(row["data"] or None)
        if row["data_bt"] is not None or not seed:
            return ts_ai.route_saved(row["data_bt"] or None)
        src = row["data"] or None
        if not src:
            return None                     # копіювати нема чого
        conn.execute("UPDATE strategies SET data_bt=%s WHERE user_id=%s "
                     "AND data_bt IS NULL", (Jsonb(src), user_id))
        return ts_ai.route_saved(src)


def put(user_id, data, kind="", sid=0):
    init()
    sid = _sid(sid)
    if sid and _kind(kind) != "bt":
        with db.connect() as conn:
            conn.execute("UPDATE ts_multi SET data=%s, updated_at=now() WHERE id=%s AND user_id=%s",
                         (Jsonb(data or {}), sid, user_id))
        return
    col = "data_bt" if _kind(kind) == "bt" else "data"
    with db.connect() as conn:
        # у рядка обидві колонки: у сусідньої лишається те, що в ній було
        conn.execute(
            "INSERT INTO strategies (user_id, %s) VALUES (%%s, %%s) "
            "ON CONFLICT (user_id) DO UPDATE SET %s=EXCLUDED.%s, updated_at=now()"
            % (col, col, col),
            (user_id, Jsonb(data or {})))


def clear(user_id, kind="", sid=0):
    """Прибирає стратегію одного журналу. Сусідню не чіпає."""
    init()
    sid = _sid(sid)
    if sid and _kind(kind) != "bt":
        put(user_id, {}, "", sid)
        return
    with db.connect() as conn:
        if _kind(kind) == "bt":
            # порожній документ, а не NULL: прибрана стратегія має лишитись
            # прибраною, інакше наступний захід знову притяг би копію
            conn.execute("UPDATE strategies SET data_bt=%s, updated_at=now() "
                         "WHERE user_id=%s", (Jsonb({}), user_id))
            return
        # рядок тримає й бектест — тоді просто спорожняємо реальну частину
        conn.execute("UPDATE strategies SET data=%s, updated_at=now() "
                     "WHERE user_id=%s AND data_bt IS NOT NULL", (Jsonb({}), user_id))
        conn.execute("DELETE FROM strategies WHERE user_id=%s AND data_bt IS NULL",
                     (user_id,))


# ----------------------------------------------------------- скріни ----

DATAURL_RE = re.compile(r"^data:image/(png|jpeg|jpg|webp|gif);base64,(.+)$", re.S)
NAME_RE = re.compile(r"^ts(\d+)_[0-9a-z]+\.(png|jpg|jpeg|webp|gif)$", re.I)
MAX_BYTES = 6 * 1024 * 1024


def save_shot(user_id, data_url, shots_dir):
    """Кладе картинку з data-URL у файл і повертає його ім'я."""
    m = DATAURL_RE.match(data_url or "")
    if not m:
        raise ValueError("не картинка")
    try:
        raw = base64.b64decode(m.group(2))
    except Exception:
        raise ValueError("зіпсований файл")
    if len(raw) > MAX_BYTES:
        raise filestore.ShotError("завеликий файл", "too_big", 413)
    # Розширення беремо з байтів, а не зі слова в data-URL: його пише клієнт.
    ext = filestore.kind(raw)
    if not ext:
        raise filestore.ShotError("не картинка", "bad_image")
    name = "ts%d_%x.%s" % (int(user_id), int(time.time() * 1000), ext)
    # у базі — надовго, на диску — кешем: у контейнерів файлова система
    # тимчасова, і після оновлення коду картинки зникли б
    try:
        filestore.put(name, raw)
    except Exception:
        pass
    try:
        with open(os.path.join(shots_dir, name), "wb") as f:
            f.write(raw)
    except OSError:
        pass
    return name


def owns_shot(user_id, name):
    m = NAME_RE.match(name or "")
    return bool(m) and m.group(1) == str(user_id)


def copy_for(user_id, data):
    """Чужа ТС як своя: та сама структура, але кожен скрін — нова копія з
    іменем нового власника (ts<його id>_…). Інакше картинки лишились би
    чужими: їх не віддасть перевірка власника і прибере sweep автора."""
    n = [0]

    def dup(name):
        got = filestore.get(os.path.basename(name)) if name else None
        if not got:
            return ""
        mime, blob = got
        ext = name.rsplit(".", 1)[-1].lower()
        n[0] += 1
        new = "ts%d_%x%02d.%s" % (int(user_id), int(time.time() * 1000), n[0] % 100, ext)
        filestore.put(new, bytes(blob), mime)
        return new

    def walk(x):
        if isinstance(x, dict):
            out = {}
            for k, v in x.items():
                if k in ("shot", "file") and isinstance(v, str):
                    out[k] = dup(v)
                elif k == "shots" and isinstance(v, list):
                    out[k] = [s for s in (dup(i) if isinstance(i, str) else walk(i) for i in v) if s]
                else:
                    out[k] = walk(v)
            return out
        if isinstance(x, list):
            return [walk(v) for v in x]
        return x

    return walk(data or {})


def copy_for(user_id, data):
    """Чужа ТС як своя: та сама структура, але кожен скрін — нова копія з
    іменем нового власника (ts<його id>_…). Інакше картинки лишились би
    чужими: їх не віддасть перевірка власника і прибере sweep автора."""
    n = [0]

    def dup(name):
        got = filestore.get(os.path.basename(name)) if name else None
        if not got:
            return ""
        mime, blob = got
        ext = name.rsplit(".", 1)[-1].lower()
        n[0] += 1
        new = "ts%d_%x%02d.%s" % (int(user_id), int(time.time() * 1000), n[0] % 100, ext)
        filestore.put(new, bytes(blob), mime)
        return new

    def walk(x):
        if isinstance(x, dict):
            out = {}
            for k, v in x.items():
                if k in ("shot", "file") and isinstance(v, str):
                    out[k] = dup(v)
                elif k == "shots" and isinstance(v, list):
                    out[k] = [s for s in (dup(i) if isinstance(i, str) else walk(i) for i in v) if s]
                else:
                    out[k] = walk(v)
            return out
        if isinstance(x, list):
            return [walk(v) for v in x]
        return x

    return walk(data or {})


def used_files(data):
    """Усі імена файлів, на які посилається стратегія."""
    out = set()

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k in ("shot", "file") and isinstance(v, str) and v:
                    out.add(v)
                elif k == "shots" and isinstance(v, list):
                    # список імен файлів: скріни супроводу і приклади до моделей
                    for it in v:
                        if isinstance(it, str):
                            if it:
                                out.add(it)
                        else:
                            walk(it)
                else:
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(data or {})
    return out


def sweep(user_id, data, shots_dir, kind="", sid=0):
    """Прибирає файли, на які стратегія більше не посилається.

    Людина може перекласти скрін тричі — старі копії інакше лишаться
    лежати назавжди.

    Стратегій у людини дві, а тека скрінів спільна, і копія для бектесту
    посилається на ті самі файли. Тому лишаємо й те, чим користується
    сусідній журнал: інакше прибирання в одному забрало б картинки з іншого.
    """
    init()
    kind, sid = _kind(kind), _sid(sid)
    if kind == "bt":
        sid = 0
    try:
        with db.connect() as conn:
            row = _row(conn, user_id) or {}
            extra = conn.execute("SELECT id, data FROM ts_multi WHERE user_id=%s",
                                 (user_id,)).fetchall()
    except Exception:
        # не змогли спитати базу — краще нічого не чіпати, ніж стерти чуже
        return
    # лишаємо все, чим користуються інші стратегії: скріни в копії ТС —
    # ті самі файли, що й в оригіналі
    others = [r["data"] for r in extra if r["id"] != sid]
    if sid or kind == "bt":
        others.append(row.get("data"))
    if sid or kind != "bt":
        others.append(row.get("data_bt"))
    keep = used_files(data)
    for doc in others:
        keep |= used_files(doc or None)
    pref = "ts%d_" % int(user_id)
    try:
        names = os.listdir(shots_dir)
    except OSError:
        names = []
    gone = [n for n in names if n.startswith(pref) and n not in keep]
    for n in gone:
        try:
            os.remove(os.path.join(shots_dir, n))
        except OSError:
            pass
    try:
        filestore.delete(gone)
    except Exception:
        pass

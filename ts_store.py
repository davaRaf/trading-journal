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

_ready = False


def init():
    """Таблиця створюється при першому зверненні: так модуль не залежить
    від того, чи згадали про нього в db.init()."""
    global _ready
    if _ready:
        return
    with db.connect() as conn:
        conn.execute(SCHEMA)
    _ready = True


def _kind(kind):
    return "bt" if kind == "bt" else ""


def _row(conn, user_id):
    return conn.execute("SELECT data, data_bt FROM strategies WHERE user_id=%s",
                        (user_id,)).fetchone()


def get(user_id, kind="", seed=True):
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
    with db.connect() as conn:
        row = _row(conn, user_id)
        if row is None:
            return None
        if _kind(kind) != "bt":
            return row["data"] or None
        if row["data_bt"] is not None or not seed:
            return row["data_bt"] or None
        src = row["data"] or None
        if not src:
            return None                     # копіювати нема чого
        conn.execute("UPDATE strategies SET data_bt=%s WHERE user_id=%s "
                     "AND data_bt IS NULL", (Jsonb(src), user_id))
        return src


def put(user_id, data, kind=""):
    init()
    col = "data_bt" if _kind(kind) == "bt" else "data"
    with db.connect() as conn:
        # у рядка обидві колонки: у сусідньої лишається те, що в ній було
        conn.execute(
            "INSERT INTO strategies (user_id, %s) VALUES (%%s, %%s) "
            "ON CONFLICT (user_id) DO UPDATE SET %s=EXCLUDED.%s, updated_at=now()"
            % (col, col, col),
            (user_id, Jsonb(data or {})))


def clear(user_id, kind=""):
    """Прибирає стратегію одного журналу. Сусідню не чіпає."""
    init()
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
        raise ValueError("завеликий файл")
    ext = m.group(1).lower().replace("jpeg", "jpg")
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


def sweep(user_id, data, shots_dir, kind=""):
    """Прибирає файли, на які стратегія більше не посилається.

    Людина може перекласти скрін тричі — старі копії інакше лишаться
    лежати назавжди.

    Стратегій у людини дві, а тека скрінів спільна, і копія для бектесту
    посилається на ті самі файли. Тому лишаємо й те, чим користується
    сусідній журнал: інакше прибирання в одному забрало б картинки з іншого.
    """
    init()
    kind = _kind(kind)
    try:
        with db.connect() as conn:
            row = _row(conn, user_id) or {}
        other = (row.get("data") if kind == "bt" else row.get("data_bt")) or None
    except Exception:
        # не змогли спитати базу — краще нічого не чіпати, ніж стерти чуже
        return
    keep = used_files(data) | used_files(other)
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

# -*- coding: utf-8 -*-
"""
Запис угоди в боті: покроковий сценарій із кнопками.

Людина тисне «Записати угоду» — і далі бот веде по полях: пара, дата,
сесія, напрямок, біас, сетап, модель входу, рахунок, результат, RR,
ризик, скрін, емоція. Наприкінці показує картку й записує тільки після
підтвердження: моделі тут немає взагалі, а отже й нема чому вигадувати
за людину.

Чому кнопками, а не вільним текстом: майже всі поля — це кілька значень,
якими людина користується щодня. Натиснути «Лондон» швидше, ніж написати,
і в журнал не потрапляє чергове написання того самого («лондон», «Лонд.»),
через яке аналітика розсипається на синоніми. Варіанти беремо з її ж
журналу, від найчастішого (db.frequent_values).

Чернетка лежить у базі (db.trade_drafts), а не в пам'яті процесу: виклад
коду перезапускає бота, і недописана угода інакше зникала б разом з ним.
"""
import datetime
import random
import time
from zoneinfo import ZoneInfo

import db
import emotions
import filestore
import tg_api
from config import SITE_URL

KYIV = ZoneInfo("Europe/Kyiv")

# Напис на постійній кнопці біля поля вводу. Він же приходить звичайним
# повідомленням, коли її тиснуть, — тому лежить тут, а не в bot.py.
BUTTON = "➕ Записати угоду"
REPLY_KB = [[{"text": BUTTON}]]

# Скільки варіантів показуємо кнопками. Більше — і клавіатура займає
# півекрана, а хвіст усе одно ніхто не читає: своє значення швидше
# написати текстом.
TOP = 6

# Результати — рівно ті, що в формі на сайті (static/app.js). Підписи
# людські, у базу лягає код.
RESULTS = [("Win", "TP"), ("WinM", "Рукою"), ("Loss", "SL"),
           ("BE-", "BE−"), ("BE+", "BE+"), ("Skip", "Скіп")]

# RR має сенс лише там, де угода щось принесла. За стопом рахується сам
# ризик (див. netR у static/app.js), тому питати там нічого.
RR_RESULTS = {"Win", "WinM", "BE+"}


def _new_id():
    """Свій номер угоди. Формат такий самий, як у сайту (app.py new_id) —
    літера й число, — але довший на три цифри: сайт і бот живуть в одному
    процесі й нумерують незалежно, а збігтися вони не мають."""
    return "t%d%03d" % (int(time.time() * 1000), random.randint(0, 999))


# ------------------------------------------------------------------ кроки ----
# kind визначає, як питаємо й що приймаємо:
#   choice — кнопки з журналу плюс своє значення текстом;
#   fixed  — закритий список (напрямок, результат);
#   date   — сьогодні/вчора або дата текстом;
#   number — число текстом, з підказкою «як минулого разу»;
#   photo  — чекаємо картинку;
#   emotion — кнопки з emotions.py.
STEPS = [
    {"key": "pair",        "field": "pair",        "kind": "choice", "q": "Яка пара?"},
    {"key": "date",        "field": "date",        "kind": "date",   "q": "Коли це було?"},
    {"key": "session",     "field": "session",     "kind": "choice", "q": "Яка сесія?",
     "skip": True},
    {"key": "position",    "field": "position",    "kind": "fixed",  "q": "Напрямок?",
     "options": [("Long", "Long"), ("Short", "Short")]},
    {"key": "bias",        "field": "bias",        "kind": "choice", "q": "Який біас?",
     "skip": True},
    {"key": "setup",       "field": "setup",       "kind": "choice", "q": "Сетап?",
     "skip": True},
    {"key": "entry_model", "field": "entry_model", "kind": "choice", "q": "Модель входу?",
     "skip": True},
    {"key": "account",     "field": "account",     "kind": "choice", "q": "Який рахунок?",
     "skip": True},
    {"key": "result",      "field": "result",      "kind": "fixed",  "q": "Чим закінчилась?",
     "options": RESULTS},
    {"key": "rr",          "field": "rr",          "kind": "number", "q": "Скільки RR?",
     "skip": True, "only_if_result": RR_RESULTS},
    {"key": "risk",        "field": "risk",        "kind": "number", "q": "Який ризик, %?",
     "skip": True},
    {"key": "shot",        "field": None,          "kind": "photo",  "skip": True,
     "q": "Надішли скрін угоди — картинкою в чат."},
    {"key": "emotion",     "field": "emotion",     "kind": "emotion", "skip": True,
     "q": "Яка емоція була під час угоди?"},
]
BY_KEY = {s["key"]: s for s in STEPS}
ORDER = [s["key"] for s in STEPS]
CONFIRM = "confirm"           # окремий «крок»: картка з підтвердженням


def _step_fits(step, trade):
    """Чи питати цей крок узагалі. RR за стопом не питаємо: він там ні на
    що не впливає, а зайве питання посеред сценарію дратує."""
    need = step.get("only_if_result")
    return not need or (trade.get("result") in need)


def _next_key(key, trade):
    i = ORDER.index(key) + 1 if key in ORDER else 0
    while i < len(ORDER):
        if _step_fits(BY_KEY[ORDER[i]], trade):
            return ORDER[i]
        i += 1
    return CONFIRM


def _prev_key(key, trade):
    if key == CONFIRM:
        i = len(ORDER) - 1
    else:
        i = ORDER.index(key) - 1
    while i >= 0:
        if _step_fits(BY_KEY[ORDER[i]], trade):
            return ORDER[i]
        i -= 1
    return None


# --------------------------------------------------------------- клавіатури ----

def _options(user_id, step, trade):
    """Що показати кнопками на цьому кроці."""
    kind = step["kind"]
    if kind == "fixed":
        return [label for _v, label in step["options"]], [v for v, _l in step["options"]]
    if kind == "date":
        today = datetime.datetime.now(KYIV).date()
        vals = [today.isoformat(), (today - datetime.timedelta(days=1)).isoformat()]
        return ["Сьогодні", "Вчора"], vals
    if kind == "number":
        last = db.last_number(user_id, step["field"])
        if last is None:
            return [], []
        return ["Як минулого разу (%s)" % _num(last)], [str(last)]
    if kind == "emotion":
        return [l for _c, l in emotions.OPTIONS], [l for _c, l in emotions.OPTIONS]
    vals = db.frequent_values(user_id, step["field"], TOP)
    return list(vals), list(vals)


def _keyboard(step, labels, skip_ok, first):
    """Кнопки значень по дві в ряд, унизу — навігація.

    У callback_data кладемо номер варіанта, а не сам текст: у Телеграма
    на неї 64 байти, а назви сетапів у людей бувають довгі. Поруч —
    назва кроку: старі повідомлення з чату нікуди не діваються, і без неї
    натиснута кнопка попереднього питання рахувалась би відповіддю на
    поточне — з чужого списку й чужим номером.
    """
    key = step["key"]
    rows, row = [], []
    for i, label in enumerate(labels):
        row.append({"text": label, "callback_data": "tw:v:%s:%d" % (key, i)})
        if len(row) == 2:
            rows.append(row); row = []
    if row:
        rows.append(row)
    rows.append(nav_row(key, back=not first, skip=skip_ok))
    return rows


def nav_row(key, back=True, skip=False):
    nav = []
    if back:
        nav.append({"text": "← Назад", "callback_data": "tw:b:%s" % key})
    if skip:
        nav.append({"text": "Пропустити", "callback_data": "tw:s:%s" % key})
    nav.append({"text": "✕ Скасувати", "callback_data": "tw:x"})
    return nav


def _num(v):
    """Числа показуємо без хвоста .0 — «1» замість «1.0»."""
    if v is None:
        return ""
    f = float(v)
    return str(int(f)) if f == int(f) else ("%g" % f)


# ------------------------------------------------------------------ картка ----

SHOW = [("pair", "Пара"), ("date", "Дата"), ("session", "Сесія"), ("position", "Напрямок"),
        ("bias", "Біас"), ("setup", "Сетап"), ("entry_model", "Модель входу"),
        ("account", "Рахунок"), ("result", "Результат"), ("rr", "RR"),
        ("risk", "Ризик, %"), ("emotion", "Емоція")]
RES_LABEL = dict(RESULTS)


def card(trade):
    lines = []
    for key, title in SHOW:
        v = trade.get(key)
        if v in (None, ""):
            continue
        if key == "result":
            v = RES_LABEL.get(v, v)
        elif key in ("rr", "risk"):
            v = _num(v)
        lines.append("%s: %s" % (title, v))
    shots = len(trade.get("screenshots") or [])
    if shots:
        lines.append("Скрін: %d" % shots)
    return "\n".join(lines) or "Поки що порожньо."


def _confirm_kb():
    return [[{"text": "✅ Записати", "callback_data": "tw:ok"}],
            nav_row(CONFIRM)]


# ------------------------------------------------------------------- показ ----

def _ask(user_id, chat_id, draft):
    """Питання поточного кроку. Стан чернетки зберігаємо тут же, разом зі
    списком варіантів: кнопка повертає номер, і без списку його нічим
    розшифрувати після перезапуску бота."""
    key = draft["step"]
    trade = draft["data"].get("trade") or {}
    if key == CONFIRM:
        db.draft_save(user_id, chat_id, key, draft["data"])
        tg_api.send_message(chat_id, "Ось що вийшло:\n\n" + card(trade)
                            + "\n\nЗаписати в журнал?", keyboard=_confirm_kb())
        return
    step = BY_KEY[key]
    labels, values = _options(user_id, step, trade)
    draft["data"]["opts"] = values
    db.draft_save(user_id, chat_id, key, draft["data"])
    hint = ""
    if step["kind"] == "choice":
        hint = "\nМожна написати своє."
    elif step["kind"] == "number":
        hint = "\nНапиши числом."
    elif step["kind"] == "date":
        hint = "\nАбо напиши дату: 2026-09-05."
    elif step["kind"] == "emotion":
        hint = "\nАбо опиши своїми словами."
    first = _prev_key(key, trade) is None
    tg_api.send_message(chat_id, step["q"] + hint,
                        keyboard=_keyboard(step, labels, step.get("skip"), first))


# ------------------------------------------------------------------ початок ----

def start(user, chat_id):
    """Нова чернетка. Стару мовчки замінюємо: якщо людина натиснула
    «Записати угоду» посеред попередньої, вона саме цього й хоче."""
    trade = {"id": _new_id(), "screenshots": []}
    draft = {"chat_id": chat_id, "step": ORDER[0], "data": {"trade": trade}}
    _ask(user["id"], chat_id, draft)


def active(user_id):
    return db.draft_get(user_id) is not None


# ------------------------------------------------------------------ відповіді ----

def _set(user_id, chat_id, draft, value):
    """Записати відповідь у поле й перейти далі."""
    key = draft["step"]
    step = BY_KEY[key]
    trade = draft["data"].setdefault("trade", {})
    field = step["field"]
    if field and value is not None:
        if step["kind"] == "number":
            trade[field] = value            # уже число
        else:
            trade[field] = value
    draft["step"] = _next_key(key, trade)
    _ask(user_id, chat_id, draft)


def on_text(user, chat_id, text):
    """Текст під час сценарію. Повертає True, якщо повідомлення наше."""
    draft = db.draft_get(user["id"])
    if not draft:
        return False
    key = draft["step"]
    if key == CONFIRM:
        tg_api.send_message(chat_id, "Натисни «Записати» або «Скасувати» під карткою.")
        return True
    step = BY_KEY[key]
    raw = (text or "").strip()
    if step["kind"] == "photo":
        # На кроці зі скріном текст — це майже завжди «нема» чи «пізніше».
        _set(user["id"], chat_id, draft, None)
        return True
    if step["kind"] == "number":
        try:
            value = float(raw.replace(",", ".").replace("%", "").strip())
        except ValueError:
            tg_api.send_message(chat_id, "Це не схоже на число. Напиши, наприклад, 1.5")
            return True
        _set(user["id"], chat_id, draft, value)
        return True
    if step["kind"] == "date":
        day = _parse_date(raw)
        if not day:
            tg_api.send_message(chat_id, "Не зрозумів дату. Напиши так: 2026-09-05")
            return True
        _set(user["id"], chat_id, draft, day)
        return True
    if step["kind"] == "fixed":
        # Закритий список: приймаємо тільки те, що є серед кнопок, інакше
        # в журнал поїде «лонк» і зламає розріз по напрямку.
        for value, label in step["options"]:
            if raw.lower() in (value.lower(), label.lower()):
                _set(user["id"], chat_id, draft, value)
                return True
        tg_api.send_message(chat_id, "Обери кнопкою, будь ласка.")
        return True
    if step["kind"] == "emotion":
        # Свої слова зводимо до категорії — так само, як після угоди з сайту.
        label = emotions.classify(raw[:200]) or raw[:200]
        _set(user["id"], chat_id, draft, label)
        return True
    _set(user["id"], chat_id, draft, raw[:200])
    return True


def _parse_date(raw):
    t = raw.lower().strip()
    today = datetime.datetime.now(KYIV).date()
    if t in ("сьогодні", "сегодня", "today"):
        return today.isoformat()
    if t in ("вчора", "вчера", "yesterday"):
        return (today - datetime.timedelta(days=1)).isoformat()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y", "%d/%m/%Y"):
        try:
            return datetime.datetime.strptime(raw.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def on_photo(user, chat_id, photos):
    """Скрін до угоди. Кладемо в те саме сховище, що й картинки з сайту
    (filestore), тому в журналі він відкриється звичайним чином."""
    draft = db.draft_get(user["id"])
    if not draft:
        return False
    trade = draft["data"].setdefault("trade", {})
    # Телеграм присилає кілька розмірів одного фото — беремо найбільший.
    best = max(photos, key=lambda p: p.get("file_size") or 0)
    try:
        path = tg_api.get_file(best["file_id"])["file_path"]
        raw = tg_api.download(path)
    except Exception as ex:
        print("скрін не забрався:", ex)
        tg_api.send_message(chat_id, "Не вдалось забрати картинку. Спробуй ще раз.")
        return True
    ext = (path.rsplit(".", 1)[-1] or "jpg").lower()
    if ext not in ("jpg", "jpeg", "png", "webp"):
        ext = "jpg"
    name = "%s_%d.%s" % (trade.get("id") or _new_id(), int(time.time() * 1000) % 100000000, ext)
    filestore.put(name, raw)
    trade.setdefault("screenshots", []).append({"tf": "", "file": name})
    # Кілька скрінів підряд — звичайна річ (сетап, вхід, вихід), тому крок
    # не закриваємо: людина йде далі кнопкою.
    if draft["step"] == "shot":
        db.draft_save(user["id"], chat_id, draft["step"], draft["data"])
        tg_api.send_message(
            chat_id, "Скрін прийняв (%d). Можна ще один або далі."
            % len(trade["screenshots"]),
            keyboard=[[{"text": "Далі →", "callback_data": "tw:s:shot"}],
                      nav_row("shot")])
    else:
        db.draft_save(user["id"], chat_id, draft["step"], draft["data"])
        tg_api.send_message(chat_id, "Скрін прийняв — додам до цієї угоди.")
    return True


# ------------------------------------------------------------------ кнопки ----

def on_callback(cq, user):
    """Натиснута кнопка сценарію. Повертає True, якщо вона наша."""
    data = cq.get("data") or ""
    if not data.startswith("tw:"):
        return False
    chat_id = cq["message"]["chat"]["id"]
    draft = db.draft_get(user["id"])
    if not draft:
        tg_api.answer_callback(cq["id"], "Ця угода вже закрита")
        return True
    parts = data.split(":")
    action = parts[1]
    from_step = parts[2] if len(parts) > 2 and not parts[2].isdigit() else None
    trade = draft["data"].setdefault("trade", {})

    # Кнопка з чужого кроку — тобто зі старого повідомлення, до якого людина
    # прокрутила чат. Відповідати на неї не можна: варіанти в чернетці вже
    # інші, і номер кнопки вказав би на чуже значення. Просто нагадуємо, де
    # ми зараз, і повторюємо поточне питання.
    if from_step and from_step != draft["step"] and action in ("v", "s", "b"):
        tg_api.answer_callback(cq["id"], "Це кнопка з попереднього кроку")
        _ask(user["id"], chat_id, draft)
        return True

    if action == "x":
        db.draft_clear(user["id"])
        tg_api.answer_callback(cq["id"])
        tg_api.send_message(chat_id, "Скасував. Нічого не записав.")
        return True

    if action == "b":
        prev = _prev_key(draft["step"], trade)
        if prev is None:
            tg_api.answer_callback(cq["id"], "Це перший крок")
            return True
        # Значення кроку, на який повертаємось, забуваємо — інакше воно
        # мовчки лишилося б старим, хоч людина прийшла його змінити.
        field = BY_KEY[prev]["field"]
        if field:
            trade.pop(field, None)
        draft["step"] = prev
        tg_api.answer_callback(cq["id"])
        _ask(user["id"], chat_id, draft)
        return True

    if action == "s":
        tg_api.answer_callback(cq["id"])
        _set(user["id"], chat_id, draft, None)
        return True

    if action == "ok":
        tg_api.answer_callback(cq["id"])
        _save(user, chat_id, draft)
        return True

    if action == "v":
        try:
            idx = int(parts[-1])
            value = (draft["data"].get("opts") or [])[idx]
        except (IndexError, ValueError):
            # Список варіантів не збігся з кнопкою — питаємо ще раз замість
            # того, щоб мовчки записати не те.
            tg_api.answer_callback(cq["id"], "Кнопка застаріла")
            _ask(user["id"], chat_id, draft)
            return True
        step = BY_KEY.get(draft["step"])
        if step and step["kind"] == "number":
            try:
                value = float(value)
            except ValueError:
                value = None
        tg_api.answer_callback(cq["id"])
        _set(user["id"], chat_id, draft, value)
        return True

    tg_api.answer_callback(cq["id"])
    return True


# ------------------------------------------------------------------- запис ----

def _save(user, chat_id, draft):
    trade = draft["data"].get("trade") or {}
    if not (trade.get("pair") or "").strip():
        tg_api.send_message(chat_id, "Без пари не запишу — почни спочатку кнопкою.")
        db.draft_clear(user["id"])
        return
    t = {"id": trade.get("id") or _new_id()}
    for f in db.TEXT_FIELDS:
        t[f] = trade.get(f) or ""
    for f in db.NUM_FIELDS:
        v = trade.get(f)
        t[f] = float(v) if isinstance(v, (int, float)) else None
    t["screenshots"] = trade.get("screenshots") or []
    # Емоцію в сценарії вже питали, тому вдогонку її не питаємо: статус
    # «na» саме про це — «питання не стоїть».
    db.insert_trade(user["id"], t, "na")
    db.draft_clear(user["id"])
    # Клавіатуру повертаємо разом із відповіддю: наступну угоду записують
    # тією ж кнопкою, і шукати її після розмови не доводиться.
    tg_api.send_message(chat_id, "Записав у журнал ✍️\n\n" + card(t)
                        + "\n\nПодивитись: " + SITE_URL,
                        reply_kb=REPLY_KB)

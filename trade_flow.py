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

Питання й кнопки — мовою людини (botlang), а значення полів у журнал
лягають як є: перекладати те, що потім піде в розріз статистики, не можна.

Чернетка лежить у базі (db.trade_drafts), а не в пам'яті процесу: виклад
коду перезапускає бота, і недописана угода інакше зникала б разом з ним.
"""
import datetime
import random
import time
from zoneinfo import ZoneInfo

import botlang
import db
import emotions
import filestore
import tg_api
from botlang import t
from config import SITE_URL

KYIV = ZoneInfo("Europe/Kyiv")

# Скільки варіантів показуємо кнопками. Більше — і клавіатура займає
# півекрана, а хвіст усе одно ніхто не читає: своє значення швидше
# написати текстом.
TOP = 6

# Результати — рівно ті, що в формі на сайті (static/app.js). У журнал іде
# код, людина бачить підпис: TP/SL/BE зрозумілі всім, а «рукою» і «скіп»
# перекладаємо.
RESULTS = [("Win", "TP"), ("WinM", "resHand"), ("Loss", "SL"),
           ("BE-", "BE−"), ("BE+", "BE+"), ("Skip", "resSkip")]

# RR має сенс лише там, де угода щось принесла. За стопом рахується сам
# ризик (див. netR у static/app.js), тому питати там нічого.
RR_RESULTS = {"Win", "WinM", "BE+"}


def button(lang=botlang.DEFAULT):
    return t(lang, "btnTrade")


def reply_kb(lang=botlang.DEFAULT):
    """Постійна клавіатура біля поля вводу — одна кнопка запису."""
    return [[{"text": button(lang)}]]


def is_button(text):
    """Чи це натиснута постійна кнопка. Порівнюємо з усіма мовами: людина
    могла отримати клавіатуру українською, а потім перейти на російську —
    кнопка в неї на екрані лишиться стара."""
    return text in {t(code, "btnTrade") for code in botlang.ORDER}


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
    {"key": "pair",        "field": "pair",        "kind": "choice", "q": "qPair"},
    {"key": "date",        "field": "date",        "kind": "date",   "q": "qDate"},
    {"key": "session",     "field": "session",     "kind": "choice", "q": "qSession",
     "skip": True},
    {"key": "position",    "field": "position",    "kind": "fixed",  "q": "qPosition",
     "options": [("Long", "Long"), ("Short", "Short")]},
    {"key": "bias",        "field": "bias",        "kind": "choice", "q": "qBias",
     "skip": True},
    {"key": "setup",       "field": "setup",       "kind": "choice", "q": "qSetup",
     "skip": True},
    {"key": "entry_model", "field": "entry_model", "kind": "choice", "q": "qEntryModel",
     "skip": True},
    {"key": "account",     "field": "account",     "kind": "choice", "q": "qAccount",
     "skip": True},
    {"key": "result",      "field": "result",      "kind": "fixed",  "q": "qResult",
     "options": RESULTS},
    {"key": "rr",          "field": "rr",          "kind": "number", "q": "qRr",
     "skip": True, "only_if_result": RR_RESULTS},
    {"key": "risk",        "field": "risk",        "kind": "number", "q": "qRisk",
     "skip": True},
    {"key": "shot",        "field": None,          "kind": "photo",  "q": "qShot",
     "skip": True},
    {"key": "emotion",     "field": "emotion",     "kind": "emotion", "q": "qEmotion",
     "skip": True},
]
BY_KEY = {s["key"]: s for s in STEPS}
ORDER = [s["key"] for s in STEPS]
CONFIRM = "confirm"           # окремий «крок»: картка з підтвердженням


def _label(step, value, label, lang):
    """Підпис варіанта: у закритих списках частина з них — ключі словника
    («рукою», «скіп»), решта однакова всіма мовами (TP, SL, Long)."""
    return t(lang, label) if label in botlang.PHRASES else label


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

def _options(user_id, step, trade, lang):
    """Що показати кнопками на цьому кроці: (підписи, значення).

    Підписи — мовою людини, значення — те, що ляже в журнал.
    """
    kind = step["kind"]
    if kind == "fixed":
        return ([_label(step, v, l, lang) for v, l in step["options"]],
                [v for v, _l in step["options"]])
    if kind == "date":
        today = datetime.datetime.now(KYIV).date()
        vals = [today.isoformat(), (today - datetime.timedelta(days=1)).isoformat()]
        return [t(lang, "today"), t(lang, "yesterday")], vals
    if kind == "number":
        last = db.last_number(user_id, step["field"])
        if last is None:
            return [], []
        return [t(lang, "asLastTime", _num(last))], [str(last)]
    if kind == "emotion":
        # Підпис — мовою людини, а в журнал іде українське написання:
        # інакше розріз по емоціях розсиплеться на мовні варіанти.
        return ([t(lang, "em" + code.capitalize()) for code, _l in emotions.OPTIONS],
                [label for _c, label in emotions.OPTIONS])
    if not step["field"]:
        # Крок без поля журналу — скрін. Пропонувати нічого, там чекають
        # картинку, а не вибір; лишається сама навігація.
        return [], []
    vals = db.frequent_values(user_id, step["field"], TOP)
    return list(vals), list(vals)


def _keyboard(step, labels, skip_ok, first, lang):
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
    rows.append(nav_row(key, lang, back=not first, skip=skip_ok))
    return rows


def nav_row(key, lang, back=True, skip=False):
    nav = []
    if back:
        nav.append({"text": t(lang, "back"), "callback_data": "tw:b:%s" % key})
    if skip:
        nav.append({"text": t(lang, "skip"), "callback_data": "tw:s:%s" % key})
    nav.append({"text": t(lang, "cancel"), "callback_data": "tw:x"})
    return nav


def _num(v):
    """Числа показуємо без хвоста .0 — «1» замість «1.0»."""
    if v is None:
        return ""
    f = float(v)
    return str(int(f)) if f == int(f) else ("%g" % f)


# ------------------------------------------------------------------ картка ----

SHOW = [("pair", "fPair"), ("date", "fDate"), ("session", "fSession"),
        ("position", "fPosition"), ("bias", "fBias"), ("setup", "fSetup"),
        ("entry_model", "fEntryModel"), ("account", "fAccount"),
        ("result", "fResult"), ("rr", "fRr"), ("risk", "fRisk"),
        ("emotion", "fEmotion")]
RES_LABEL = dict(RESULTS)


def card(trade, lang=botlang.DEFAULT):
    lines = []
    for key, title in SHOW:
        v = trade.get(key)
        if v in (None, ""):
            continue
        if key == "result":
            label = RES_LABEL.get(v, v)
            v = t(lang, label) if label in botlang.PHRASES else label
        elif key in ("rr", "risk"):
            v = _num(v)
        lines.append("%s: %s" % (t(lang, title), v))
    shots = len(trade.get("screenshots") or [])
    if shots:
        lines.append(t(lang, "fShots", shots))
    return "\n".join(lines) or t(lang, "cardEmpty")


def _confirm_kb(lang):
    return [[{"text": t(lang, "save"), "callback_data": "tw:ok"}],
            nav_row(CONFIRM, lang)]


# ------------------------------------------------------------------- показ ----

def _ask(user, chat_id, draft):
    """Питання поточного кроку. Стан чернетки зберігаємо тут же, разом зі
    списком варіантів: кнопка повертає номер, і без списку його нічим
    розшифрувати після перезапуску бота."""
    uid, lang = user["id"], botlang.of(user)
    key = draft["step"]
    trade = draft["data"].get("trade") or {}
    if key == CONFIRM:
        db.draft_save(uid, chat_id, key, draft["data"])
        tg_api.send_message(chat_id, t(lang, "cardHead") + "\n\n" + card(trade, lang)
                            + "\n\n" + t(lang, "cardAsk"), keyboard=_confirm_kb(lang))
        return
    step = BY_KEY[key]
    labels, values = _options(uid, step, trade, lang)
    draft["data"]["opts"] = values
    db.draft_save(uid, chat_id, key, draft["data"])
    hints = {"choice": "hintOwn", "number": "hintNumber",
             "date": "hintDate", "emotion": "hintEmotion"}
    hint = hints.get(step["kind"])
    text = t(lang, step["q"]) + ("\n" + t(lang, hint) if hint else "")
    first = _prev_key(key, trade) is None
    tg_api.send_message(chat_id, text,
                        keyboard=_keyboard(step, labels, step.get("skip"), first, lang))


# ------------------------------------------------------------------ початок ----

def start(user, chat_id):
    """Нова чернетка. Стару мовчки замінюємо: якщо людина натиснула
    «Записати угоду» посеред попередньої, вона саме цього й хоче."""
    trade = {"id": _new_id(), "screenshots": []}
    draft = {"chat_id": chat_id, "step": ORDER[0], "data": {"trade": trade}}
    _ask(user, chat_id, draft)


def active(user_id):
    return db.draft_get(user_id) is not None


# ------------------------------------------------------------------ відповіді ----

def _set(user, chat_id, draft, value):
    """Записати відповідь у поле й перейти далі."""
    key = draft["step"]
    step = BY_KEY[key]
    trade = draft["data"].setdefault("trade", {})
    field = step["field"]
    if field and value is not None:
        trade[field] = value
    draft["step"] = _next_key(key, trade)
    _ask(user, chat_id, draft)


def on_text(user, chat_id, text):
    """Текст під час сценарію. Повертає True, якщо повідомлення наше."""
    draft = db.draft_get(user["id"])
    if not draft:
        return False
    lang = botlang.of(user)
    key = draft["step"]
    if key == CONFIRM:
        tg_api.send_message(chat_id, t(lang, "pressButtons"))
        return True
    step = BY_KEY[key]
    raw = (text or "").strip()
    if step["kind"] == "photo":
        # На кроці зі скріном текст — це майже завжди «нема» чи «пізніше».
        _set(user, chat_id, draft, None)
        return True
    if step["kind"] == "number":
        try:
            value = float(raw.replace(",", ".").replace("%", "").strip())
        except ValueError:
            tg_api.send_message(chat_id, t(lang, "notNumber"))
            return True
        _set(user, chat_id, draft, value)
        return True
    if step["kind"] == "date":
        day = _parse_date(raw)
        if not day:
            tg_api.send_message(chat_id, t(lang, "notDate"))
            return True
        _set(user, chat_id, draft, day)
        return True
    if step["kind"] == "fixed":
        # Закритий список: приймаємо тільки те, що є серед кнопок, інакше
        # в журнал поїде «лонк» і зламає розріз по напрямку. Підпис
        # звіряємо всіма мовами — людина могла прочитати кнопку однією, а
        # написати іншою.
        for value, label in step["options"]:
            names = {value.lower()}
            if label in botlang.PHRASES:
                names |= {t(code, label).lower() for code in botlang.ORDER}
            else:
                names.add(label.lower())
            if raw.lower() in names:
                _set(user, chat_id, draft, value)
                return True
        tg_api.send_message(chat_id, t(lang, "useButton"))
        return True
    if step["kind"] == "emotion":
        # Свої слова зводимо до категорії — так само, як після угоди з сайту.
        label = emotions.classify(raw[:200]) or raw[:200]
        _set(user, chat_id, draft, label)
        return True
    _set(user, chat_id, draft, raw[:200])
    return True


def _parse_date(raw):
    t_ = raw.lower().strip()
    today = datetime.datetime.now(KYIV).date()
    if t_ in ("сьогодні", "сегодня", "today"):
        return today.isoformat()
    if t_ in ("вчора", "вчера", "yesterday"):
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
    lang = botlang.of(user)
    trade = draft["data"].setdefault("trade", {})
    # Телеграм присилає кілька розмірів одного фото — беремо найбільший.
    best = max(photos, key=lambda p: p.get("file_size") or 0)
    try:
        path = tg_api.get_file(best["file_id"])["file_path"]
        raw = tg_api.download(path)
    except Exception as ex:
        print("скрін не забрався:", ex)
        tg_api.send_message(chat_id, t(lang, "shotFailed"))
        return True
    ext = (path.rsplit(".", 1)[-1] or "jpg").lower()
    if ext not in ("jpg", "jpeg", "png", "webp"):
        ext = "jpg"
    name = "%s_%d.%s" % (trade.get("id") or _new_id(), int(time.time() * 1000) % 100000000, ext)
    filestore.put(name, raw)
    trade.setdefault("screenshots", []).append({"tf": "", "file": name})
    db.draft_save(user["id"], chat_id, draft["step"], draft["data"])
    # Кілька скрінів підряд — звичайна річ (сетап, вхід, вихід), тому крок
    # не закриваємо: людина йде далі кнопкою.
    if draft["step"] == "shot":
        tg_api.send_message(
            chat_id, t(lang, "shotOk", len(trade["screenshots"])),
            keyboard=[[{"text": t(lang, "next"), "callback_data": "tw:s:shot"}],
                      nav_row("shot", lang)])
    else:
        tg_api.send_message(chat_id, t(lang, "shotAdded"))
    return True


# ------------------------------------------------------------------ кнопки ----

def on_callback(cq, user):
    """Натиснута кнопка сценарію. Повертає True, якщо вона наша."""
    data = cq.get("data") or ""
    if not data.startswith("tw:"):
        return False
    chat_id = cq["message"]["chat"]["id"]
    lang = botlang.of(user)
    draft = db.draft_get(user["id"])
    if not draft:
        tg_api.answer_callback(cq["id"], t(lang, "gone"))
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
        tg_api.answer_callback(cq["id"], t(lang, "oldStep"))
        _ask(user, chat_id, draft)
        return True

    if action == "x":
        db.draft_clear(user["id"])
        tg_api.answer_callback(cq["id"])
        tg_api.send_message(chat_id, t(lang, "cancelled"))
        return True

    if action == "b":
        prev = _prev_key(draft["step"], trade)
        if prev is None:
            tg_api.answer_callback(cq["id"], t(lang, "firstStep"))
            return True
        # Значення кроку, на який повертаємось, забуваємо — інакше воно
        # мовчки лишилося б старим, хоч людина прийшла його змінити.
        field = BY_KEY[prev]["field"]
        if field:
            trade.pop(field, None)
        draft["step"] = prev
        tg_api.answer_callback(cq["id"])
        _ask(user, chat_id, draft)
        return True

    if action == "s":
        tg_api.answer_callback(cq["id"])
        _set(user, chat_id, draft, None)
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
            tg_api.answer_callback(cq["id"], t(lang, "oldButton"))
            _ask(user, chat_id, draft)
            return True
        step = BY_KEY.get(draft["step"])
        if step and step["kind"] == "number":
            try:
                value = float(value)
            except ValueError:
                value = None
        tg_api.answer_callback(cq["id"])
        _set(user, chat_id, draft, value)
        return True

    tg_api.answer_callback(cq["id"])
    return True


# ------------------------------------------------------------------- запис ----

def _save(user, chat_id, draft):
    lang = botlang.of(user)
    trade = draft["data"].get("trade") or {}
    if not (trade.get("pair") or "").strip():
        tg_api.send_message(chat_id, t(lang, "noPair"))
        db.draft_clear(user["id"])
        return
    t_ = {"id": trade.get("id") or _new_id()}
    for f in db.TEXT_FIELDS:
        t_[f] = trade.get(f) or ""
    for f in db.NUM_FIELDS:
        v = trade.get(f)
        t_[f] = float(v) if isinstance(v, (int, float)) else None
    t_["screenshots"] = trade.get("screenshots") or []
    # Емоцію в сценарії вже питали, тому вдогонку її не питаємо: статус
    # «na» саме про це — «питання не стоїть».
    db.insert_trade(user["id"], t_, "na")
    db.draft_clear(user["id"])
    # Клавіатуру повертаємо разом із відповіддю: наступну угоду записують
    # тією ж кнопкою, і шукати її після розмови не доводиться.
    tg_api.send_message(chat_id, t(lang, "saved") + "\n\n" + card(t_, lang)
                        + "\n\n" + t(lang, "openIt") + SITE_URL,
                        reply_kb=reply_kb(lang))

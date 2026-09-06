# -*- coding: utf-8 -*-
"""Запис угоди в боті: проходимо сценарій від кнопки до рядка в журналі.

База й Телеграм підмінені: перевіряємо саму логіку кроків — що питається,
що записується і що потрапляє в журнал. Ловимо те, через що сценарій
псував би дані мовчки: RR за стопом (його там не питають), «назад» зі
старим значенням і чужі слова в закритих списках.
"""
import sys
import types

# --- підміна db і tg_api до імпорту сценарію ---------------------------------
fake_db = types.ModuleType("db")
fake_db.TEXT_FIELDS = ["pair", "date", "session", "position", "entry_model", "bias",
                       "setup", "direction_type", "result", "account", "entry_details",
                       "notes", "mistakes", "comments", "emotion", "notion_id", "import_id"]
fake_db.NUM_FIELDS = ["rr", "risk", "rr_plan"]

STORE = {"draft": None, "saved": []}
fake_db.draft_get = lambda uid: STORE["draft"]
fake_db.draft_save = lambda uid, chat, step, data: STORE.__setitem__(
    "draft", {"chat_id": chat, "step": step, "data": data})
fake_db.draft_clear = lambda uid: STORE.__setitem__("draft", None)
fake_db.frequent_values = lambda uid, field, limit=6: {
    "pair": ["EURUSD", "NQ"], "session": ["Лондон", "Нью-Йорк"],
    "bias": ["Бичачий"], "setup": ["FVG"], "entry_model": ["CISD"],
    "account": ["FundingPips"]}.get(field, [])
fake_db.last_number = lambda uid, field: 1.0 if field == "risk" else None
fake_db.insert_trade = lambda uid, t, status: STORE["saved"].append((t, status))
# Мову бот тримає в meta під ключем «lang:<telegram_id>» (див. botlang).
LANG = {"value": ""}
fake_db.meta_get = lambda key, default="": LANG["value"] or default
fake_db.meta_set = lambda key, value: LANG.__setitem__("value", value)

fake_tg = types.ModuleType("tg_api")
SENT = []
fake_tg.send_message = lambda chat, text, keyboard=None, parse_mode=None, reply_kb=None: (
    SENT.append({"text": text, "kb": keyboard}))
fake_tg.answer_callback = lambda cid, text=None: None
fake_tg.get_file = lambda fid: {"file_path": "photos/x.jpg"}
fake_tg.download = lambda path, timeout=30: b"picture"

fake_store = types.ModuleType("filestore")
PUT = []
fake_store.put = lambda name, raw, mime=None: PUT.append(name)

fake_emotions = types.ModuleType("emotions")
fake_emotions.OPTIONS = [("sp", "Спокій"), ("st", "Страх")]
fake_emotions.LABELS = dict(fake_emotions.OPTIONS)
fake_emotions.classify = lambda text: "Страх" if "страш" in text.lower() else None

sys.modules["db"] = fake_db
sys.modules["tg_api"] = fake_tg
sys.modules["filestore"] = fake_store
sys.modules["emotions"] = fake_emotions

import trade_flow as tf                                       # noqa: E402

USER = {"id": 7}
CHAT = 100


def check(name, cond):
    print("  %-5s %s" % ("ok" if cond else "ПАДАЄ", name))
    assert cond, name


def last():
    return SENT[-1]


def press(action, arg=None, step_key=None):
    """Натиснути кнопку сценарію. За замовчуванням — кнопку поточного кроку;
    step_key дозволяє натиснути кнопку зі старого повідомлення."""
    key = step_key or (STORE["draft"] or {}).get("step") or ""
    data = "tw:%s" % action
    if action in ("v", "s", "b"):
        data += ":%s" % key
    if arg is not None:
        data += ":%d" % arg
    tf.on_callback({"id": "c", "data": data, "message": {"chat": {"id": CHAT}}}, USER)


def step():
    return STORE["draft"]["step"]


def trade():
    return STORE["draft"]["data"]["trade"]


def reset():
    STORE["draft"] = None
    STORE["saved"].clear()
    SENT.clear()
    PUT.clear()


def check_order():
    """Кнопки ведуть по кроках, значення лягають у поля."""
    reset()
    tf.start(USER, CHAT)
    check("почали з пари", step() == "pair")
    check("варіанти пари з журналу", "EURUSD" in last()["text"] or
          any("EURUSD" in b["text"] for row in last()["kb"] for b in row))
    press("v", 0)                                   # EURUSD
    check("пара записана", trade()["pair"] == "EURUSD")
    check("далі дата", step() == "date")
    press("v", 0)                                   # сьогодні
    check("дата у форматі журналу", len(trade()["date"]) == 10 and trade()["date"][4] == "-")
    press("s")                                      # сесію пропускаємо
    check("пропуск не пише порожнечу", "session" not in trade())
    check("далі напрямок", step() == "position")
    press("v", 0)
    check("напрямок Long", trade()["position"] == "Long")


def check_loss_skips_rr():
    """За стопом RR не питаємо: він там ні на що не впливає."""
    reset()
    STORE["draft"] = {"chat_id": CHAT, "step": "result",
                      "data": {"trade": {"id": "t1", "pair": "NQ"},
                               "opts": [v for v, _l in tf.RESULTS]}}
    press("v", 2)                                   # Loss
    check("результат Loss", trade()["result"] == "Loss")
    check("RR пропущено, одразу ризик", step() == "risk")

    reset()
    STORE["draft"] = {"chat_id": CHAT, "step": "result",
                      "data": {"trade": {"id": "t2", "pair": "NQ"},
                               "opts": [v for v, _l in tf.RESULTS]}}
    press("v", 0)                                   # Win
    check("за тейком RR питаємо", step() == "rr")


def check_text_answers():
    """Своє значення текстом, число з комою, чужі слова в закритому списку."""
    reset()
    STORE["draft"] = {"chat_id": CHAT, "step": "pair",
                      "data": {"trade": {"id": "t3"}, "opts": ["EURUSD"]}}
    tf.on_text(USER, CHAT, "XAUUSD")
    check("своя пара текстом", trade()["pair"] == "XAUUSD")

    STORE["draft"]["step"] = "rr"
    tf.on_text(USER, CHAT, "2,5")
    check("кома як крапка", trade()["rr"] == 2.5)

    STORE["draft"]["step"] = "risk"
    tf.on_text(USER, CHAT, "ой")
    check("не число — питаємо ще раз", step() == "risk" and "число" in last()["text"])

    STORE["draft"]["step"] = "position"
    STORE["draft"]["data"]["opts"] = ["Long", "Short"]
    tf.on_text(USER, CHAT, "лонк")
    check("чуже слово в закритий список не пускаємо", "position" not in trade())
    tf.on_text(USER, CHAT, "short")
    check("своє написання зводимо до коду", trade()["position"] == "Short")

    STORE["draft"]["step"] = "date"
    tf.on_text(USER, CHAT, "05.09.2026")
    check("дата з крапками", trade()["date"] == "2026-09-05")

    STORE["draft"]["step"] = "emotion"
    tf.on_text(USER, CHAT, "було страшно")
    check("емоцію звели до категорії", trade()["emotion"] == "Страх")


def check_back():
    """«Назад» повертає до кроку й забуває стару відповідь."""
    reset()
    STORE["draft"] = {"chat_id": CHAT, "step": "position",
                      "data": {"trade": {"id": "t4", "pair": "NQ", "date": "2026-09-05",
                                         "session": "Лондон"}, "opts": []}}
    press("b")
    check("повернулись на сесію", step() == "session")
    check("старе значення забуте", "session" not in trade())


def check_photo():
    """Скрін лягає в сховище картинок і в саму угоду."""
    reset()
    STORE["draft"] = {"chat_id": CHAT, "step": "shot",
                      "data": {"trade": {"id": "t5", "pair": "NQ"}, "opts": []}}
    tf.on_photo(USER, CHAT, [{"file_id": "a", "file_size": 10},
                             {"file_id": "b", "file_size": 900}])
    check("картинка збережена", len(PUT) == 1 and PUT[0].startswith("t5_"))
    check("скрін у списку угоди", trade()["screenshots"][0]["file"] == PUT[0])
    check("крок не закрився — можна ще один", step() == "shot")


def check_save():
    """Підтвердження пише угоду в журнал і прибирає чернетку."""
    reset()
    STORE["draft"] = {"chat_id": CHAT, "step": tf.CONFIRM,
                      "data": {"trade": {"id": "t6", "pair": "EURUSD", "date": "2026-09-05",
                                         "position": "Long", "result": "Win", "rr": 2.0,
                                         "risk": 1.0, "emotion": "Спокій",
                                         "screenshots": [{"tf": "", "file": "t6_1.jpg"}]},
                               "opts": []}}
    press("ok")
    check("угода записана", len(STORE["saved"]) == 1)
    t, status = STORE["saved"][0]
    check("усі поля журналу на місці", set(tf.db.TEXT_FIELDS) <= set(t))
    check("числа числами", t["rr"] == 2.0 and t["risk"] == 1.0)
    check("незаповнене — порожній рядок, не None", t["setup"] == "" and t["notes"] == "")
    check("скрін переїхав", t["screenshots"][0]["file"] == "t6_1.jpg")
    check("емоцію вдогонку не питаємо", status == "na")
    check("чернетки більше немає", STORE["draft"] is None)

    # Без пари угоди не буває: така чернетка не має доїхати до журналу.
    reset()
    STORE["draft"] = {"chat_id": CHAT, "step": tf.CONFIRM,
                      "data": {"trade": {"id": "t7"}, "opts": []}}
    press("ok")
    check("без пари не записуємо", not STORE["saved"] and STORE["draft"] is None)


def check_full_walk():
    """Проходимо сценарій цілком, кнопка за кнопкою.

    Саме так знайшлася поломка на кроці зі скріном: у нього немає поля
    журналу, а варіанти для кнопок усе одно запитувались — і сценарій
    обривався на середині. Окремі кроки такого не ловлять, тільки прохід
    від початку до картки.
    """
    reset()
    tf.start(USER, CHAT)
    seen = []
    for _ in range(len(tf.STEPS) + 2):
        if step() == tf.CONFIRM:
            break
        seen.append(step())
        press("s") if tf.BY_KEY[step()].get("skip") else press("v", 0)
    check("дійшли до картки", step() == tf.CONFIRM)
    check("крок зі скріном пройдено", "shot" in seen)
    check("картка показана", "Записати в журнал?" in last()["text"])


def check_old_button():
    """Кнопка зі старого повідомлення не записує чуже значення.

    Саме на цьому сценарій спіткнувся живцем: людина прокрутила чат до
    попереднього питання й натиснула кнопку там, а номер кнопки пішов у
    список варіантів уже іншого кроку — IndexError і мовчання у відповідь.
    """
    reset()
    STORE["draft"] = {"chat_id": CHAT, "step": "position",
                      "data": {"trade": {"id": "t9", "pair": "NQ"},
                               "opts": ["Long", "Short"]}}
    press("v", 5, step_key="result")          # кнопка з кроку результату
    check("чужий крок нічого не записав", "result" not in trade()
          and "position" not in trade())
    check("лишились на своєму кроці", step() == "position")
    check("питання повторили", "Напрямок" in last()["text"])

    # А ще номер може вилетіти за межі списку вже свого кроку — теж не падаємо.
    STORE["draft"]["data"]["opts"] = ["Long"]
    press("v", 7)
    check("номер поза списком — питаємо ще раз", step() == "position"
          and "position" not in trade())


def check_language():
    """Питання й кнопки — мовою людини, а значення в журнал ідуть як є."""
    reset()
    ru = {"id": 7, "telegram_id": 42}
    LANG["value"] = "ru"
    try:
        tf.start(ru, CHAT)
        check("питання російською", "Какая пара" in last()["text"])
        check("навігація російською",
              any("Отменить" in b["text"] for row in last()["kb"] for b in row))
        check("вибір способу російською",
              "Пошагово" in [b["text"] for row in tf.mode_kb("ru") for b in row])

        # Емоція: підпис російський, а в журнал іде українське написання —
        # інакше розріз по емоціях розсиплеться на мовні варіанти.
        STORE["draft"] = {"chat_id": CHAT, "step": "emotion",
                          "data": {"trade": {"id": "tl", "pair": "NQ"}, "opts": []}}
        tf._ask(ru, CHAT, STORE["draft"])
        labels = [b["text"] for row in last()["kb"] for b in row]
        check("емоції показані російською", "Спокойствие" in labels)
        check("у журнал іде українське написання",
              STORE["draft"]["data"]["opts"][0] == "Спокій")
    finally:
        LANG["value"] = ""


def check_cancel():
    reset()
    STORE["draft"] = {"chat_id": CHAT, "step": "setup",
                      "data": {"trade": {"id": "t8", "pair": "NQ"}, "opts": []}}
    press("x")
    check("скасування прибирає чернетку", STORE["draft"] is None and not STORE["saved"])


check_order()
check_loss_skips_rr()
check_text_answers()
check_back()
check_photo()
check_full_walk()
check_old_button()
check_language()
check_save()
check_cancel()
print("\nусе добре")

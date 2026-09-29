# -*- coding: utf-8 -*-
"""Підписка в боті: /plan і відмови з кнопкою на тарифи.

Телеграм і база підмінені, правила підписки — теж: тут перевіряємо не
самі ліміти (це test_billing.py), а що бот каже людині, коли безкоштовне
скінчилось, і чи веде кнопка в тарифи.

Головне, що ловимо: лічильник «лишилось N із 20» не має з'явитися ніде
(рішення власника 22.09.2026), а відмова без кнопки — це глухий кут.
"""
import billing
import bot
import botlang
import trade_flow

SENT = []


def _send(chat, text, keyboard=None, parse_mode=None, reply_kb=None):
    SENT.append({"text": text, "kb": keyboard})


bot.tg_api.send_message = _send          # той самий модуль бачить і trade_flow
bot.tg_api.send_typing = lambda chat: None

USER = {"id": 7, "telegram_id": 500, "nickname": "tester"}
STATE = {"user": USER, "plan": None, "free_ai": True, "free_trade": True}

bot.db.get_user_by_telegram = lambda tg: STATE["user"]
bot.db.get_user = lambda uid: STATE["user"]
bot.db.pending_emotion_trades = lambda uid: []
bot.db.draft_get = lambda uid: None
bot.db.meta_get = lambda key, default="": "uk"
bot.db.meta_set = lambda key, value: None

billing.state = lambda u: STATE["plan"] or {
    "plan": "free", "active": False, "paid_until": None}
billing.free_terms = lambda u: {"trades": 20, "bt": 20, "imports": 3,
                                "import_days": 30, "ai": 15}
billing.can_use_ai = lambda u: (True, "") if STATE["free_ai"] is True else (
    False, STATE["free_ai"])
billing.can_add_trade = lambda u, kind="": (True, "") if STATE["free_trade"] else (
    False, billing.TRADES_LIMIT)


def check(name, cond):
    print("  %-5s %s" % ("ok" if cond else "ПАДАЄ", name))
    assert cond, name


def last():
    return SENT[-1]


def reset():
    SENT.clear()
    STATE.update({"user": USER, "plan": None, "free_ai": True, "free_trade": True})


def button():
    """Текст кнопки-посилання під повідомленням, або порожньо."""
    kb = last()["kb"]
    return kb[0][0]["text"] if kb else ""


def link():
    kb = last()["kb"]
    return kb[0][0].get("url", "") if kb else ""


def check_plan_free():
    """Без підписки /plan каже умови — і веде в тарифи."""
    reset()
    bot.on_plan(100, 500)
    text = last()["text"]
    check("сказали, що безкоштовно", "Зараз безкоштовно" in text)
    check("назвали умови", "20 угод" in text and "15 звернень" in text)
    check("сказали, що записане лишається", "лишається назавжди" in text)
    check("кнопка веде в тарифи", button() == "Подивитись тарифи")
    check("посилання на розділ підписки", link().endswith("/#plan"))
    check("залишку не показуємо", "лишилось" not in text and "осталось" not in text)


def check_plan_paid():
    """З підпискою — тариф і дата, кликати в тарифи нема чого."""
    reset()
    STATE["plan"] = {"plan": "year", "active": True,
                     "paid_until": "2027-09-22T12:00:00+00:00"}
    bot.on_plan(100, 500)
    text = last()["text"]
    check("назвали тариф", "річна" in text)
    check("назвали дату по-людськи", "22.09.2027" in text)
    check("сказали, що все відкрито", "без обмежень" in text)
    check("кнопки тарифів немає", button() == "")


def check_plan_unlinked():
    """Журнал не прив'язаний — спершу про це."""
    reset()
    STATE["user"] = None
    bot.on_plan(100, 500)
    check("просимо прив'язати журнал", "прив'яжи журнал" in last()["text"])


def check_plan_language():
    """Мова людини — і в /plan теж."""
    reset()
    bot.db.meta_get = lambda key, default="": "ru"
    try:
        bot.on_plan(100, 500)
        check("умови російською", "Сейчас бесплатно" in last()["text"])
        check("кнопка російською", button() == "Посмотреть тарифы")
    finally:
        bot.db.meta_get = lambda key, default="": "uk"


def check_chat_refusal():
    """Порція звернень скінчилась — відмова з кнопкою, а не мовчання."""
    reset()
    STATE["free_ai"] = billing.AI_LIMIT
    bot.on_text(100, 500, "як мої справи цього тижня?")
    check("сказали про порцію", "порція звернень" in last()["text"])
    check("кнопка на тарифи", button() == "Подивитись тарифи")
    check("залишку не показуємо", "лишилось" not in last()["text"])


def check_chat_cap():
    """Стеля в того, хто платить, — інша розмова: тарифи йому не потрібні."""
    reset()
    STATE["free_ai"] = billing.AI_CAP
    bot.on_text(100, 500, "як мої справи цього тижня?")
    check("просимо зачекати", "Трохи згодом" in last()["text"])
    check("у тарифи не кличемо", button() == "")


def check_report_refusal():
    """Таблицю емоцій віддаємо завжди — платний тільки висновок моделі."""
    reset()
    STATE["free_ai"] = billing.AI_LIMIT
    rows = [{"emotion": "Спокій", "risk": 1.0, "rr": 2.0, "result": "Win"}] * 6
    bot.db.trades_with_emotion = lambda uid: rows
    bot.on_report(100, 500)
    text = last()["text"]
    check("таблиця на місці", "Спокій" in text)
    check("сказали про порцію", "порція звернень" in text)
    check("кнопка на тарифи", button() == "Подивитись тарифи")


def check_trade_refusal():
    """Сценарій запису: відмова теж із кнопкою."""
    reset()
    STATE["free_trade"] = False
    trade_flow.start(USER, 100)
    check("сценарій не почався", "Безкоштовні угоди скінчились" in last()["text"])
    check("кнопка на тарифи", button() == "Подивитись тарифи")
    check("залишку не показуємо", "лишилось" not in last()["text"])


def check_all_languages():
    """Жодного ключа без перекладу — інакше людина побачить сам ключ."""
    keys = ["planBtn", "planFree", "planFreeWhat", "planKeep", "planPaid",
            "planPaidWhat", "planMonth", "planQuarter", "planYear",
            "subTrades", "subAi", "subAiCap"]
    bad = [k for k in keys
           if len(botlang.PHRASES.get(k, ())) != 3
           or any(not str(v).strip() for v in botlang.PHRASES.get(k, ()))]
    check("усі слова трьома мовами", not bad)
    same = [k for k in keys if len(set(botlang.PHRASES[k])) != 3]
    check("переклад не скопійований", not same)


print("підписка в боті")
check_plan_free()
check_plan_paid()
check_plan_unlinked()
check_plan_language()
check_chat_refusal()
check_chat_cap()
check_report_refusal()
check_trade_refusal()
check_all_languages()
print("\nусе добре")

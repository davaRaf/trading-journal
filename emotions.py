# -*- coding: utf-8 -*-
"""
Опрос про эмоцию после сделки: список вариантов и сообщение с кнопками.
Модуль общий — сайт отправляет вопрос, бот принимает ответ.
"""
import db
import llm
import tg_api

# Код в callback_data держим коротким: у Telegram лимит 64 байта на кнопку.
OPTIONS = [
    ("sp", "Спокій"),
    ("vp", "Впевненість"),
    ("zh", "Жадібність"),
    ("st", "Страх"),
    ("az", "Азарт"),
    ("pm", "Помста"),
    ("nd", "Нудьга"),
]
LABELS = dict(OPTIONS)


def keyboard(trade_id):
    rows, row = [], []
    for code, label in OPTIONS:
        row.append({"text": label, "callback_data": "emo:%s:%s" % (trade_id, code)})
        if len(row) == 2:
            rows.append(row); row = []
    if row:
        rows.append(row)
    rows.append([{"text": "✍️ Написати своє", "callback_data": "emofree:%s" % trade_id}])
    return rows


def prompt_text(trade):
    pair = (trade.get("pair") or "").strip() or "сделка"
    date = (trade.get("date") or "").strip()
    head = "%s%s" % (pair, " · %s" % date if date else "")
    return "Записав угоду: %s\nЯку емоцію відчував під час неї?" % head


OTHER = "Інше"


def classify(text):
    """Свои слова сводим к одной из категорий — иначе разрез в аналитике
    рассыплется на десятки уникальных строк. Не вышло — отдаём None."""
    text = (text or "").strip()
    if not text:
        return None
    for label in LABELS.values():          # уже назвал категорию словом в словаре
        if text.lower() == label.lower():
            return label
    if not llm.enabled():
        return None
    answer = llm.ask(
        "Трейдер описав свій емоційний стан під час угоди. Віднеси опис до однієї "
        "з категорій і надрукуй ЛИШЕ назву категорії, без пояснень.\n"
        "Категорії: %s, %s.\n"
        "Якщо опис не підходить до жодної — надрукуй %s.\n"
        "Опис: %s" % (", ".join(LABELS.values()), OTHER, OTHER, text),
        max_tokens=200)
    if not answer:
        return None
    answer = answer.strip().strip(".").strip()
    for label in list(LABELS.values()) + [OTHER]:
        if answer.lower() == label.lower():
            return label
    return None


def send_prompt(chat_id, trade):
    """Шлём вопрос и запоминаем id сообщения, чтобы потом заменить его ответом."""
    msg = tg_api.send_message(chat_id, prompt_text(trade), keyboard(trade["id"]))
    db.set_emotion_prompt_msg(trade["id"], msg.get("message_id"))
    return msg

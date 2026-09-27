# -*- coding: utf-8 -*-
"""
Опрос про эмоцию после сделки: список вариантов и сообщение с кнопками.
Модуль общий — сайт отправляет вопрос, бот принимает ответ.
"""
import re

import botlang
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
    ("fm", "ФОМО"),      # страх упустити рух — окрема причина входу, не азарт
]
LABELS = dict(OPTIONS)
CODES = [c for c, _l in OPTIONS]
OTHER_CODE = "other"

# У базі емоція лежить кодом (sp, vp… other), кілька — через «, ». Словами
# її показують лише при виводі, мовою того, хто дивиться. Раніше бот писав
# українську назву, а сайт — назву мовою інтерфейсу, і одна емоція в
# аналітиці розпадалась на «Спокій» і «Спокойствие».
#
# Усі написання, що трапляються в старих записах і в імпорті: підписи бота
# (botlang em*), сайту (static/i18n.js), англійські варіанти, «Інше».
ALIASES = {c: c for c in CODES + [OTHER_CODE]}
for _c in CODES:
    for _w in botlang.PHRASES["em" + _c.capitalize()]:
        ALIASES[_w.lower()] = _c
ALIASES.update({
    "calm": "sp", "спокойно": "sp",
    "confidence": "vp", "уверенно": "vp",
    "greed": "zh", "жадність": "zh",
    "fear": "st",
    "excitement": "az", "thrill": "az",
    "revenge": "pm",
    "boredom": "nd",
    "fomo": "fm", "фомо": "fm",
    "інше": OTHER_CODE, "другое": OTHER_CODE, "иное": OTHER_CODE, "other": OTHER_CODE,
})


def code_of(word):
    """Код для одного слова або None, якщо це не наша категорія."""
    return ALIASES.get(str(word or "").strip().lower())


def _parts(value):
    return [p.strip() for p in str(value or "").split(",") if p.strip()]


def norm(value):
    """Як записати в базу: кожне знайоме слово — кодом, своє — як є,
    без повторів. «Спокойствие, Страх» → «sp, st»."""
    out = []
    for p in _parts(value):
        c = code_of(p) or p
        if c not in out:
            out.append(c)
    return ", ".join(out)


def label(value, lang=botlang.DEFAULT):
    """Як показати людині: коди — словами її мови, своє — як є."""
    out = []
    for p in _parts(value):
        c = code_of(p)
        w = (botlang.t(lang, "em" + c.capitalize()) if c in LABELS
             else botlang.t(lang, "emOther") if c == OTHER_CODE else p)
        if w not in out:
            out.append(w)
    return ", ".join(out)


def localize(trades, lang):
    """Копії угод з емоцією словами — для моделі, яка кодів не знає."""
    return [dict(t, emotion=label(t.get("emotion"), lang)) if t.get("emotion") else t
            for t in trades]


def keyboard(trade_id, lang=botlang.DEFAULT):
    """Підписи — мовою людини, у callback_data код. У журнал з коду
    розгортається українська назва (LABELS): у базі має бути одне
    написання на всіх, інакше розріз по емоціях розсиплеться на мовні
    варіанти."""
    rows, row = [], []
    for code, _label in OPTIONS:
        row.append({"text": botlang.t(lang, "em" + code.capitalize()),
                    "callback_data": "emo:%s:%s" % (trade_id, code)})
        if len(row) == 2:
            rows.append(row); row = []
    if row:
        rows.append(row)
    rows.append([{"text": botlang.t(lang, "ownWords"),
                  "callback_data": "emofree:%s" % trade_id}])
    return rows


def nice_date(raw):
    """«2026-09-27T13:43» → «27.09, 13:43»; без часу — «27.09»."""
    raw = (raw or "").strip()
    m = re.match(r"^\d{4}-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?", raw)
    if not m:
        return raw
    mo, d, hh, mm = m.groups()
    return "%s.%s" % (d, mo) + (", %s:%s" % (hh, mm) if hh else "")


def prompt_text(trade, lang=botlang.DEFAULT):
    pair = (trade.get("pair") or "").strip() or "—"
    date = nice_date(trade.get("date"))
    head = "%s%s" % (pair, " · %s" % date if date else "")
    return botlang.t(lang, "emAsk", head)


OTHER = "Інше"


def classify(text):
    """Свои слова сводим к одной из категорий — иначе разрез в аналитике
    рассыплется на десятки уникальных строк. Возвращает код; не вышло — None."""
    text = (text or "").strip()
    if not text:
        return None
    if code_of(text):                      # уже назвал категорию словом (любым языком)
        return code_of(text)
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
    return code_of(answer)


def send_prompt(chat_id, trade):
    """Шлём вопрос и запоминаем id сообщения, чтобы потом заменить его ответом.

    chat_id у бота совпадает с telegram_id человека, поэтому язык берём
    прямо по нему: вопрос приходит с сайта, где о языке бота не знают."""
    lang = botlang.of_tg(chat_id)
    msg = tg_api.send_message(chat_id, prompt_text(trade, lang),
                              keyboard(trade["id"], lang))
    db.set_emotion_prompt_msg(trade["id"], msg.get("message_id"))
    return msg


if __name__ == "__main__":
    assert norm("Спокойствие, Впевненість, Страх") == "sp, vp, st"
    assert norm("Жадібність, Жадность, greed") == "zh"
    assert norm("Інше") == "other" and norm("Другое") == "other"
    assert norm("sp, свое слово") == "sp, свое слово"
    assert label("sp, vp", "ru") == "Спокойствие, Уверенность"
    assert label("other", "en") == "Other" and label("Спокій", "en") == "Calm"
    assert nice_date("2026-09-27T13:43") == "27.09, 13:43" and nice_date("2026-09-27") == "27.09"
    print("ok")

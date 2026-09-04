# -*- coding: utf-8 -*-
"""
Gemini поверх urllib. Модель тут отвечает только за слова:
все числа считаются в коде, иначе им нельзя верить.
Без ключа всё молча выключается — журнал работает как раньше.
"""
import json
import queue
import threading
import time
import urllib.error
import urllib.request

from config import GEMINI_API_KEY

URL = "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent"
# Старшие модели тут не нужны: задачи короткие, а gemini-3.6-flash на том же
# запросе думает под две минуты — для бота это вечность. Замеряно: 1.1 с против 110 с.
MODEL = "gemini-3.5-flash-lite"

# Через сколько секунд молчания пускаем дубль запроса. Замерено: удачный
# ответ приходит за 0.7–2 с, а неудачный не приходит вообще — висит до
# таймаута, и так примерно через раз. От размера запроса это не зависит:
# 8 КБ прилетали за 1.7 с, а «скажи ок» висело десять секунд. Поэтому не
# ждём молча, а через две секунды отправляем ещё одну попытку параллельно и
# берём ту, которая ответит первой. Лишний запрос дешевле долгого ожидания —
# но именно один: у бесплатного ключа есть предел запросов в минуту, и
# веером дублей его выбивает (429 «exceeded your current quota»).
HEDGE_AFTER = 3.5


# Чем закончилась последняя попытка: "quota" — уперлись в предел запросов,
# "silence" — модель не ответила. Нужно, чтобы человеку сказать по делу,
# а не одинаковое «модель не отвечает» на всё подряд.
last_error = None


def enabled():
    return bool(GEMINI_API_KEY)


def _once(data, model, timeout):
    """Одна попытка. Возвращает (текст, отказ-сервера).

    Отказ сервера (4xx/5xx) означает, что повторять бессмысленно —
    в отличие от тишины, которая лечится повтором.
    """
    req = urllib.request.Request(
        URL % model, data=data,
        headers={"Content-Type": "application/json", "x-goog-api-key": GEMINI_API_KEY})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as ex:
        global last_error
        last_error = "quota" if ex.code == 429 else "silence"
        print("gemini: HTTP %s %s" % (ex.code, ex.read().decode("utf-8", "replace")[:200]))
        return None, True
    except Exception as ex:
        print("gemini:", ex)
        return None, False
    try:
        parts = body["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts).strip() or None, True
    except Exception:
        return None, True


def ask(prompt, model=MODEL, max_tokens=900, timeout=8, system=None,
        temperature=0.2, tries=2):
    """Возвращает текст ответа или None, если модель недоступна.

    system — правила, которые модель должна слушать всегда; идут отдельным
    полем API (systemInstruction), а не текстом внутри prompt, поэтому их
    нельзя перебить тем, что написано в данных пользователя.

    temperature — насколько модель вольна в словах. По умолчанию 0.2: там, где
    она пересказывает цифры, разнообразие только вредит. Для живой болтовни
    (бот в Telegram) поднимаем, иначе одна и та же мысль звучит слово в слово.

    timeout — сколько ждём одну попытку; tries — сколько их может быть всего.
    Попытки идут внахлёст (см. HEDGE_AFTER), а не одна за другой.
    """
    if not enabled():
        return None
    global last_error
    last_error = "silence"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
    }
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    box = queue.Queue()

    def shot():
        box.put(_once(data, model, timeout))

    tries = max(1, tries)
    launched = done = 0
    deadline = time.time() + timeout + HEDGE_AFTER * (tries - 1)
    while True:
        if launched < tries:
            threading.Thread(target=shot, daemon=True).start()
            launched += 1
        left = deadline - time.time()
        if done >= tries or (left <= 0 and launched >= tries):
            return None
        try:
            text, hard = box.get(
                timeout=HEDGE_AFTER if launched < tries else max(0.1, left))
        except queue.Empty:
            continue              # молчит — пускаем дубль или ждём дальше
        done += 1
        if text:
            last_error = None
            return text
        if hard:
            return None           # сервер отказал или ответил пустым

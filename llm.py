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
# Куди йти, коли основна відповідає «503, високий попит»: це про конкретну
# модель, і сусідня в ту саму мить відповідає нормально. Перевірено живцем —
# 3.5-flash-lite мовчала десять секунд, а 3.1-flash-lite відповіла за 1.8 с.
SPARE = ("gemini-3.1-flash-lite", "gemini-3.7-flash", "gemini-3-flash-preview",
         "gemini-3.6-flash", "gemini-3.8-flash")

# Через сколько секунд молчания пускаем дубль запроса. Замерено: удачный
# ответ приходит за 0.7–2 с, а неудачный не приходит вообще — висит до
# таймаута, и так примерно через раз. От размера запроса это не зависит:
# 8 КБ прилетали за 1.7 с, а «скажи ок» висело десять секунд. Поэтому не
# ждём молча, а через две секунды отправляем ещё одну попытку параллельно и
# берём ту, которая ответит первой. Лишний запрос дешевле долгого ожидания —
# но именно один: у бесплатного ключа есть предел запросов в минуту, и
# веером дублей его выбивает (429 «exceeded your current quota»).
HEDGE_AFTER = 2.5


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


def _plan(model, tries):
    """Якою моделлю робити кожну спробу.

    Перший постріл — основною, наступні — запасними. Раніше дублювали ту
    саму модель, і це не рятувало: коли Gemini відповідає «503, високий
    попит», він каже це про конкретну модель, і другий такий самий запит
    отримує те саме. Сусідня модель у цей момент відповідає за секунду.
    """
    out = [model]
    for m in SPARE:
        if len(out) >= tries:
            break
        if m != model:
            out.append(m)
    while len(out) < tries:
        out.append(out[-1])
    return out[:max(1, tries)]


def ask(prompt, model=MODEL, max_tokens=900, timeout=8, system=None,
        temperature=0.2, tries=2):
    """Повертає текст відповіді або None, якщо модель недоступна.

    system — правила, які модель має слухати завжди; ідуть окремим полем
    API (systemInstruction), а не текстом усередині prompt, тому їх не
    можна перебити тим, що написано в даних користувача.

    temperature — наскільки модель вільна в словах. Типово 0.2: там, де
    вона переказує цифри, різноманіття лише шкодить. Для живої розмови
    (бот у Telegram) піднімаємо, інакше та сама думка звучить слово в слово.

    timeout — скільки чекаємо одну спробу; tries — скільки їх усього.
    Спроби йдуть внахлест (див. HEDGE_AFTER) і різними моделями (_plan).
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

    def shot(name):
        box.put(_once(data, name, timeout))

    models = _plan(model, tries)
    launched = done = 0
    deadline = time.time() + timeout + HEDGE_AFTER * (len(models) - 1)
    while True:
        if launched < len(models):
            threading.Thread(target=shot, args=(models[launched],), daemon=True).start()
            launched += 1
        left = deadline - time.time()
        if done >= len(models) or (left <= 0 and launched >= len(models)):
            return None
        try:
            text, _hard = box.get(
                timeout=HEDGE_AFTER if launched < len(models) else max(0.1, left))
        except queue.Empty:
            continue              # мовчить — пускаємо наступну модель або чекаємо
        done += 1
        if text:
            last_error = None
            return text
        # Відмова сервера більше не зупиняє все: «503» стосується однієї
        # моделі, тож просто пробуємо наступну зі списку.

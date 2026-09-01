# -*- coding: utf-8 -*-
"""
Gemini поверх urllib. Модель тут отвечает только за слова:
все числа считаются в коде, иначе им нельзя верить.
Без ключа всё молча выключается — журнал работает как раньше.
"""
import json
import urllib.error
import urllib.request

from config import GEMINI_API_KEY

URL = "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent"
# Старшие модели тут не нужны: задачи короткие, а gemini-3.6-flash на том же
# запросе думает под две минуты — для бота это вечность. Замеряно: 1.1 с против 110 с.
MODEL = "gemini-3.5-flash-lite"


def enabled():
    return bool(GEMINI_API_KEY)


def ask(prompt, model=MODEL, max_tokens=900, timeout=30, system=None):
    """Возвращает текст ответа или None, если модель недоступна.

    system — правила, которые модель должна слушать всегда; идут отдельным
    полем API (systemInstruction), а не текстом внутри prompt, поэтому их
    нельзя перебить тем, что написано в данных пользователя.
    """
    if not enabled():
        return None
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": max_tokens},
    }
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}
    req = urllib.request.Request(
        URL % model, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": GEMINI_API_KEY})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as ex:
        print("gemini: HTTP %s %s" % (ex.code, ex.read().decode("utf-8", "replace")[:200]))
        return None
    except Exception as ex:
        print("gemini:", ex)
        return None
    try:
        parts = body["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts).strip() or None
    except Exception:
        return None

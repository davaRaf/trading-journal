# -*- coding: utf-8 -*-
"""
Голос у текст (OpenAI). Людина натискає мікрофон біля «Як заходив»,
диктує — у полі з'являється текст.

Модель gpt-4o-mini-transcribe, а не whisper-1. Заміряно на нашому ж
жаргоні («стоп під лоу азіатської сесії», «4h імбаланс», «RR 2.5»):
whisper-1 злипає слова («стоп подлоуазиатской») і не ставить крапок,
mini-transcribe розставляє все правильно — і коштує вдвічі менше
($0.003 проти $0.006 за хвилину).

Без ключа все мовчки вимикається: кнопка мікрофона не показується,
решта журналу працює як раніше.
"""
import json
import urllib.error
import urllib.request
import uuid

import net4
from config import OPENAI_API_KEY

URL = "https://api.openai.com/v1/audio/transcriptions"
MODEL = "gpt-4o-mini-transcribe"

# Стеля на один запис. Браузер пише opus (~24 кбіт/с), тобто 8 МБ — це
# десятки хвилин: межа тут не для того, щоб обрізати людину, а щоб запит
# із чимось іншим усередині не поїхав до моделі за наші гроші.
MAX_BYTES = 8 * 1024 * 1024

# Модель вибирає декодер за розширенням у назві файла, тому назву
# складаємо самі з того, що сказав браузер. Chrome і Firefox пишуть webm,
# Safari — mp4; решта тут на випадок, коли браузер назве те саме інакше.
EXT = {
    "audio/webm": "webm",
    "audio/ogg": "ogg",
    "audio/oga": "oga",
    "audio/mp4": "mp4",
    "audio/x-m4a": "m4a",
    "audio/m4a": "m4a",
    "audio/aac": "m4a",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/flac": "flac",
}


def enabled():
    return bool(OPENAI_API_KEY)


def ext_for(mime):
    """Розширення для назви файла або "" — такого звуку ми не шлемо."""
    # Браузер дає "audio/webm;codecs=opus" — кодек нас не цікавить.
    base = (mime or "").split(";")[0].strip().lower()
    return EXT.get(base, "")


def _form(fields, filename, blob):
    """Тіло multipart/form-data. Повертає (boundary, байти).

    Руками, бо в журналі немає requests: уся робота назовні — urllib
    (див. net4.py), а стандартна бібліотека multipart складати не вміє.
    """
    bound = "----statsai" + uuid.uuid4().hex
    parts = []
    for key, val in fields.items():
        parts.append(("--%s\r\n"
                      'Content-Disposition: form-data; name="%s"\r\n\r\n'
                      "%s\r\n" % (bound, key, val)).encode("utf-8"))
    parts.append(("--%s\r\n"
                  'Content-Disposition: form-data; name="file"; filename="%s"\r\n'
                  "Content-Type: application/octet-stream\r\n\r\n"
                  % (bound, filename)).encode("utf-8"))
    parts.append(blob)
    parts.append(("\r\n--%s--\r\n" % bound).encode("utf-8"))
    return bound, b"".join(parts)


def transcribe(blob, mime, lang=None, timeout=60):
    """Звук → (текст, причина відмови). Причина порожня, коли все добре.

    Причини: no_key — немає ключа, bad_audio — не той формат або пусто,
    too_big — запис завеликий, quota — вперлися в межу OpenAI,
    silence — модель не відповіла.

    Повертаємо парою, а не через глобальну змінну (як llm.py): сайт
    відповідає кількома робітниками одночасно, і одна глобальна причина
    на всіх дісталась би не тому запиту.
    """
    if not enabled():
        return None, "no_key"
    if not blob:
        return None, "bad_audio"
    if len(blob) > MAX_BYTES:
        return None, "too_big"
    ext = ext_for(mime)
    if not ext:
        return None, "bad_audio"

    fields = {"model": MODEL, "response_format": "json"}
    # Мова інтерфейсу як підказка: короткий запис без неї модель інколи
    # чує як сусідню мову — українське «зайшов» як російське. Коли мова
    # невідома, не передаємо нічого й лишаємо визначати самій.
    if lang in ("uk", "ru", "en"):
        fields["language"] = lang
    bound, body = _form(fields, "voice." + ext, blob)
    req = urllib.request.Request(
        URL, data=body,
        headers={"Authorization": "Bearer %s" % OPENAI_API_KEY,
                 "Content-Type": "multipart/form-data; boundary=%s" % bound})
    try:
        # Тільки по IPv4: маршрут із нашого сервера по IPv6 підвисає
        # на 30 секунд (див. net4.py).
        with net4.urlopen(req, timeout=timeout) as r:
            got = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as ex:
        detail = ex.read().decode("utf-8", "replace")[:300]
        print("voice: HTTP %s %s" % (ex.code, detail), flush=True)
        if ex.code == 429:
            return None, "quota"
        # 400 від OpenAI — це майже завжди «не можу розібрати цей звук»:
        # людині треба сказати «перезапиши», а не «сервіс недоступний».
        if ex.code == 400:
            return None, "bad_audio"
        return None, "silence"
    except Exception as ex:
        print("voice:", ex, flush=True)
        return None, "silence"

    text = (got.get("text") or "").strip() if isinstance(got, dict) else ""
    # Тиша теж повертається як успіх, тільки з порожнім текстом — і
    # вставляти в поле нічого. Для людини це той самий «не почув».
    return (text, "") if text else (None, "bad_audio")

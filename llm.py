# -*- coding: utf-8 -*-
"""
DeepSeek поверх urllib. Модель тут отвечает только за слова:
все числа считаются в коде, иначе им нельзя верить.
Без ключа всё молча выключается — журнал работает как раньше.

Раньше здесь был Gemini. Переехали 05.09.2026: со своего сервера Google
отвечает «User location is not supported» — он не пускает запросы с IP
хостингов. DeepSeek такого не требует, а разговаривает не хуже.
"""
import json
import queue
import threading
import time
import urllib.error
import urllib.request

from config import DEEPSEEK_API_KEY

URL = "https://api.deepseek.com/chat/completions"
# Найдешевша й найшвидша з доступних: відповідає за секунду. Старша
# (deepseek-v4-pro) для наших задач зайва — вони короткі, а коштує вона більше.
MODEL = "deepseek-v4-flash"
# Куди йти, коли основна відмовила. Порожньо: у DeepSeek одна швидка модель,
# і повторний постріл тією самою (див. _plan) виявляється кориснішим за
# перехід на дорожчу.
SPARE = ()

# Модель уміє «думати» перед відповіддю, і ці роздуми з'їдають ті самі
# токени, що й відповідь: на ліміті у 110 токенів (бот у Телеграмі) на
# роздуми йшло 49, а людині лишався огризок. Нам роздуми не потрібні —
# питання прості, тому вимикаємо їх і платимо тільки за слова.
NO_THINKING = {"reasoning_effort": "none"}

# Через сколько секунд молчания пускаем дубль запроса. Замерено: удачный
# ответ приходит за 0.7–2 с, а неудачный не приходит вообще — висит до
# таймаута. Поэтому не ждём молча, а через две секунды отправляем ещё одну
# попытку параллельно и берём ту, которая ответит первой.
HEDGE_AFTER = 2.5


# Чем закончилась последняя попытка: "quota" — уперлись в предел запросов,
# "silence" — модель не ответила. Нужно, чтобы человеку сказать по делу,
# а не одинаковое «модель не отвечает» на всё подряд.
last_error = None


def enabled():
    return bool(DEEPSEEK_API_KEY)


def _once(data, model, timeout):
    """Одна попытка. Возвращает (текст, отказ-сервера).

    Отказ сервера (4xx/5xx) означает, что повторять бессмысленно —
    в отличие от тишины, которая лечится повтором.
    """
    body_out = json.loads(data.decode("utf-8"))
    body_out["model"] = model
    req = urllib.request.Request(
        URL, data=json.dumps(body_out, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer %s" % DEEPSEEK_API_KEY})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as ex:
        global last_error
        last_error = "quota" if ex.code == 429 else "silence"
        print("deepseek: HTTP %s %s" % (ex.code, ex.read().decode("utf-8", "replace")[:200]))
        return None, True
    except Exception as ex:
        print("deepseek:", ex)
        return None, False
    try:
        choice = body["choices"][0]
        text = (choice["message"].get("content") or "").strip()
    except Exception:
        return None, True
    # Модель уперлася у стелю токенів і спинилась на півслові. Раніше такий
    # огризок ішов людині як є («Твоя последняя сделка» — і все). Лишаємо
    # тільки завершені речення, а якщо не лишилось нічого — вважаємо це
    # мовчанням: у циклі вище тоді спробує ще раз.
    if choice.get("finish_reason") == "length":
        text = _whole(text)
    return text or None, True


def _whole(text):
    """Текст до останнього завершеного речення.

    Двадцять символів — межа, нижче якої від відповіді однаково нічого не
    лишилось: краще спробувати ще раз, ніж слати обрубок."""
    cut = max(text.rfind(c) for c in ".!?…")
    return text[:cut + 1].strip() if cut >= 20 else ""


def _plan(model, tries):
    """Якою моделлю робити кожну спробу.

    Перший постріл — основною, наступні — запасними, а коли запасних немає
    (у DeepSeek швидка модель одна) — тією самою. Другий запит однаково не
    марний: перша спроба часто просто зависає, а не відмовляє.
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

    system — правила, які модель має слухати завжди; ідуть окремим
    повідомленням із роллю system, а не текстом усередині prompt, тому їх
    не можна перебити тим, що написано в даних користувача.

    temperature — наскільки модель вільна в словах. Типово 0.2: там, де
    вона переказує цифри, різноманіття лише шкодить. Для живої розмови
    (бот у Telegram) піднімаємо, інакше та сама думка звучить слово в слово.

    timeout — скільки чекаємо одну спробу; tries — скільки їх усього.
    Спроби йдуть внахлест (див. HEDGE_AFTER).
    """
    if not enabled():
        return None
    global last_error
    last_error = "silence"
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    payload.update(NO_THINKING)
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
            continue              # мовчить — пускаємо наступну спробу або чекаємо
        done += 1
        if text:
            last_error = None
            return text
        # Відмова сервера більше не зупиняє все: пробуємо наступну спробу.

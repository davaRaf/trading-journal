# -*- coding: utf-8 -*-
"""
Розбір угоди з живого тексту: «запиши угоду EU лонг по Лондону, +2R».

Другий спосіб запису поруч із покроковим сценарієм (trade_flow.py).
Покроковий питає по одному полю й нічого не вигадує; цей навпаки —
бере все з одного повідомлення й нічого не перепитує. Людина сама
вирішує, що їй зараз зручніше.

Модель тут потрібна саме для розбору: «взяв EU в лонг по лондону, вийшов
у беззбиток» кодом не розібрати — у кожного своя мова, скорочення й
порядок слів. Але вигадувати їй нема чого: усе, чого немає в тексті,
лишається порожнім, а не «схожим на правду».

Щоб журнал не розсипався на синоніми, у запит кладемо те, чим людина
вже користується (db.frequent_values): модель має вибрати з її ж слів,
а не написати «Лондонська сесія» там, де в журналі скрізь «Лондон».

Числа й дати після моделі перевіряємо кодом: їй довіряємо тільки
розкладання по полях.
"""
import datetime
import json
import re
from zoneinfo import ZoneInfo

import db
import llm

KYIV = ZoneInfo("Europe/Kyiv")

# Коди результату — рівно ті, що в журналі (static/app.js).
RESULTS = ("Win", "WinM", "Loss", "BE-", "BE+", "Skip")
POSITIONS = ("Long", "Short")

# Поля, які модель має право заповнити. rr_plan і службові сюди не входять.
TEXT_OUT = ("pair", "date", "session", "position", "bias", "setup",
            "entry_model", "account", "result", "emotion", "notes")
NUM_OUT = ("rr", "risk")

# Слова, з яких видно намір записати угоду. Без цього фільтра модель
# смикали б на кожне «як справи», а це і гроші, і секунда затримки.
INTENT = re.compile(
    r"(запиши|запис|додай|додати|добав|зафіксуй|зафиксируй|"
    r"нова угода|нову угоду|нова сделка|новая сделка|"
    r"log a trade|add a trade|record a trade)", re.I)

# Ознаки, що в тексті таки описана угода, навіть без слова «запиши»:
# результат разом із RR або напрямком.
LOOKS_LIKE = re.compile(
    r"(\b\d+(?:[.,]\d+)?\s*[rR]\b|\brr\b|тейк|стоп|беззбит|безубыт|"
    r"\blong\b|\bshort\b|лонг|шорт|лонк)", re.I)

RULES = (
    "Ти розбираєш повідомлення трейдера про угоду й повертаєш ТІЛЬКИ JSON.\n"
    "Нічого не вигадуй: чого немає в тексті — лишай порожнім рядком або null.\n"
    "Не пояснюй, не додавай тексту поза JSON."
)


def wants_trade(text):
    """Чи схоже це на запис угоди. Дешева перевірка перед моделлю."""
    t = (text or "").strip()
    if len(t) < 6:
        return False
    return bool(INTENT.search(t)) or bool(LOOKS_LIKE.search(t))


def _known(user_id):
    """Значення, якими людина вже користується — по одному списку на поле."""
    out = {}
    for field in ("pair", "session", "bias", "setup", "entry_model", "account"):
        try:
            out[field] = db.frequent_values(user_id, field, 12)
        except Exception:
            out[field] = []
    return out


def _prompt(user_id, text):
    known = _known(user_id)
    today = datetime.datetime.now(KYIV).date()
    lines = [
        "Сьогодні %s (часовий пояс Києва)." % today.isoformat(),
        "",
        "Повідомлення трейдера:",
        text.strip()[:1000],
        "",
        "Поверни JSON із такими ключами:",
        '{"is_trade": true|false, "pair": "", "date": "РРРР-ММ-ДД", "session": "",',
        ' "position": "Long|Short|", "bias": "", "setup": "", "entry_model": "",',
        ' "account": "", "result": "Win|WinM|Loss|BE-|BE+|Skip|", "rr": null,',
        ' "risk": null, "emotion": "", "notes": ""}',
        "",
        "is_trade — чи це справді опис угоди, а не питання чи балачка.",
        "result: Win — узяв тейк, WinM — вийшов у плюс рукою, Loss — стоп,",
        "BE- — беззбиток замість збитку, BE+ — беззбиток замість плюса,",
        "Skip — угоду пропустив.",
        "rr — скільки R принесла угода, risk — ризик у відсотках.",
        "date — сьогоднішня, якщо про день нічого не сказано.",
        "notes — те, що не влізло в інші поля; порожньо, якщо все влізло.",
        "",
        "Ці значення вже є в журналі. Якщо трейдер має на увазі одне з них —",
        "пиши ТОЧНО як тут, буква в букву, навіть коли він скоротив:",
    ]
    for field, vals in known.items():
        if vals:
            lines.append("%s: %s" % (field, ", ".join(vals)))
    lines.append("Немає збігу — пиши так, як сказав трейдер.")
    return "\n".join(lines)


def _json(out):
    """JSON із відповіді моделі. Вона любить обгортати його в ```json."""
    if not out:
        return None
    i, j = out.find("{"), out.rfind("}")
    if i < 0 or j < i:
        return None
    try:
        return json.loads(out[i:j + 1])
    except ValueError:
        return None


def _num(v):
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.replace(",", ".").replace("%", "").strip())
        except ValueError:
            return None
    return None


def _date(v):
    if not isinstance(v, str):
        return ""
    v = v.strip()
    try:
        return datetime.datetime.strptime(v, "%Y-%m-%d").date().isoformat()
    except ValueError:
        return ""


def parse(user_id, text):
    """Поля угоди з тексту або None, якщо це не угода (чи модель мовчить).

    Повертаємо тільки те, що модель справді знайшла: порожні поля не
    заповнюємо ні нулями, ні здогадками — у журналі краще прочерк, ніж
    вигадане значення.
    """
    if not llm.enabled():
        return None
    raw = _json(llm.ask(_prompt(user_id, text), system=RULES, max_tokens=400,
                        timeout=8, tries=3, temperature=0))
    if not isinstance(raw, dict) or not raw.get("is_trade"):
        return None

    out = {}
    for f in TEXT_OUT:
        v = raw.get(f)
        out[f] = v.strip()[:200] if isinstance(v, str) else ""
    for f in NUM_OUT:
        out[f] = _num(raw.get(f))

    out["date"] = _date(raw.get("date")) or datetime.datetime.now(KYIV).date().isoformat()
    if out["position"] not in POSITIONS:
        out["position"] = ""
    if out["result"] not in RESULTS:
        out["result"] = ""
    # Без інструмента це не угода: журнал такий рядок теж не прийме.
    if not out["pair"]:
        return None
    return out

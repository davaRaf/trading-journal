# -*- coding: utf-8 -*-
"""
Звірка щойно записаної угоди з описаною торговою системою.

Людина сама пише свої правила на сторінці «Моя ТС» — інструменти, вікна,
моделі входу, ризик, ліміти. Досі ці правила лежали окремо від журналу:
звірка на сторінці ТС статистична, показує картину за місяць і мовчить у
той момент, коли відхилення щойно сталось.

Тут — навпаки: одна угода проти правил, одразу після запису.

Два принципи:

  * рахує все Python, модель лише переказує готові факти словами
    (той самий підхід, що в assistant.py);
  * порожнє поле ТС мовчить. Людина описала лише ризик — перевіряємо лише
    ризик. Ніяких «типових» значень замість не заповнених.

Назовні йдуть коди відхилень, а не тексти: підписи лежать у i18n.js на
трьох мовах, і сторінка сама вирішує, як їх сказати.
"""
import re

import llm
from assistant import LANG_ORDER, net_pct, when

# Скільки відхилень має сенс показати за раз: більше — це вже не підказка,
# а докір, і людина перестає читати.
MAX_ITEMS = 4

# Дні тижня в трьох мовах, повні й скорочені. Ключ — номер (0 = понеділок).
WEEKDAYS = {
    0: ["понеділок", "понедельник", "monday", "пн", "mon"],
    1: ["вівторок", "вторник", "tuesday", "вт", "tue"],
    2: ["середа", "середу", "среда", "среду", "wednesday", "ср", "wed"],
    3: ["четвер", "четверг", "thursday", "чт", "thu"],
    4: ["п'ятниця", "п'ятницю", "пятница", "пятницу", "friday", "пт", "fri"],
    5: ["субота", "суботу", "суббота", "субботу", "saturday", "сб", "sat"],
    6: ["неділя", "неділю", "воскресенье", "sunday", "нд", "sun"],
}

# Слова, за якими видно, що перелік днів — це саме пропуски, а не робочі дні.
SKIP_WORDS = ["пропус", "не торг", "не входж", "не работ", "skip", "avoid",
              "no trad", "not trad", "вихідн", "выходн", "off"]


def _f(v):
    try:
        return float(str(v).replace(",", ".").replace("%", "").strip())
    except (TypeError, ValueError, AttributeError):
        return None


def _nums(s):
    """Усі числа з рядка: «0.5%, 1%» — це два оголошених розміри ризику."""
    return [float(x.replace(",", ".")) for x in
            re.findall(r"\d+(?:[.,]\d+)?", str(s or ""))]


def _norm(s):
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def _same(a, b):
    """Пари й моделі люди пишуть по-різному: US 100, us100, US-100."""
    clean = lambda s: re.sub(r"[^a-z0-9а-яіїєґ]", "", _norm(s))
    return clean(a) == clean(b) and clean(a) != ""


# ------------------------------------------------------------- правила ----

def _asset(ts, t):
    lst = [a for a in (ts.get("assets") or []) if str(a).strip()]
    pair = (t.get("pair") or "").strip()
    if not lst or not pair:
        return None
    if any(_same(pair, a) for a in lst):
        return None
    return {"code": "asset", "want": ", ".join(str(a) for a in lst), "got": pair}


def _model(ts, t):
    names = [m.get("name") for m in (ts.get("models") or [])
             if isinstance(m, dict) and str(m.get("name") or "").strip()]
    got = (t.get("entry_model") or "").strip()
    if not names or not got:
        return None
    if any(_same(got, n) for n in names):
        return None
    return {"code": "model", "want": ", ".join(names), "got": got}


def _windows(ts, t):
    """Час входу проти торгових вікон. Вікно через північ (22:00 – 02:00)
    теж рахуємо: у нічних сесіях це звичайна річ."""
    spans = []
    for w in (ts.get("windows") or []):
        if not isinstance(w, dict):
            continue
        got = re.findall(r"(\d{1,2})(?::(\d{2}))?", str(w.get("time") or ""))
        if len(got) < 2:
            continue
        a = int(got[0][0]) * 60 + int(got[0][1] or 0)
        b = int(got[1][0]) * 60 + int(got[1][1] or 0)
        if a > 24 * 60 or b > 24 * 60:
            continue
        spans.append((a, b, (w.get("name") or w.get("time") or "").strip()))
    dt = when(t)
    if not spans or not dt:
        return None
    minutes = dt.hour * 60 + dt.minute
    for a, b, _ in spans:
        inside = a <= minutes <= b if a <= b else (minutes >= a or minutes <= b)
        if inside:
            return None
    names = ", ".join(n for _, _, n in spans if n) or \
            ", ".join(str((w or {}).get("time") or "") for w in (ts.get("windows") or []))
    return {"code": "window", "want": names, "got": "%02d:%02d" % (dt.hour, dt.minute)}


def _weekday(ts, t):
    """Пропущені дні. Беремося за правило, лише якщо в рядку видно, що це
    саме пропуски: «пропускаю: понеділок». Інакше «торгую пн-пт» читалось
    би як заборона на всі ці дні."""
    text = _norm(ts.get("days"))
    dt = when(t)
    if not text or not dt:
        return None
    if not any(w in text for w in SKIP_WORDS):
        return None
    for word in WEEKDAYS.get(dt.weekday(), []):
        if re.search(r"(?<![а-яіїєґa-z])%s" % re.escape(word), text):
            return {"code": "weekday", "want": ts.get("days"), "got": word}
    return None


def _risk(ts, t):
    declared = max(_nums((ts.get("risk") or {}).get("per")), default=None)
    got = _f(t.get("risk"))
    if declared is None or got is None or declared <= 0:
        return None
    if got <= declared + 1e-9:
        return None
    return {"code": "risk", "want": "%g%%" % declared, "got": "%g%%" % got}


def _rr(ts, t):
    want = _f((ts.get("risk") or {}).get("rr"))
    got = _f(t.get("rr"))
    if want is None or got is None or want <= 0:
        return None
    if got >= want - 1e-9:
        return None
    return {"code": "rr", "want": "%g" % want, "got": "%g" % got}


def _day_loss(ts, t, day):
    """Денний ліміт збитку. Дивимось підсумок дня разом з новою угодою:
    саме вона могла його й перебити."""
    limit = _f((ts.get("risk") or {}).get("day"))
    if limit is None or limit <= 0:
        return None
    net = sum(net_pct(x) for x in day)
    if net >= -limit - 1e-9:
        return None
    return {"code": "dayloss", "want": "%g%%" % limit, "got": "%+.2f%%" % net}


def _max_trades(ts, t, day):
    limit = _f(ts.get("maxtrades"))
    if limit is None or limit <= 0 or len(day) <= limit:
        return None
    return {"code": "maxtrades", "want": "%g" % limit, "got": str(len(day))}


# --------------------------------------------------------------- збірка ----

def check(ts, trade, day_trades=None):
    """Відхилення щойно записаної угоди від ТС.

    day_trades — усі угоди того самого дня разом із цією: денний ліміт і
    кількість входів інакше не порахувати.
    """
    if not isinstance(ts, dict) or not ts or not isinstance(trade, dict):
        return []
    day = [x for x in (day_trades or [trade]) if not x.get("hidden")]
    found = [
        _asset(ts, trade),
        _model(ts, trade),
        _windows(ts, trade),
        _weekday(ts, trade),
        _risk(ts, trade),
        _rr(ts, trade),
        _day_loss(ts, trade, day),
        _max_trades(ts, trade, day),
    ]
    return [x for x in found if x][:MAX_ITEMS]


# ------------------------------------------------------- слова помічника ----
#
# Факти вже пораховані — моделі лишається сказати їх по-людськи. Своїх
# цифр вона не вигадує: усе, що можна назвати, є в рядках нижче.

FACTS = {
    "asset": "торгував %(got)s, хоча в системі записані інші інструменти: %(want)s",
    "model": "модель входу «%(got)s» не з тих, що описані в системі: %(want)s",
    "window": "вхід о %(got)s, а торгові вікна в системі: %(want)s",
    "weekday": "цей день у системі позначений як пропуск (%(want)s)",
    "risk": "ризик %(got)s замість оголошених %(want)s",
    "rr": "RR %(got)s нижчий за мінімальний %(want)s з системи",
    "dayloss": "день уже %(got)s при денному ліміті %(want)s",
    "maxtrades": "це %(got)s-та угода за день, а ліміт %(want)s",
}

SAY_RULES = (
    "Ти — помічник трейдера в його журналі. Нижче — факти про щойно записану "
    "угоду: чим вона розійшлася з його ж торговою системою. Перекажи їх однією-"
    "двома фразами, спокійно й по-дружньому, без списків, без моралі й без "
    "порад «наступного разу». Не додавай жодних чисел, яких немає у фактах. "
    "Це не докір: людина сама вирішує, що з цим робити."
)


def say(items, lang="uk"):
    """Одна жива фраза замість сухого переліку. Немає ключа до моделі —
    повертаємо порожньо, і сторінка покаже самі факти своїми словами."""
    if not items or not llm.enabled():
        return ""
    lines = []
    for it in items:
        tpl = FACTS.get(it.get("code"))
        if tpl:
            lines.append("- " + tpl % {"want": it.get("want", ""),
                                       "got": it.get("got", "")})
    if not lines:
        return ""
    order = LANG_ORDER.get(lang, LANG_ORDER["uk"])
    prompt = ("Факти:\n" + "\n".join(lines)
              + "\n\nВІДПОВІДЬ НАПИШИ %s. Іншою мовою не відповідай." % order)
    try:
        out = llm.ask(prompt, system=SAY_RULES, max_tokens=220, timeout=20,
                      temperature=0.4)
    except Exception:
        return ""
    return (out or "").strip()


def gaps(ts, trade):
    """Чому звірка мовчить, коли їй нема за що зачепитись.

    Мовчазний помічник виглядає зламаним. Якщо в ТС описані самі назви
    моделей, а решта полів порожня — сказати про це корисніше, ніж
    промовчати: людина думає, що звірка не працює, а насправді правил
    просто немає.
    """
    if not isinstance(ts, dict):
        return ""
    risk = ts.get("risk") or {}
    live = {
        "assets": bool([a for a in (ts.get("assets") or []) if str(a).strip()]),
        "models": bool([m for m in (ts.get("models") or [])
                        if isinstance(m, dict) and str(m.get("name") or "").strip()]),
        "windows": bool([w for w in (ts.get("windows") or [])
                         if isinstance(w, dict) and str(w.get("time") or "").strip()]),
        "days": bool(str(ts.get("days") or "").strip()),
        "per": _f(risk.get("per")) is not None,
        "rr": _f(risk.get("rr")) is not None,
        "day": _f(risk.get("day")) is not None,
        "maxtrades": _f(ts.get("maxtrades")) is not None,
    }
    if not any(live.values()):
        return "thin"
    # єдине описане правило — моделі входу, а в угоді це поле порожнє
    if live["models"] and not any(v for k, v in live.items() if k != "models") \
            and not str((trade or {}).get("entry_model") or "").strip():
        return "nomodel"
    return ""


def same_day(trades, trade):
    """Угоди того самого дня — включно з переданою."""
    dt = when(trade)
    if not dt:
        return [trade]
    out = []
    for t in trades:
        got = when(t)
        if got and got.date() == dt.date():
            out.append(t)
    return out or [trade]

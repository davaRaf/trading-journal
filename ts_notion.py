# -*- coding: utf-8 -*-
"""
Читання торгової стратегії з Notion за публічним посиланням.

Сторінка з ТС — не таблиця, а звичайний текст: заголовки, списки,
скріни між ними. Тому імпорт тут інший, ніж для угод: сторінку
розбираємо на рядки, з рядків витягуємо те, що зчитується однозначно
(таймфрейми, відсоток ризику, RR, вікна сесій, інструменти, моделі
входу), а решту лишаємо як є — людина побачить свій текст поруч і
допише руками.

Нічого не вигадуємо: якщо числа на сторінці немає, поле лишається
порожнім, а не заповнюється «типовим» значенням.
"""
import re

import notion_import
import notion_public


# ------------------------------------------------------------ словники ----

TFS = ["1W", "1D", "4H", "2H", "1H", "30M", "15M", "5M", "3M", "1M"]

# інструменти, які пишуть по-різному: ліворуч — як шукаємо, праворуч — як покажемо
ASSETS = [
    (r"\bUS\s?100\b|\bNAS\s?100\b|\bNASDAQ\b|\bNQ\b", "US100"),
    (r"\bUS\s?30\b|\bDOW\b|\bYM\b", "US30"),
    (r"\bUS\s?500\b|\bSPX\b|\bES\s?500\b|\bS&P\b", "US500"),
    (r"\bGER\s?40\b|\bDAX\b|\bDE\s?40\b", "GER40"),
    (r"\bXAU\s?/?\s?USD\b|\bGOLD\b|\bЗОЛОТ", "XAUUSD"),
    (r"\bEUR\s?/?\s?USD\b", "EURUSD"),
    (r"\bGBP\s?/?\s?USD\b", "GBPUSD"),
    (r"\bUSD\s?/?\s?JPY\b", "USDJPY"),
    (r"\bUSD\s?/?\s?CAD\b", "USDCAD"),
    (r"\bBTC\s?/?\s?USD\b|\bBITCOIN\b", "BTCUSD"),
    (r"\bJP\s?225\b|\bNIKKEI\b", "JP225"),
]

MODELS = [
    (r"\bcisd\b", "cisd"),
    (r"\bbos\b", "bos"),
    (r"\binvers", "inversion"),
    (r"\bfvg\b|імбаланс|имбаланс", "fvg"),
    (r"order\s?block|\bob\b|ордер\s?блок", "order block"),
    (r"liquidity\s?sweep|зняття\s?ліквідн|снятие\s?ликвидн", "liquidity sweep"),
]

SESSIONS = [
    (r"frankfurt|франкфурт", "Frankfurt"),
    (r"london|лондон", "London"),
    (r"new\s?york|нью[-\s]?йорк|\bny\b", "New York"),
    (r"power\s?hour", "Power Hour"),
    (r"asia|азі|ази", "Азія"),
]

TIME_RE = re.compile(r"\b([01]?\d|2[0-3])[:.]([0-5]\d)\s*[-–—]\s*([01]?\d|2[0-3])[:.]([0-5]\d)")
PCT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")
NUM_RE = re.compile(r"(\d+(?:[.,]\d+)?)")


def _f(s):
    try:
        return float(str(s).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _pct(line):
    m = PCT_RE.search(line)
    return (m.group(1).replace(",", ".") + "%") if m else ""


# --------------------------------------------------------------- розбір ----

def _tfs_in(line):
    up = line.upper()
    return [tf for tf in TFS if re.search(r"(?<![0-9A-Z])" + tf + r"(?![0-9A-Z])", up)]


def _hits(line, table):
    out = []
    for pat, name in table:
        if re.search(pat, line, re.I) and name not in out:
            out.append(name)
    return out


def parse(text):
    """З рядків сторінки збираємо чернетку стратегії."""
    lines = [l.strip(" \t•-—") for l in (text or "").split("\n")]
    lines = [l for l in lines if l]

    assets, models, tf_seen = [], [], []
    windows, manage, no_market, mind = [], [], [], []
    risk = {"per": "", "rr": "", "day": "", "week": ""}
    maxtrades = ""
    stop = target = bias = ""

    for line in lines:
        low = line.lower()

        for a in _hits(line, ASSETS):
            if a not in assets:
                assets.append(a)
        for m in _hits(line, MODELS):
            if m not in models:
                models.append(m)
        for tf in _tfs_in(line):
            if tf not in tf_seen:
                tf_seen.append(tf)

        # вікна сесій: назва сесії поруч із проміжком часу
        tm = TIME_RE.search(line)
        if tm:
            names = _hits(line, SESSIONS)
            windows.append({
                "name": names[0] if names else line[:28],
                "time": "%s:%s – %s:%s" % (tm.group(1).zfill(2), tm.group(2),
                                           tm.group(3).zfill(2), tm.group(4)),
                "note": "",
            })

        # ризик і ліміти — тільки там, де в рядку і слово, і відсоток
        if PCT_RE.search(line):
            if re.search(r"ризик|риск|risk", low) and not re.search(r"день|дня|day|тижд|недел|week", low):
                risk["per"] = risk["per"] or _pct(line)
            if re.search(r"(за |на )?день|дня|daily|day", low) and re.search(r"ліміт|лимит|limit|стоп|stop|втрат|потер", low):
                risk["day"] = risk["day"] or _pct(line)
            if re.search(r"тижд|недел|week", low):
                risk["week"] = risk["week"] or _pct(line)

        if re.search(r"\brr\b|р\/р|ризик[- ]прибут|соотнош", low):
            m = NUM_RE.search(line)
            if m and not risk["rr"]:
                v = _f(m.group(1))
                if v and 0.5 <= v <= 20:
                    risk["rr"] = m.group(1).replace(",", ".")

        if re.search(r"(не більше|не более|максимум|максимально|max).{0,20}(угод|сделок|trades?)", low):
            m = NUM_RE.search(line)
            if m and not maxtrades:
                maxtrades = m.group(1)

        if re.search(r"\bстоп\b|\bstop\b|\bsl\b", low) and not stop and len(line) < 160:
            stop = line
        if re.search(r"\bціл|\bцел|\btarget\b|\btp\b|тейк", low) and not target and len(line) < 160:
            target = line
        if re.search(r"біас|биас|\bbias\b|напрям", low) and not bias and len(line) < 160:
            bias = line

        if re.search(r"беззбит|безубыт|\bbe\b|\bбу\b|часткov|частичн|фікса|фикса|руками|вручну", low) \
                and len(line) < 200:
            manage.append(line)
        if re.search(r"не вход|не захо|пропуск|скіп|скип|\bskip\b", low) and len(line) < 200:
            no_market.append(line)
        if re.search(r"нагад|напомн|голов|пам'ятай|помни", low) and len(line) < 200:
            mind.append(line)

    # таймфрейми: старший — контекст, наймолодший — вхід
    order = {tf: i for i, tf in enumerate(TFS)}
    tf_seen.sort(key=lambda x: order.get(x, 99))
    tfs = [{"tf": tf, "role": "", "what": "", "shot": ""} for tf in tf_seen]

    return {
        "assets": assets,
        "tfs": tfs,
        "windows": windows[:8],
        "days": "", "news": "",
        "models": [{"name": m, "note": "", "shot": ""} for m in models],
        "bias": bias, "stop": {"v": stop, "shot": ""}, "target": {"v": target, "shot": ""},
        "maxtrades": maxtrades,
        "risk": risk, "riskCases": [],
        "manage": [{"k": "", "v": v, "shots": []} for v in manage[:6]],
        "no": {"market": no_market[:8], "time": [], "self": []},
        "mind": " ".join(mind[:3]),
        "check": [],
    }


def read(url, user_id, shots_dir):
    """Читає сторінку за посиланням і повертає чернетку стратегії.

    Картинки одразу перекладаємо до себе: посилання Notion живуть
    близько години, потім віддають 403.
    """
    pid, _ = notion_public.parse_link(url)
    text, images = notion_public.row_content(pid)

    shots = []
    for i, im in enumerate(images[:20]):
        try:
            base = "ts%d_%s" % (int(user_id), ("n%02d" % i) + format(abs(hash(im["url"])) % 0xFFFFFF, "x"))
            name = notion_import.download(im["url"], shots_dir, base)
            shots.append({"file": name, "caption": im.get("caption") or ""})
        except Exception:
            continue

    if not (text or "").strip() and not shots:
        raise ValueError("на сторінці не знайшли ні тексту, ні скрінів. "
                         "Дай посилання на сторінку з описом ТС, а не на таблицю")

    draft = parse(text)
    draft["source"] = "notion"
    draft["notion"] = {"url": url, "text": text[:20000], "shots": shots}

    # підписані скріни розкладаємо по таймфреймах: у Notion підпис
    # блока — це зазвичай і є таймфрейм
    by_tf = {}
    for s in shots:
        for tf in _tfs_in(s.get("caption") or ""):
            by_tf.setdefault(tf, s["file"])
    for row in draft["tfs"]:
        if row["tf"] in by_tf:
            row["shot"] = by_tf[row["tf"]]

    return draft

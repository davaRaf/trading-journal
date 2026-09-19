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
import ts_ai


# ------------------------------------------------------------ словники ----

TFS = ["1MN", "1W", "1D", "4H", "2H", "1H", "30M", "15M", "5M", "3M", "1M"]

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
    # «LO/NY» — так сесії скорочують у записах ICT
    (r"london|лондон|\blo\b", "London"),
    (r"new\s?york|нью[-\s]?йорк|\bny\b|\bnyse\b", "New York"),
    (r"power\s?hour", "Power Hour"),
    (r"asia|азі|ази", "Азія"),
]

# «9:00 – 12:00», а також «9:00am - 5:00pm» і «9:00am - 17:00pm»: am/pm після
# часу раніше рвали збіг, і вікно сесії не знаходилось зовсім
TIME_RE = re.compile(r"\b([01]?\d|2[0-3])[:.]([0-5]\d)\s*(am|pm)?\s*[-–—]\s*"
                     r"([01]?\d|2[0-3])[:.]([0-5]\d)\s*(am|pm)?", re.I)

# заголовок переліку сесій: під ним пунктами йдуть самі сесії, часто без часу
SESS_HEAD_RE = re.compile(r"trad\w*\s+sessions?|sessions?|торгов\w*\s+сес|сесі|сесси", re.I)


def _hm(h, m, ap):
    """Година з am/pm у 24-годинному записі. «17:00pm» лишаємо 17:00."""
    h = int(h)
    ap = (ap or "").lower()
    if ap == "pm" and h < 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    return "%02d:%s" % (h, m)
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

# Таймфрейм пишуть як заманеться: «1H» і «H1», «15M» і «M15», з пробілом і без,
# словами й кирилицею. Раніше розуміли тільки «1H» — а хто веде ТС у записі
# MetaTrader («H1», «M15»), той не отримував у розділах нічого.
_LETTER = "0-9A-Za-zА-Яа-яЇїІіЄєҐґ"          # що не має стояти впритул до запису
_TF_NUM_UNIT = re.compile(
    r"(?<![%s])(\d{1,3})\s*"
    r"(хвилин\w*|минут\w*|мин|min\w*|годин\w*|часов\w*|час|hour\w*|"
    r"денн\w*|дневн\w*|дн\w*|day\w*|тижн\w*|недел\w*|week\w*|[mмhгdдwт])"
    r"(?![%s])" % (_LETTER, _LETTER), re.I)
_TF_UNIT_NUM = re.compile(                    # запис MetaTrader: H1, M15, D1, W1
    r"(?<![%s])([HMDWhmdwМмГгЧчДдТтНн])\s*(\d{1,3})(?![%s])" % (_LETTER, _LETTER))
# кирилиця в тому ж записі: М15, Г1, Д1, Т1
_CYR_UNIT = {"М": "M", "Г": "H", "Ч": "H", "Д": "D", "Т": "W", "Н": "W"}
# «D/4h», «1h/15m», «М5/М3»: коли таймфрейми перелічують через скісну, одна
# з частин часто без числа — сама лише буква. «D» тут означає денний.
_TF_BARE = re.compile(
    r"(?<![%s])([DWHMdwhmДдТтГгЧчМм])\s*(?=/)"      # буква перед скісною
    r"|(?<=/)\s*([DWHMdwhmДдТтГгЧчМм])(?![%s])" % (_LETTER, _LETTER))
_TF_WORDS = [
    (r"\b(daily|денний|дневной|добов\w*)\b", "1D"),
    (r"\b(weekly|тижневий|недельный)\b", "1W"),
    (r"\b(hourly|часовик|годинний)\b", "1H"),
]


def _unit_letter(u):
    u = u.lower()
    if re.match(r"хвилин|минут|мин|min|[mм]$", u):
        return "M"
    if re.match(r"годин|часов|час|hour|[hг]$", u):
        return "H"
    if re.match(r"денн|дневн|дн|day|[dд]$", u):
        return "D"
    if re.match(r"тижн|недел|week|[wт]$", u):
        return "W"
    return ""


def _tf_split(line):
    """Таймфрейми рядка + те, що в ньому лишилось (це і є опис)."""
    tfs, cuts = [], []

    def add(tf, span):
        if tf not in tfs:
            tfs.append(tf)
        cuts.append(span)

    for m in _TF_NUM_UNIT.finditer(line):
        letter = _unit_letter(m.group(2))
        if letter:
            add("%d%s" % (int(m.group(1)), letter), m.span())
    for m in _TF_UNIT_NUM.finditer(line):
        letter = m.group(1).upper()
        letter = _CYR_UNIT.get(letter, letter)
        add("%d%s" % (int(m.group(2)), letter), m.span())
    month = re.search(r"місяц|месяц|month", line, re.I)
    for m in _TF_BARE.finditer(line):
        letter = (m.group(1) or m.group(2)).upper()
        letter = _CYR_UNIT.get(letter, letter)
        # «M/W» поруч зі словом «місяць» — це місяць і тиждень, а не хвилина
        add("1MN" if (letter == "M" and month) else "1" + letter, m.span())
    for pat, tf in _TF_WORDS:
        m = re.search(pat, line, re.I)
        if m:
            add(tf, m.span())

    rest = line
    for a, b in sorted(cuts, reverse=True):       # з кінця, щоб не з'їхали межі
        rest = rest[:a] + " " + rest[b:]
    # «/» теж прибираємо: від «D/4h» лишався смітник «/ -» на початку опису
    rest = re.sub(r"\s+", " ", rest).strip(" \t:—–-•,;/")
    return tfs, rest


def _tfs_in(line):
    return _tf_split(line)[0]


def _hits(line, table):
    out = []
    for pat, name in table:
        if re.search(pat, line, re.I) and name not in out:
            out.append(name)
    return out


def parse(text):
    """З рядків сторінки збираємо чернетку стратегії."""
    # запам'ятовуємо, чи був рядок пунктом списку: під таймфреймом майже
    # завжди йде перелік, і без цієї позначки в розділ потрапляв самий заголовок
    lines, is_item = [], []
    for raw in (text or "").split("\n"):
        s = raw.strip()
        if not s:
            continue
        is_item.append(bool(re.match(r"^[•·*\-—–]\s+|^\d+[.)]\s+", s)))
        lines.append(s.strip(" \t•·*-—–"))

    assets, models, tf_seen = [], [], []
    tf_text = {}                       # таймфрейм -> що по ньому написано
    tf_role_src = {}                   # вступний рядок таймфрейму — з нього беремо роль
    # заздалегідь знаємо, у якому рядку є таймфрейм: щоб під заголовком
    # «H1» забрати опис із наступних рядків і зупинитись на сусідньому ТФ
    split = [_tf_split(l) for l in lines]
    windows, manage, no_market, mind = [], [], [], []
    head = ""                          # останній рядок-заголовок (не пункт списку)
    risk = {"per": "", "rr": "", "day": "", "week": ""}
    maxtrades = ""
    stop = target = bias = ""

    for i, line in enumerate(lines):
        low = line.lower()

        for a in _hits(line, ASSETS):
            if a not in assets:
                assets.append(a)
        for m in _hits(line, MODELS):
            if m not in models:
                models.append(m)

        found, rest = split[i]
        if found:
            # «1h – На нім я знаходжу:» і нижче пункти — забираємо і те, й те
            items = []
            for j in range(i + 1, len(lines)):
                if split[j][0] or not is_item[j]:
                    break
                items.append(lines[j])
                if len(items) >= 12:
                    break

            note = rest
            if not note and not items:
                # рядок — самий лише заголовок, а опис нижче звичайним текстом
                tail = []
                for j in range(i + 1, min(i + 4, len(lines))):
                    if split[j][0]:
                        break
                    tail.append(lines[j])
                note = " ".join(tail)
            if items:
                note = (note + ":\n" if note else "") + "\n".join("• " + x for x in items)

            for tf in found:
                if tf not in tf_seen:
                    tf_seen.append(tf)
                if note and not tf_text.get(tf):
                    tf_text[tf] = note[:800]
                    # роль шукаємо у вступному рядку, а не в пунктах: там про
                    # неї і пишуть («(entry)», «контекст»), а список лише збиває
                    tf_role_src.setdefault(tf, rest)

        # вікна сесій: назва сесії поруч із проміжком часу. Коли час стоїть
        # окремим пунктом («OTT - Prague Time» і нижче «• 9:00am - 17:00pm»),
        # назвою стає заголовок над ним, а не сам час
        tm = TIME_RE.search(line)
        if tm:
            names = _hits(line, SESSIONS)
            label = re.sub(r"\s+", " ", TIME_RE.sub(" ", line)).strip(" \t:—–-•,;/")
            if not names and not label and head:
                label = head
            windows.append({
                "name": names[0] if names else (label or line)[:28],
                "time": "%s – %s" % (_hm(tm.group(1), tm.group(2), tm.group(3)),
                                     _hm(tm.group(4), tm.group(5), tm.group(6))),
                "note": "",
            })
        elif is_item[i] and SESS_HEAD_RE.search(head):
            # «Trade sessions» і пунктом «GER40/EUR/XAU - LO/NY (Asia/Frankfurt -
            # інформаційні)». Те, що в дужках, — пояснення, а не торгові сесії
            main = re.sub(r"\([^)]*\)", " ", line)
            for nm in _hits(main, SESSIONS):
                if not any(w["name"] == nm for w in windows):
                    windows.append({"name": nm, "time": "", "note": line[:200]})
        if not is_item[i]:
            head = line

        # ризик і ліміти — тільки там, де в рядку і слово, і відсоток
        if PCT_RE.search(line):
            if re.search(r"ризик|риск|risk", low) and not re.search(r"день|дня|day|тижд|недел|week", low):
                risk["per"] = risk["per"] or _pct(line)
            if re.search(r"(за |на )?день|дня|daily|day", low) and re.search(r"ліміт|лимит|limit|стоп|stop|втрат|потер|loss|збит|убыт", low):
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
    # роль беремо тільки якщо вона написана словами: вигадувати «контекст»
    # за старшинством таймфрейму не можна — у кожного своя система
    roles = [(r"контекст|структур|structure|напрям|тренд|bias", "контекст"),
             (r"вхід|вход|entry|тригер|триггер|trigger", "вхід"),
             (r"підтвердж|подтвержд|confirm", "підтвердження")]
    tfs = []
    for tf in tf_seen:
        note = tf_text.get(tf, "")
        role = ""
        for pat, name in roles:
            if re.search(pat, tf_role_src.get(tf, "") or note, re.I):
                role = name
                break
        # той самий поділ, що й після моделі: підпис над переліком — окремо
        role, note = ts_ai.split_lead(role, note)
        tfs.append({"tf": tf, "role": role, "what": note, "shot": ""})

    return {
        "assets": assets,
        "tfs": tfs,
        "windows": windows[:8],
        "days": "", "news": "",
        "models": [{"name": m, "note": "", "shots": []} for m in models],
        "bias": bias, "stop": {"v": stop, "shot": ""}, "target": {"v": target, "shot": ""},
        "maxtrades": maxtrades,
        "risk": risk, "riskCases": [],
        "manage": [{"k": "", "v": v, "shots": []} for v in manage[:6]],
        "no": {"market": no_market[:8], "time": [], "self": []},
        "mind": " ".join(mind[:3]),
        "check": [],
    }


# ------------------------------------------------------ читання сторінок ----
#
# Сторінка з ТС рідко буває одна. У Notion людина розкладає систему по
# розділах: контекст окремо, моделі входу окремо, ризик окремо. Тому читаємо
# скільки завгодно посилань і складаємо з них один опис — так модель бачить
# систему цілком, а не по шматку, і не вигадує зв'язки між розділами.

MAX_PAGES = 8        # більше сторінок ніхто не веде, а читати їх довго
AI_BUDGET = 18000    # стільки тексту доходить до моделі (ts_ai.parse ріже так само)
SHOTS_CAP = 24       # скрінів з усіх сторінок разом
SHOTS_MIN = 4        # але кожній сторінці лишаємо хоч кілька


def page_title(url):
    """Назва сторінки з самого посилання, без зайвого запиту до Notion.

    `notion.so/Moya-TS-1a2b3c...` -> «Moya TS». Потрібна лише щоб людина
    бачила в списку, що саме вона підтягнула. Не вийшло — лишаємо порожнє,
    покажемо саме посилання.
    """
    slug = re.sub(r"[?#].*$", "", str(url or "")).rstrip("/").rsplit("/", 1)[-1]
    slug = re.sub(r"-?[0-9a-f]{32}$", "", slug)          # ід сторінки в кінці
    slug = re.sub(r"-?[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$", "", slug)
    name = slug.replace("-", " ").strip()
    return name[:60] if name and not re.fullmatch(r"[0-9a-f]+", name) else ""


def _read_one(url, user_id, shots_dir, seq, shots_left):
    """Одна сторінка: текст і скріни, вже перекладені до себе.

    Картинки забираємо одразу: посилання Notion живуть близько години,
    потім віддають 403.
    """
    pid, _ = notion_public.parse_link(url)
    text, images = notion_public.row_content(pid)

    shots = []
    for i, im in enumerate(images[:max(SHOTS_MIN, shots_left)]):
        try:
            base = "ts%d_%s" % (int(user_id), ("n%d%02d" % (seq, i))
                                + format(abs(hash(im["url"])) % 0xFFFFFF, "x"))
            name = notion_import.download(im["url"], shots_dir, base)
            shots.append({"file": name, "caption": im.get("caption") or ""})
        except Exception:
            continue

    return {"url": url, "title": page_title(url),
            "text": (text or "").strip(), "shots": shots}


def read(urls, user_id, shots_dir):
    """Читає сторінки за посиланнями і повертає чернетку стратегії.

    Приймає і одне посилання рядком, і список: старі виклики (і записи в
    базі, де лежить одне `notion.url`) від цього не ламаються.

    Сторінка, яка не прочиталась, не роняє решту: її відкладаємо в `failed`,
    і людина побачить, з якою саме не склалось.
    """
    if isinstance(urls, str):
        urls = [urls]
    clean = []
    for u in (urls or []):
        u = str(u or "").strip()
        if u and u not in clean:
            clean.append(u)
    clean = clean[:MAX_PAGES]
    if not clean:
        raise ValueError("дай посилання на сторінку з описом ТС")

    pages, failed = [], []
    for seq, url in enumerate(clean):
        left = SHOTS_CAP - sum(len(p["shots"]) for p in pages)
        try:
            page = _read_one(url, user_id, shots_dir, seq, left)
        except Exception as e:
            failed.append({"url": url, "why": str(e)[:200] or "не прочиталась"})
            continue
        if not page["text"] and not page["shots"]:
            failed.append({"url": url, "why": "ні тексту, ні скрінів"})
            continue
        pages.append(page)

    if not pages:
        # Технічну причину назовні не несемо: людині від «KeyError» користі
        # немає. Кажемо, що перевірити, і які саме сторінки не далися.
        which = ", ".join(f["url"] for f in failed[:3])
        raise ValueError("не вдалось прочитати " + (which or "сторінку")
                         + ". Перевір, що сторінка відкрита за посиланням "
                           "(Share → Publish) і що це опис ТС, а не таблиця")

    # Ділимо бюджет тексту порівну: інакше перша ж довга сторінка з'їла б
    # усе місце, і моделі не дісталось би ні моделей входу, ні ризику.
    share = max(1500, AI_BUDGET // len(pages))
    parts, shots = [], []
    for p in pages:
        head = ("## " + p["title"] + "\n") if p["title"] else ""
        parts.append(head + p["text"][:share])
        shots.extend(p["shots"])
    joined = "\n\n".join(x for x in parts if x.strip())

    # спершу модель: вона читає сторінку цілком і бачить те, чого ключові
    # слова не ловлять. Розбір нижче лишається запасним — якщо ключа немає
    # або відповідь не склалась
    draft = ts_ai.parse(joined, shots, TFS, _tfs_in)
    if not draft:
        # Без моделі ключові слова ловлять лише шматки. Сторінки ж у людини
        # названі за розділами («Psychology», «Entry models», «Where SL and TP») —
        # тож розкладаємо їх за назвами, а слова лишаємо на решту.
        draft = parse(joined)
        route_pages(draft, pages)
    draft.setdefault("psy", [])
    draft["source"] = "notion"
    keep = max(2000, 20000 // len(pages))
    draft["notion"] = {
        # одне посилання лишаємо окремо: так запис читається старим кодом
        "url": pages[0]["url"],
        "urls": [p["url"] for p in pages],
        "pages": [{"url": p["url"], "title": p["title"],
                   "text": p["text"][:keep], "shots": p["shots"]} for p in pages],
        "text": joined[:20000],
        "shots": shots,
        "failed": failed,
    }

    # підписані скріни розкладаємо по таймфреймах: у Notion підпис
    # блока — це зазвичай і є таймфрейм
    by_tf = {}
    for sh in shots:
        for tf in _tfs_in(sh.get("caption") or ""):
            by_tf.setdefault(tf, sh["file"])
    for row in draft["tfs"]:
        if row["tf"] in by_tf:
            row["shot"] = by_tf[row["tf"]]

    attach_by_caption(draft, shots)
    return draft


# ------------------------------------------------ сторінки за назвами ----
#
# Людина веде ТС у Notion розділами, і назва сторінки прямо каже, що в ній:
# «Psychology», «Entry models», «Where SL and TP». Без моделі це найнадійніша
# підказка — надійніша за ключові слова, які ловлять просто згадки.

# Назви пишуть як завгодно й будь-якою мовою: «Psychology», «Психология»,
# «Mindset», «Стоп и тейк», «SL/TP», «Модели входа», «Setups»… Порядок
# важливий: «Stop & entry» — це про стоп, а не про вхід.
PAGE_ROUTES = [
    ("psy", r"psych|психо|mindset|mental|менталь|emotion|емоц|эмоц|дисципл|discipl|tilt|тильт|тільт"),
    ("stop", r"\bsl\b|\btp\b|\bstop|стоп|тейк|\btake|target|таргет|\bціл|\bцел|\bexit|выход|вихід|профит|профіт"),
    ("models", r"entry|entries|вход|вхід|модел|model|setup|сетап|trigger|тригер|execution"),
    ("context", r"context|контекст|bias|біас|биас|htf|narrative|наратив|таймфрейм|timeframe|synchron|синхрон|аналіз|анализ"),
    ("general", r"general|rules|правил|загальн|общ|основн|\bmain\b|risk|ризик|риск|session|сесі|сесси|money"),
]

# Назва нічого не підказала («Notes», «Мої нотатки») — дивимось, про що
# сам текст. Беремо тільки явного лідера: хибно впізнана сторінка гірша за
# сторінку, яка просто лягла в «Додатково».
CONTENT_HINTS = [
    ("psy", r"эмоц|емоц|тильт|тільт|\btilt|fomo|фомо|жадн|страх|\bfear|greed|revenge|отыгр|відігр|"
            r"дисциплин|дисциплін|психолог|терпен|терпін|спокі|спокой|азарт|самоконтрол"),
    ("stop", r"стоп|\bstop|\bsl\b|тейк|take.?profit|\btp\b|таргет|target"),
    ("models", r"модел|entry model|\bbos\b|choch|cisd|\bi?fvg\b|order.?block|\bsmt\b|свип|sweep"),
]


def _guess_kind(page):
    text = page.get("text") or ""
    score = sorted(((len(re.findall(pat, text, re.I)), k) for k, pat in CONTENT_HINTS), reverse=True)
    (top, kind), (second, _) = score[0], score[1]
    return kind if top >= 3 and top >= 2 * second else None
ITEM_RE = re.compile(r"^([•·*\-—–]|\d+[.)])\s+")
SKIP_HEAD_RE = re.compile(r"skip|скіп|скип|не вход|не захож|пропуск", re.I)
RISK_HEAD_RE = re.compile(r"risk|ризик|риск", re.I)
DRAFT_RE = re.compile(r"^(черновой|чорновий|draft)\b|^(примеры?|приклади?)\s+(из|з)\s+графік|^(примеры?|приклади?)\s+(из|з)\s+график", re.I)
MANAGE_HEAD_RE = re.compile(r"^be$|беззбит|безубыт|break\s?even|partial|частков|частичн|супровід|сопровожд|manage", re.I)


def _items(text):
    """Пункти сторінки: нумерований або маркований рядок починає пункт,
    звичайні рядки під ним — його продовження («1. Правило» і пояснення нижче)."""
    out = []
    for raw in (text or "").split("\n"):
        t = raw.strip()
        if not t:
            continue
        if ITEM_RE.match(t) or not out:
            out.append(ITEM_RE.sub("", t))
        else:
            out[-1] += "\n" + t
    return [x.strip() for x in out if x.strip()]


def _sections(text):
    """Сторінка по підзаголовках: [(заголовок, [пункти])]. Заголовок — рядок
    без маркера («Risk management:», «Skip:»), пункти — рядки з маркером."""
    out = [("", [])]
    for raw in (text or "").split("\n"):
        t = raw.strip()
        if not t:
            continue
        if ITEM_RE.match(t):
            out[-1][1].append(ITEM_RE.sub("", t))
        else:
            out.append((t.rstrip(":").strip(), []))
    return [(h, it) for h, it in out if h or it]


def _block(k, lines, shots=None):
    v = "\n".join("• " + x for x in lines) if len(lines) > 1 else "".join(lines)
    return {"k": k[:60], "v": v[:800], "shots": [s["file"] for s in (shots or [])][:8]}


def _route_models(draft, page):
    """«BOS - как модель для входа» і пункти під ним — модель BOS. Назви
    беремо з таких рядків і з підписів скрінів; те, що до першої моделі, —
    загальні правила входу, вони йдуть у «Додатково»."""
    names = []
    for src in [sh.get("caption") or "" for sh in page["shots"]] + page["text"].split("\n"):
        m = re.match(r"^[•·*\-—–\s]*(.+?)\s+[-–—]\s+.*(модел|model|вход|вхід|entry)", src.strip(), re.I)
        if m and m.group(1).strip() not in names:
            names.append(m.group(1).strip())
    if not names:
        return False
    models, cur, preface = [], None, []
    for line in _items(page["text"]):
        head = line.split("\n")[0]
        hit = next((n for n in names if re.match(r"^" + re.escape(n) + r"\s+[-–—]", head)), None)
        if hit:
            cur = {"name": hit, "note": [], "shots": []}
            models.append(cur)
        elif DRAFT_RE.search(head):
            continue
        elif cur:
            keep = [x for x in line.split("\n") if not DRAFT_RE.search(x.strip())]
            if keep:
                cur["note"].append("\n".join(keep))
        else:
            preface.append(line)
    for m in models:
        m["shots"] = [sh["file"] for sh in page["shots"]
                      if (sh.get("caption") or "").lower().startswith(m["name"].lower())][:8]
        m["note"] = "\n".join("• " + x for x in m["note"])[:800]
    draft["models"] = models
    if preface:
        draft.setdefault("extra", []).append(_block(page["title"] or "Entry", preface))
    return True


def _route_context(draft, page):
    """Таймфрейми — тільки зі сторінки контексту: інакше в список лізли
    всі ТФ, згадані будь-де. Решта сторінки (синхронізація тощо) — окремим
    блоком у «Додатково»."""
    tfs = parse(page["text"])["tfs"]
    if tfs:
        draft["tfs"] = tfs
    rest, seen_tf, on = [], False, False
    for h, it in _sections(page["text"]):
        if _tfs_in(h):
            seen_tf = True
        elif seen_tf and h and not h.endswith("?"):
            # перший підзаголовок без таймфрейму після блоку ТФ — далі «інше»
            on = True
        if on:
            rest += ([h] if h and not DRAFT_RE.search(h) else []) + it
    rest = [x for x in rest if not DRAFT_RE.search(x)]
    if rest:
        tf_caps = [sh for sh in page["shots"] if not _tfs_in(sh.get("caption") or "")]
        draft.setdefault("extra", []).append(_block(page["title"] or "Context", rest, tf_caps))


def _route_stop(draft, page):
    """Сторінка про стоп і тейк: рядки — стоп, підписи скрінів — ціль."""
    lines = _items(page["text"])
    caps = [sh for sh in page["shots"] if (sh.get("caption") or "").strip()]
    stop = [x for x in lines if re.search(r"стоп|stop|\bsl\b", x, re.I)] or lines
    tgt = [sh["caption"].strip() for sh in caps if re.search(r"тейк|take|\btp\b|ціл|цел|target", sh["caption"], re.I)]
    tgt += [x for x in lines if re.search(r"тейк|take|\btp\b|ціл|цел|target", x, re.I) and x not in stop]
    if stop:
        draft["stop"] = {"v": "\n".join("• " + x for x in stop)[:600] if len(stop) > 1 else stop[0][:600],
                         "shot": page["shots"][0]["file"] if page["shots"] else ""}
    if tgt:
        draft["target"] = {"v": "\n".join("• " + x for x in tgt)[:600] if len(tgt) > 1 else tgt[0][:600],
                           "shot": page["shots"][1]["file"] if len(page["shots"]) > 1 else ""}


def _route_general(draft, page):
    """Загальні правила по підзаголовках: сесії й ризик уже взяв розбір за
    словами, «Skip» — це «коли не входжу», решта — окремі блоки."""
    no = draft.setdefault("no", {"market": [], "time": [], "self": []})
    for h, it in _sections(page["text"]):
        if not it:
            continue
        if SESS_HEAD_RE.search(h) or RISK_HEAD_RE.search(h) or any(TIME_RE.search(x) for x in it):
            continue
        if SKIP_HEAD_RE.search(h):
            for x in it:
                if x not in no["market"]:
                    no["market"].append(x[:300])
            continue
        if MANAGE_HEAD_RE.search(h):
            b = _block(h, it)
            draft.setdefault("manage", []).append({"k": b["k"], "v": b["v"][:500], "shots": []})
            continue
        draft.setdefault("extra", []).append(_block(h or page["title"] or "General", it))


def route_pages(draft, pages):
    """Розкладає сторінки за їхніми назвами. Сторінку, чию назву не впізнали,
    кладемо в «Додатково» цілою — під її ж назвою, зі скрінами."""
    draft.setdefault("extra", [])
    draft.setdefault("psy", [])
    seen = set()      # розділи, вже взяті зі сторінки: друга така сторінка додається, а не затирає
    for page in pages:
        title = page.get("title") or ""
        kind = (next((k for k, pat in PAGE_ROUTES if re.search(pat, title, re.I)), None)
                or _guess_kind(page))
        before = list(draft.get(kind) or []) if kind in seen else []
        if kind == "psy":
            rules = [{"k": "", "v": x[:500]} for x in _items(page["text"]) if not DRAFT_RE.search(x)]
            draft["psy"] = (before + rules)[:12]
            seen.add("psy")
        elif kind == "models" and _route_models(draft, page):
            draft["models"] = (before + draft["models"])[:12]
            seen.add("models")
        elif kind == "stop":
            _route_stop(draft, page)
        elif kind == "context":
            _route_context(draft, page)
        elif kind == "general":
            _route_general(draft, page)
        else:
            lines = [x for x in _items(page["text"]) if not DRAFT_RE.search(x)]
            if lines or page["shots"]:
                draft["extra"].append(_block(title or "Notion", lines, page["shots"]))
    draft["extra"] = draft["extra"][:12]
    taken = " ".join(b["v"] for b in draft["extra"] + draft.get("manage", []))
    no = draft.get("no") or {}
    no["market"] = [x for x in no.get("market", [])
                    if not x.rstrip().endswith(":") and x not in taken][:10]
    return draft


# ------------------------------------------------------- скріни по підписах --

def _words(s):
    """Слова підпису в нижньому регістрі — щоб «Order flow» і «ORDER FLOW»
    були тим самим, а «BOS» не ловилось усередині «BOSS»."""
    return [w for w in re.split(r"[^0-9a-zA-Zа-яА-Яа-яїієґЇІЄҐ]+", (s or "").lower()) if w]


def attach_by_caption(draft, shots):
    """Скрін, підписаний назвою правила, ставимо до цього правила.

    У Notion картинку кладуть під заголовком («Order flow», «BOS»), і цей
    заголовок стає підписом блока. Модель ставить номери сама, але не завжди
    влучає — тоді картинка осідала б унизу сторінки, хоча місце для неї видно
    з підпису. Чіпаємо лише порожні блоки: те, що модель уже розклала, не
    чіпаємо.
    """
    taken = {row.get("shot") for row in draft.get("tfs") or [] if row.get("shot")}
    for key in ("models", "manage", "extra"):
        for row in draft.get(key) or []:
            taken.update(row.get("shots") or [])
    for key in ("stop", "target"):
        got = (draft.get(key) or {}).get("shot")
        if got:
            taken.add(got)

    for key, title in (("models", "name"), ("manage", "k"), ("extra", "k")):
        for row in draft.get(key) or []:
            if row.get("shots"):
                continue
            name = _words(row.get(title))
            if not name:
                continue
            picked = []
            for sh in shots:
                if sh["file"] in taken:
                    continue
                cap = _words(sh.get("caption"))
                # усі слова назви стоять у підписі окремими словами
                if cap and all(w in cap for w in name):
                    picked.append(sh["file"])
                    taken.add(sh["file"])
                    if len(picked) >= 8:
                        break
            if picked:
                row["shots"] = picked

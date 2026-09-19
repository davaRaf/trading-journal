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
import difflib
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
    text, images = notion_public.row_content(pid, indent=True)

    shots = []
    for i, im in enumerate(images[:max(SHOTS_MIN, shots_left)]):
        try:
            base = "ts%d_%s" % (int(user_id), ("n%d%02d" % (seq, i))
                                + format(abs(hash(im["url"])) % 0xFFFFFF, "x"))
            name = notion_import.download(im["url"], shots_dir, base)
            shots.append({"file": name, "caption": im.get("caption") or "", "at": im.get("at")})
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
    draft.setdefault("ctx", [])
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
    # Лише ті скріни, що ще нікуди не лягли, і лише в порожні рядки: скрін,
    # який стоїть у блоці «Синхронізація» з підписом «1h лонг OF», — приклад
    # синхронізації, а не картинка таймфрейму 1H.
    placed = set(_strings(draft, []))
    by_tf = {}
    for sh in shots:
        if sh["file"] in placed:
            continue
        for tf in _tfs_in(sh.get("caption") or ""):
            by_tf.setdefault(tf, sh["file"])
    for row in draft["tfs"]:
        if row.get("shot"):
            continue
        hit = next((by_tf[t] for t in str(row["tf"]).split("/") if t in by_tf), "")
        if hit and hit not in placed:
            row["shot"] = hit
            placed.add(hit)

    attach_by_caption(draft, shots)
    # і наостанок — усе, що не лягло в жоден розділ, у «Додатково»
    _rescue(draft, pages)
    return draft


# ------------------------------------------------ сторінки за назвами ----
#
# Людина веде ТС у Notion розділами, і назва сторінки каже, що в ній. Але
# кожен називає по-своєму: «Psychology», «Моя психологія», «🧠 Mindset»,
# «Где стоп, где тейк», «SL/TP», «Как я вхожу», «Сетапы», «Коли не торгую»,
# «Чек-лист перед угодою» — і з помилками теж («Психалогия»).
#
# Тому не шукаємо одне точне слово, а рахуємо бали: назву зводимо до простих
# слів (регістр, емодзі, дефіси й скісні геть), і кожен корінь зі словника
# розділу, з якого починається слово назви, дає бали. Словосполучення («не
# входжу», «перед входом») важать більше за окреме слово — інакше «Коли не
# входжу» пішло б у моделі входу через «вход». Схоже слово з помилкою дає
# менше. Нічия — вирішує текст сторінки, далі порядок розділів.

# корінь -> з нього має починатись слово назви; "=sl" — тільки саме слово
PAGE_VOCAB = {
    "psy": ["психолог", "психо", "психік", "психик", "psych", "mindset", "mind", "мышлен",
            "мислен", "менталь", "mental", "emotion", "эмоц", "емоц", "дисципл", "discipl",
            "tilt", "тильт", "тільт", "fomo", "фомо", "страх", "fear", "greed", "жадн",
            "самоконтрол", "self control", "характер", "настро", "mood", "стресс", "стрес",
            "stress", "терпен", "терпін", "терпел", "мотивац", "motivat", "inner game",
            "внутрен", "внутріш", "состояни", "мой стан", "мій стан"],
    "nogo": ["не вход", "не вхож", "не входж", "не торг", "не захож", "не заход", "skip",
             "скип", "скіп", "no trade", "dont trade", "don t trade", "do not trade",
             "not trade", "avoid", "избега", "уника", "заборон", "запрет", "пропуск",
             "no go", "nogo", "red flag", "стоп фактор", "стоп факт", "когда нельзя",
             "коли не можна", "не беру", "не открыв", "не відкрива"],
    "check": ["чек лист", "чеклист", "checklist", "check list", "перед вход", "перед угод",
              "перед сделк", "перед входом", "before entry", "before trade", "pre trade",
              "pretrade", "=чек", "=check"],
    "stop": ["стоп", "stop", "=sl", "=tp", "take", "тейк", "тэйк", "profit", "профит", "профіт",
             "target", "таргет", "=цель", "=цели", "=ціль", "=цілі", "exit", "выход", "вихід",
             "фиксац", "фіксац", "фиксир", "фіксу", "прибыл", "прибут", "invalid", "инвалид", "інвалід", "закрыт", "закрит"],
    "manage": ["сопровожд", "супровід", "супровод", "trade manag", "position manag",
               "управлен сделк", "управлін угод", "ведение сделк", "ведення угод", "безубыт",
               "беззбит", "breakeven", "break even", "=be", "partial", "частичн", "частков",
               "трейлинг", "трейлінг", "trailing", "частичн фикс", "частков фікс",
               "partial close", "partial take", "trailing stop", "перенос стоп",
               "перенос в безуб", "move stop", "move sl"],
    "models": ["entry", "entri", "вход", "вхід", "входж", "вхож", "модел", "model", "setup",
               "сетап", "сэтап", "trigger", "тригер", "триггер", "execution", "исполнен",
               "точка вход", "точки вход", "=poi", "confirm", "подтвержд", "підтвердж",
               "паттерн", "патерн", "pattern", "=bos", "=cisd", "=fvg", "=ifvg", "=choch",
               "=smt", "order block", "ордер блок"],
    "context": ["context", "контекст", "bias", "биас", "біас", "=htf", "=mtf", "narrativ",
                "наратив", "нарратив", "таймфрейм", "timeframe", "time frame", "=tf", "=тф",
                "synchron", "синхрон", "аналіз", "анализ", "analys", "структур", "structure",
                "тренд", "trend", "направлен", "напрям", "direction", "top down", "premium",
                "discount", "мульти", "multi time"],
    "general": ["general", "rule", "правил", "загальн", "общ", "основн", "=main", "базов",
                "basic", "план", "plan", "risk", "ризик", "риск", "money", "мани", "=mm", "=rm",
                "менеджмент", "session", "сесі", "сесс", "kill zone", "killzone", "килзон",
                "время торг", "час торг", "schedule", "расписан", "розклад", "ліміт", "лимит",
                "limit", "pair", "пары", "пари", "инструмент", "інструмент", "instrument", "актив", "asset",
                "correlat", "кореляц", "корреляц"],
}
# при нічиї: вужчий розділ важливіший за загальний («Правила входу» — це вхід)
KIND_ORDER = ["psy", "nogo", "check", "stop", "manage", "models", "context", "general"]

# Про що сам текст — для нічиєї і для сторінок, чия назва нічого не каже
# («Notes», «Мої нотатки»). Без назви беремо тільки явного лідера: хибно
# впізнана сторінка гірша за сторінку, яка просто лягла в «Додатково».
CONTENT_HINTS = [
    ("psy", r"эмоц|емоц|тильт|тільт|\btilt|fomo|фомо|жадн|страх|\bfear|greed|revenge|отыгр|відігр|"
            r"дисциплин|дисциплін|психолог|терпен|терпін|спокі|спокой|азарт|самоконтрол"),
    ("stop", r"стоп|\bstop|\bsl\b|тейк|take.?profit|\btp\b|таргет|target"),
    ("models", r"модел|entry model|\bbos\b|choch|cisd|\bi?fvg\b|order.?block|\bsmt\b|свип|sweep"),
]


def _norm(s):
    """«🧠 Моя Психология!», «SL/TP-1», «Stop-loss & Take-profit» → прості слова."""
    s = (s or "").lower().replace("ё", "е").replace("’", "").replace("'", "")
    s = re.sub(r"(?<=[^\W\d_])(?=\d)|(?<=\d)(?=[^\W\d_])", " ", s)   # tp1 → tp 1
    return " ".join(re.findall(r"[^\W_]+", s))


def _stem_re(st):
    """Корінь → шаблон на початок слова. У словосполученні кожне слово —
    теж початок: «частичн фикс» ловить «Частичная фиксация»."""
    exact = st.startswith("=")
    parts = st.lstrip("=").split()
    body = " ".join(re.escape(w) + (r"\w*" if len(w) > 2 else "") for w in parts[:-1])
    body = (body + " " if body else "") + re.escape(parts[-1])
    return r"(?:^| )" + body + (r"(?= |$)" if exact else r"\w*")


def _title_scores(title):
    t = _norm(title)
    score, used = {}, set()
    for kind, stems in PAGE_VOCAB.items():
        for st in stems:
            m = re.search(_stem_re(st), t)
            if m:
                score[kind] = score.get(kind, 0) + (3 if " " in st.strip("=") else 2)
                used.update(m.group(0).split())
    # помилка в слові («психалогия», «psyhology») — тільки для слів, які не
    # впізнались точно: інакше «фиксация» ще й «схожа» на укр. «фіксац» і
    # отримує подвійну вагу
    for w in t.split():
        if w in used or len(w) < 5:
            continue
        for kind, stems in PAGE_VOCAB.items():
            if any(not st.startswith("=") and " " not in st and len(st) >= 5 and len(w) >= len(st)
                   and difflib.SequenceMatcher(None, w[:len(st)], st).ratio() >= .8 for st in stems):
                score[kind] = score.get(kind, 0) + 1
    return score


def _content_scores(text):
    return {k: len(re.findall(pat, text or "", re.I)) for k, pat in CONTENT_HINTS}


def page_kind(title, text=""):
    """Розділ ТС для сторінки: psy, nogo, check, stop, manage, models, context,
    general — або None, якщо ні назва, ні текст певної відповіді не дають."""
    ts = _title_scores(title)
    cs = _content_scores(text)
    if ts:
        best = max(ts.values())
        tied = [k for k in KIND_ORDER if ts.get(k) == best]
        if len(tied) > 1 and any(cs.get(k) for k in tied):
            return max(tied, key=lambda k: (cs.get(k, 0), -KIND_ORDER.index(k)))
        return tied[0]
    ranked = sorted(((v, k) for k, v in cs.items()), reverse=True)
    (top, kind), (second, _) = ranked[0], ranked[1]
    return kind if top >= 3 and top >= 2 * second else None


ITEM_RE = re.compile(r"^([•·*\-—–]|\d+[.)])\s+")
SKIP_HEAD_RE = re.compile(r"skip|скіп|скип|не вход|не захож|пропуск", re.I)
RISK_HEAD_RE = re.compile(r"risk|ризик|риск", re.I)
DRAFT_RE = re.compile(r"^(черновой|чорновий|draft)\b|^(примеры?|приклади?)\s+(из|з)\s+графік|^(примеры?|приклади?)\s+(из|з)\s+график", re.I)
MANAGE_HEAD_RE = re.compile(r"^be$|беззбит|безубыт|break\s?even|partial|частков|частичн|супровід|сопровожд|manage", re.I)

# Скільки тексту лишаємо в одному полі. Раніше тут було 800 символів і 12
# блоків — і довгий розділ правил просто обрізався посередині.
TEXT_CAP = 6000
LIST_CAP = 60


# ------------------------------------------------ сторінка по рядках ----
#
# Головне правило імпорту: зі сторінки нічого не губиться. Тому кожен
# обробник позначає рядки, які забрав (page["_used"]), а в кінці _rescue()
# кладе в «Додатково» все, що не забрав ніхто, — під заголовком свого блока
# і зі скрінами, які стояли поруч.

def _lines(page):
    """Рядки сторінки: глибина (два пробіли на рівень), чи це пункт списку,
    текст без маркера і номер рядка. «Черновой пример:» — підпис над
    картинкою, а не правило, його пропускаємо."""
    out = []
    for i, raw in enumerate((page.get("text") or "").split("\n")):
        t = raw.strip()
        if not t:
            continue
        body = ITEM_RE.sub("", t)
        if DRAFT_RE.search(body):
            continue
        out.append({"d": (len(raw) - len(raw.lstrip(" "))) // 2,
                    "item": bool(ITEM_RE.match(t)), "t": body, "i": i})
    return out


def _use(page, rows):
    page.setdefault("_used", set()).update(r["i"] for r in rows)


def _tree(rows):
    """Рядки → текст деревом, як у Notion: «• пункт / ◦ підпункт / ▸ ще глибше»."""
    if not rows:
        return ""
    if len(rows) == 1:
        return rows[0]["t"]
    base = min(r["d"] for r in rows)
    out = []
    for r in rows:
        lvl = r["d"] - base
        mark = ("•◦▸"[min(lvl, 2)] + " ") if (r["item"] or lvl) else ""
        out.append("   " * lvl + mark + r["t"])
    return "\n".join(out)


def _is_head(r, nxt):
    """Підзаголовок: рядок не зі списку, що закінчується двокрапкою чи
    питанням, або короткий («Trade sessions», «General») і під ним пункти.
    Довгий абзац після пункту — це продовження правила, а не заголовок."""
    t = r["t"].strip()
    if r["item"]:
        return False
    if t.endswith(":") or t.endswith("?"):
        return True
    below = nxt is not None and (nxt["d"] > r["d"] or nxt["item"])
    return below and (len(t) <= 40 or nxt["d"] > r["d"])


def _groups(page, rows=None):
    """Сторінка по блоках: підзаголовок верхнього рівня і все під ним.
    До кожного блока йдуть скріни, що стоять у ньому на сторінці."""
    rows = _lines(page) if rows is None else rows
    base = min((r["d"] for r in rows), default=0)
    out = [{"head": None, "rows": [], "from": -1, "shots": []}]
    for n, r in enumerate(rows):
        if r["d"] == base and _is_head(r, rows[n + 1] if n + 1 < len(rows) else None):
            out.append({"head": r, "rows": [], "from": r["i"], "shots": []})
        else:
            out[-1]["rows"].append(r)
    out = [g for g in out if g["head"] or g["rows"]]
    for sh in page.get("shots") or []:
        at = sh.get("at")
        if not out:
            continue
        if at is None:                   # місце невідоме (старий запис) — до першого блока
            out[0]["shots"].append(sh)
            continue
        g = [g for g in out if g["from"] < at]
        (g[-1] if g else out[0])["shots"].append(sh)
    return out


def _head_text(g):
    return g["head"]["t"].rstrip(":").strip() if g["head"] else ""


def _units(rows):
    """Пункти верхнього рівня з усім, що під ними: «1. Правило» + пояснення
    рядком нижче + підпункти — це одне правило, а не три."""
    if not rows:
        return []
    base = min(r["d"] for r in rows)
    has_items = any(r["item"] and r["d"] == base for r in rows)
    units = []
    for r in rows:
        top = r["d"] == base and (r["item"] or not has_items or not units)
        if top:
            units.append([r])
        else:
            units[-1].append(r)
    out = []
    for u in units:
        first, rest = u[0], u[1:]
        # продовження без відступу — просто наступний абзац того ж правила
        text = first["t"] + "".join(
            ("\n" + x["t"]) if x["d"] == first["d"] else "" for x in rest if x["d"] == first["d"])
        deeper = [x for x in rest if x["d"] > first["d"]]
        if deeper:
            text += "\n" + _tree(deeper)
        out.append((u, text))
    return out


def _block(k, text, shots=None):
    return {"k": (k or "")[:80], "v": (text or "")[:TEXT_CAP],
            "shots": [s["file"] for s in (shots or [])][:12]}


def _cards(k, rows, shots):
    """Блок, де в кожного пункту верхнього рівня свої скріни («Синхронізація»
    зі своїми прикладами, «Розсинхронізація» зі своїми), — окремими картками:
    так картинка стоїть біля свого пункту, а не купою під усім блоком.
    Інакше — одна картка на весь блок."""
    units = _units(rows)
    if len(units) > 1 and shots and all(sh.get("at") is not None for sh in shots):
        starts = [u[0]["i"] for u, _ in units]
        own, lead = [[] for _ in units], []
        for sh in shots:
            n = max((j for j, s in enumerate(starts) if s < sh["at"]), default=None)
            (own[n] if n is not None else lead).append(sh)
        if sum(1 for o in own if o) >= 2:
            own[0] = lead + own[0]
            return [_block(u[0]["t"].rstrip(":").strip(), _tree(u[1:]), own[j])
                    for j, (u, _) in enumerate(units)]
    return [_block(k, _tree(rows), shots)]


def _tf_head(r):
    """«D/4h - При открытии дня…» → (["1D", "4H"], «При открытии дня…»).
    Таймфрейми беремо лише з початку рядка: «вспомогательные после 1h» у
    тексті — це слова, а не ще один таймфрейм."""
    m = re.match(r"^(.{1,24}?)\s*(?:[-–—:]\s+|$)(.*)$", r["t"])
    if not m:
        return [], ""
    tfs = _tfs_in(m.group(1))
    if not tfs:
        return [], ""
    if re.search(r"місяц|месяц|month", r["t"], re.I):
        tfs = ["1MN" if t == "1M" else t for t in tfs]
    # старший першим, як їх і читають: «1D/4H», а не «4H/1D»
    tfs.sort(key=lambda t: TFS.index(t) if t in TFS else len(TFS))
    return tfs, m.group(2).strip()


# ------------------------------------------------------- обробники ----

def _route_models(draft, page):
    """«BOS - как модель для входа» і все під ним — модель BOS. Назви беремо
    з таких рядків і з підписів скрінів. Пункти до першої моделі — загальні
    правила входу (modelsNote). Скріни — ті, що стоять під моделлю."""
    names = []
    for src in [sh.get("caption") or "" for sh in page["shots"]] + page["text"].split("\n"):
        m = re.match(r"^[•·*\-—–\s]*(.+?)\s+[-–—]\s+.*(модел|model|вход|вхід|entry)", src.strip(), re.I)
        if m and m.group(1).strip() not in names:
            names.append(m.group(1).strip())
    if not names:
        return False
    rows = _lines(page)
    models, cur, preface, spans = [], None, [], []
    base = None
    for r in rows:
        hit = next((n for n in names if re.match(r"^" + re.escape(n) + r"\s+[-–—]", r["t"])), None)
        if hit:
            cur, base = {"name": hit, "note": [], "shots": []}, r["d"]
            models.append(cur)
            spans.append([r["i"], None])
        elif cur is not None and (r["d"] > base or not r["item"]):
            cur["note"].append(r)
        else:
            if cur is not None:
                spans[-1][1] = r["i"]
            cur = None
            preface.append(r)
    _use(page, rows)
    raw = page["text"].split("\n")
    out = []
    for n, m in enumerate(models):
        lo, hi = spans[n][0], spans[n][1] if spans[n][1] is not None else 10 ** 9
        if n + 1 < len(models):
            hi = min(hi, spans[n + 1][0])
        by_place = [sh["file"] for sh in page["shots"] if sh.get("at") is not None and lo < sh["at"] <= hi]
        by_cap = [sh["file"] for sh in page["shots"]
                  if (sh.get("caption") or "").lower().startswith(m["name"].lower())]
        shots = by_place or by_cap
        rows_m = m["note"]
        # Вкладений випадок зі своїми прикладами («коли перед зламом є
        # імбаланс — чекаю закриття, інверсія FVG») — окрема модель: інакше
        # його скріни змішувались зі скрінами самої моделі.
        cases = []
        for p, end in (_model_cases(raw, lo, hi, rows_m) if by_place else []):
            own = [sh["file"] for sh in page["shots"]
                   if sh.get("at") is not None and p["i"] < sh["at"] <= end]
            if not own:
                continue
            kids = [r for r in rows_m if p["i"] < r["i"] < end]
            rows_m = [r for r in rows_m if r not in kids]
            shots = [f for f in shots if f not in own]
            head = p["t"].rstrip(":").strip()
            cut = head.find(",")
            short = head[:cut] if cut >= 12 else head
            note = _tree([dict(r, item=True) for r in kids]) if len(kids) > 1 else \
                ("• " + kids[0]["t"] if kids else "")
            if short != head:
                note = head + ("\n" + note if note else "")
            cases.append({"name": (m["name"] + " · " + short)[:80], "note": note[:TEXT_CAP],
                          "shots": own[:12]})
        m["shots"] = shots[:12]
        m["note"] = (_tree(rows_m) if len(rows_m) > 1 else ("• " + rows_m[0]["t"] if rows_m else ""))[:TEXT_CAP]
        out += [m] + cases
    draft["models"] = out
    if preface:
        prev = draft.get("modelsNote") or ""
        note = _tree(preface) if len(preface) > 1 else "• " + preface[0]["t"]
        draft["modelsNote"] = (((prev + "\n") if prev else "") + note)[:TEXT_CAP]
    return True


def _model_cases(raw, lo, hi, rows):
    """Пункти в описі моделі, під якими стоять свої приклади («Черновой
    пример:», «Пример из графика:»). Повертає (пункт, де його гілка
    закінчується) — усе між ними, разом зі скрінами, і є цей випадок."""
    def depth(j):
        return (len(raw[j]) - len(raw[j].lstrip(" "))) // 2

    def draft_line(j):
        return bool(raw[j].strip()) and bool(DRAFT_RE.search(ITEM_RE.sub("", raw[j].strip())))

    ids = {r["i"]: r for r in rows}
    found = []
    for j in range(lo + 1, min(hi, len(raw))):
        if not draft_line(j):
            continue
        k = j - 1
        while k > lo and (not raw[k].strip() or draft_line(k) or depth(k) >= depth(j)):
            k -= 1
        if k in ids and all(f[0]["i"] != k for f in found):
            end = next((x for x in range(k + 1, len(raw))
                        if raw[x].strip() and depth(x) <= depth(k)), len(raw))
            found.append((ids[k], end))
    return found


def _route_context(draft, page):
    """Блок «ТФ - навіщо дивлюсь» + пункти під ним — один рядок таймфреймів,
    як у людини на сторінці («D/4h» — одна картка, а не дві однакові).
    Блоки без таймфрейму (синхронізація тощо) — теж у вкладку «Контекст»,
    окремими картками (ctx): це частина контексту, а не «Додатково»."""
    groups = _groups(page)
    rows_out = []
    ctx = draft.setdefault("ctx", [])
    for g in groups:
        tfs, role = _tf_head(g["head"]) if g["head"] else ([], "")
        if tfs:
            rows_out.append({"tf": "/".join(tfs), "role": role[:300], "what": _tree(g["rows"])[:TEXT_CAP],
                             "shot": g["shots"][0]["file"] if g["shots"] else ""})
            _use(page, [g["head"]] + g["rows"])
            if len(g["shots"]) > 1:
                ctx.append(_block("/".join(tfs), "", g["shots"][1:]))
    if not rows_out:
        return False
    prev = draft.get("tfs") if draft.get("_ctx") else []
    draft["tfs"] = (prev or []) + rows_out
    draft["_ctx"] = True
    for g in groups:
        if g["head"] and _tf_head(g["head"])[0]:
            continue
        if g["head"] and not g["rows"] and g["head"]["t"].rstrip().endswith("?"):
            _use(page, [g["head"]])          # «Как я определяю контекст?» — лише заголовок
            continue
        if g["rows"] or g["shots"]:
            k = _head_text(g) or page["title"] or "Context"
            ctx.extend(_cards(k, g["rows"], g["shots"]))
            _use(page, ([g["head"]] if g["head"] else []) + g["rows"])
    draft["ctx"] = ctx[:LIST_CAP]
    return True


def _route_stop(draft, page):
    """Сторінка про стоп і тейк. Рядки про тейк / ціль — у «ціль», решта —
    у «стоп» (нічого не відкидаємо). Скріни: перший — до стопу, другий — до цілі."""
    rows = _lines(page)
    tgt_re = r"тейк|take|\btp\b|ціл|цел|target|таргет"
    tgt = [r for r in rows if re.search(tgt_re, r["t"], re.I) and not re.search(r"стоп|stop|\bsl\b", r["t"], re.I)]
    stop = [r for r in rows if r not in tgt]
    if stop:
        draft["stop"] = {"v": _tree(stop)[:TEXT_CAP], "shot": page["shots"][0]["file"] if page["shots"] else ""}
    if tgt:
        draft["target"] = {"v": _tree([dict(r, d=0, item=True) for r in tgt])[:TEXT_CAP],
                           "shot": page["shots"][1]["file"] if len(page["shots"]) > 1 else ""}
    _use(page, rows)


def _risk_rows(draft, g, page):
    """Ризик уже розібрали в цифри (risk.per, rr, day). Рядок, де крім цифри
    є ще щось («2% (SL per day - 2)»), — окремим випадком, щоб не зникло."""
    vals = {str(v).strip().lower() for v in list((draft.get("risk") or {}).values()) + [draft.get("maxtrades")] if v}
    for r in g["rows"]:
        m = re.match(r"^([^:]+):\s*(.+)$", r["t"]) or re.match(r"^(.*?)\s[—–-]\s*(.+)$", r["t"])
        k, v = (m.group(1).strip(), m.group(2).strip()) if m else ("", r["t"])
        if v.lower() not in vals:
            draft.setdefault("riskCases", []).append({"k": k[:80], "v": v[:TEXT_CAP]})
    _use(page, ([g["head"]] if g["head"] else []) + g["rows"])


def _route_general(draft, page):
    """Загальні правила по підзаголовках: «Skip» — у «коли не входжу», «BE» —
    у супровід, ризик — у цифри (+ деталі окремими випадками), час сесій —
    у вікна; решта — окремими блоками в «Додатково»."""
    no = draft.setdefault("no", {"market": [], "time": [], "self": []})
    for g in _groups(page):
        h = _head_text(g)
        head = [g["head"]] if g["head"] else []
        if not g["rows"]:
            if g["head"] and not h.endswith("?"):
                draft.setdefault("extra", []).append(_block(page["title"] or "General", g["head"]["t"], g["shots"]))
            _use(page, head)
            continue
        if RISK_HEAD_RE.search(h):
            _risk_rows(draft, g, page)
            continue
        if SESS_HEAD_RE.search(h) or any(TIME_RE.search(r["t"]) for r in g["rows"]):
            # час уже у вікнах сесій; рядки без часу (хто на яких сесіях,
            # «Asia/Frankfurt — інформаційні») не забираємо — їх збереже _rescue
            _use(page, head + [r for r in g["rows"] if TIME_RE.search(r["t"])])
            continue
        if SKIP_HEAD_RE.search(h):
            for _, text in _units(g["rows"]):
                if text not in no["market"]:
                    no["market"].append(text[:TEXT_CAP])
            _use(page, head + g["rows"])
            continue
        if MANAGE_HEAD_RE.search(h):
            draft.setdefault("manage", []).append(dict(_block(h, _tree(g["rows"]), g["shots"])))
            _use(page, head + g["rows"])
            continue
        draft.setdefault("extra", []).extend(_cards(h or page["title"] or "General", g["rows"], g["shots"]))
        _use(page, head + g["rows"])


def _route_list(page):
    """Сторінка-перелік (психологія, чек-лист, «коли не входжу»): пункти з
    поясненнями під ними. Підзаголовок стає «ситуацією» для своїх пунктів."""
    out = []
    for g in _groups(page):
        h = _head_text(g)
        if not g["rows"]:
            if g["head"] and not h.endswith("?") and not g["head"]["t"].endswith(":"):
                out.append(("", g["head"]["t"]))
        else:
            for _, text in _units(g["rows"]):
                out.append((h, text))
        _use(page, ([g["head"]] if g["head"] else []) + g["rows"])
    return out


def _route_manage(draft, page):
    """Супровід угоди: кожен підзаголовок («BE», «Часткова фіксація») —
    окреме правило зі своїми скрінами; без підзаголовків — уся сторінка."""
    for g in _groups(page):
        if not g["rows"] and not g["shots"]:
            continue
        k = _head_text(g) or page["title"] or ""
        draft.setdefault("manage", []).extend(_cards(k, g["rows"], g["shots"]))
        _use(page, ([g["head"]] if g["head"] else []) + g["rows"])


def route_pages(draft, pages):
    """Розкладає сторінки за їхніми назвами. Сторінку, чию назву не впізнали,
    кладемо в «Додатково» цілою — під її ж назвою, зі скрінами."""
    draft.setdefault("extra", [])
    draft.setdefault("ctx", [])
    draft.setdefault("psy", [])
    # Пошук за словами по всьому тексту дає уривки: будь-який рядок зі словом
    # «бу» ставав правилом супроводу, будь-яке «не входжу» — стоп-сигналом.
    # Коли є сторінки, ці поля збираємо з них самих; нічого не пропаде —
    # решту підбере _rescue.
    draft["manage"] = []
    draft.setdefault("no", {"market": [], "time": [], "self": []})["market"] = []
    seen = set()      # розділи, вже взяті зі сторінки: друга така сторінка додається, а не затирає
    for page in pages:
        title = page.get("title") or ""
        kind = page_kind(title, page.get("text") or "")
        before = list(draft.get(kind) or []) if kind in seen else []
        if kind == "psy":
            rules = [{"k": k[:80], "v": v[:TEXT_CAP]} for k, v in _route_list(page)]
            draft["psy"] = (before + rules)[:LIST_CAP]
            seen.add("psy")
        elif kind == "models" and _route_models(draft, page):
            draft["models"] = (before + draft["models"])[:LIST_CAP]
            seen.add("models")
        elif kind == "stop":
            _route_stop(draft, page)
        elif kind == "context" and _route_context(draft, page):
            pass
        elif kind == "general":
            _route_general(draft, page)
        elif kind == "check":
            items = [((k + ": ") if k else "") + v for k, v in _route_list(page)]
            draft["check"] = (before + [x[:TEXT_CAP] for x in items])[:LIST_CAP]
            seen.add("check")
        elif kind == "nogo":
            no = draft.setdefault("no", {"market": [], "time": [], "self": []})
            for k, v in _route_list(page):
                x = (((k + ": ") if k else "") + v)[:TEXT_CAP]
                if x not in no.get("market", []):
                    no.setdefault("market", []).append(x)
        elif kind == "manage":
            if "manage" not in seen:
                draft["manage"] = []          # слова з усього тексту — гірші за саму сторінку
            _route_manage(draft, page)
            seen.add("manage")
        else:
            # не впізнали — уся сторінка одним блоком під своєю назвою
            rows = _lines(page)
            if rows or page["shots"]:
                draft["extra"].append(_block(title or "Notion", _tree(rows), page["shots"]))
            _use(page, rows)
    draft.pop("_ctx", None)
    draft["extra"] = draft["extra"][:LIST_CAP]
    taken = " ".join(b["v"] for b in draft["extra"] + draft.get("manage", []))
    no = draft.get("no") or {}
    no["market"] = [x for x in no.get("market", [])
                    if not x.rstrip().endswith(":") and x not in taken][:LIST_CAP]
    return draft


# --------------------------------------------- страховка: нічого не губимо --

def _plain(s):
    s = re.sub(r"[•◦▸·*]", " ", s or "")
    return re.sub(r"\s+", " ", s).strip().lower()


def _strings(o, out):
    if isinstance(o, str):
        out.append(o)
    elif isinstance(o, list):
        for x in o:
            _strings(x, out)
    elif isinstance(o, dict):
        for k, v in o.items():
            if k not in ("notion", "source", "updated"):
                _strings(v, out)
    return out


def _rescue(draft, pages):
    """Усе зі сторінок, що не лягло в жоден розділ, — у «Додатково» під
    заголовком свого блока, зі скрінами, які стояли поруч. Так і розбір
    словами, і розбір моделлю ніколи не губить написаного людиною."""
    strs = _strings(draft, [])
    hay = _plain(" \n ".join(strs))
    files = {s for s in strs if re.match(r"^ts\d+_", s)}
    extra = draft.setdefault("extra", [])
    for page in pages:
        used = page.get("_used") or set()
        for g in _groups(page):
            left = [r for r in g["rows"] if r["i"] not in used and _plain(r["t"]) not in hay]
            head_left = g["head"] and g["head"]["i"] not in used and _plain(g["head"]["t"]) not in hay
            shots = [sh for sh in g["shots"] if sh["file"] not in files]
            lone = head_left and not g["rows"] and not g["head"]["t"].rstrip().endswith(("?", ":"))
            if left or shots:
                extra.append(_block(_head_text(g) or page.get("title") or "Notion", _tree(left), shots))
            elif lone:
                # окремий абзац-рядок без пунктів під ним
                extra.append(_block(page.get("title") or "Notion", g["head"]["t"]))
            else:
                continue
            files.update(sh["file"] for sh in shots)
        # скріни без місця (без «at») — наприкінці сторінки
        rest = [sh for sh in page.get("shots") or [] if sh["file"] not in files]
        if rest:
            extra.append(_block(page.get("title") or "Notion", "", rest))
            files.update(sh["file"] for sh in rest)
    draft["extra"] = extra[:LIST_CAP]
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
    for key in ("models", "manage", "extra", "ctx"):
        for row in draft.get(key) or []:
            taken.update(row.get("shots") or [])
    for key in ("stop", "target"):
        got = (draft.get(key) or {}).get("shot")
        if got:
            taken.add(got)

    for key, title in (("models", "name"), ("manage", "k"), ("ctx", "k"), ("extra", "k")):
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

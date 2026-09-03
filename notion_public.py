# -*- coding: utf-8 -*-
"""
Перенос журнала из Notion по обычной ссылке.

Никаких ключей и интеграций: человек в Notion нажимает Share -> Publish to web,
копирует ссылку и вставляет её сюда. Дальше читаем страницу так же, как её
читает сам сайт Notion, когда её открывает случайный посетитель.

Почему не официальное API: оно требует ключ интеграции, а объяснить человеку,
что такое «Internal Integration Secret», невозможно. Публичная ссылка понятна всем.

Чем платим: это внутреннее API Notion, оно не описано в документации и может
измениться без предупреждения. Ломается заметно — сразу перестанет читать, тихо
неправильных данных не даст.

Формат данных проверен на живой публичной базе Notion:
  block[id].value.value        — сама строка
  collection[id].value.value.schema  — {ид_колонки: {name, type}}
  properties                   — {ид_колонки: [[текст], ...]}
  даты                         — [["‣", [["d", {"start_date": "...", ...}]]]]
"""

import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import tidy
from notion_import import (NotionError, Job, guess_mapping, NORMALIZE, FIELDS,
                           download, guess_tf, MAX_SHOT, NET_TIMEOUT)

BASE = "https://www.notion.so/api/v3/"
IMG = "https://www.notion.so/image/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

MIN_GAP = 0.30
PAGE_STEP = 200          # сколько строк просим за раз
PROBE = 25               # столько читаем, чтобы понять, что лежит в колонках
DRILL_ROWS = 25          # во столько страниц оглавления заглядываем
INDEX_MAX = 2            # если полей узнали не больше — считаем таблицу оглавлением
PAGE_CAP = 5000          # предохранитель от бесконечной базы

_last = [0.0]
_gap = threading.Lock()


def _throttle():
    with _gap:
        wait = MIN_GAP - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()


def _post(path, body, space=None, tries=3):
    data = json.dumps(body).encode("utf-8")
    for attempt in range(tries):
        _throttle()
        req = urllib.request.Request(BASE + path, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("User-Agent", UA)
        if space:
            req.add_header("x-notion-space-id", space)
        try:
            with urllib.request.urlopen(req, timeout=NET_TIMEOUT) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise NotionError("сторінка закрита. У Notion відкрий її: Share → "
                                  "Publish to web, і скопіюй посилання ще раз")
            if e.code == 404:
                raise NotionError("Notion не знайшов таку сторінку — перевір посилання")
            if e.code in (429, 502, 503) and attempt < tries - 1:
                time.sleep(2 + attempt * 2)
                continue
            raise NotionError("Notion відповів помилкою %s" % e.code)
        except Exception as ex:
            if attempt < tries - 1:
                time.sleep(1.5)
                continue
            raise NotionError("немає зв'язку з Notion: %s" % ex)


# ------------------------------------------------------------------- ссылка

HEX32 = re.compile(r"([0-9a-fA-F]{32})")
DASHED = re.compile(r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
                    r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})")


def _dash(raw):
    raw = raw.replace("-", "").lower()
    return "-".join([raw[:8], raw[8:12], raw[12:16], raw[16:20], raw[20:]])


def parse_link(url):
    """Из ссылки достаём id страницы и, если есть, id вида (?v=...)."""
    url = (url or "").strip()
    if not url:
        raise NotionError("вставте посилання на сторінку Notion")
    parts = urllib.parse.urlparse(url if "://" in url else "https://" + url)
    if parts.netloc and "notion." not in parts.netloc:
        raise NotionError("це не схоже на посилання Notion")

    view = ""
    for key, vals in urllib.parse.parse_qs(parts.query).items():
        if key == "v" and vals:
            m = HEX32.search(vals[0]) or DASHED.search(vals[0])
            if m:
                view = _dash(m.group(1))

    path = parts.path
    ids = DASHED.findall(path) or HEX32.findall(path)
    if not ids:
        raise NotionError("у посиланні немає ідентифікатора сторінки. "
                          "Скопіюй його в Notion через Share → Copy web link")
    return _dash(ids[-1]), view


# ------------------------------------------------------- разбор ответа Notion

def _unwrap(rec):
    """Notion заворачивает значение в два слоя, и не всегда в одинаковые."""
    if not isinstance(rec, dict):
        return {}
    v = rec.get("value", rec)
    if isinstance(v, dict) and "value" in v and isinstance(v["value"], dict):
        v = v["value"]
    return v if isinstance(v, dict) else {}


def load_page(pid):
    res = _post("loadPageChunk", {"pageId": pid, "limit": 100, "cursor": {"stack": []},
                                  "chunkNumber": 0, "verticalColumns": False})
    return res.get("recordMap") or {}


def collections_on(rm, pid=None):
    """Все таблицы, которые есть на странице. Ссылка может вести и на саму
       таблицу, и на страницу, внутри которой она лежит."""
    blocks = rm.get("block") or {}

    def pointer(b):
        return b.get("collection_id") or             ((b.get("format") or {}).get("collection_pointer") or {}).get("id")

    order = ([pid] if pid else []) + [k for k in blocks if k != pid]
    out, seen = [], set()
    for key in order:
        b = _unwrap(blocks.get(key) or {})
        if b.get("type") not in ("collection_view", "collection_view_page"):
            continue
        cid = pointer(b)
        views = b.get("view_ids") or []
        if cid and views and cid not in seen:
            seen.add(cid)
            out.append({"collection": cid, "view": views[0],
                        "space": b.get("space_id") or "", "block": key})
    return out


def schema_of(rm, cid):
    coll = _unwrap((rm.get("collection") or {}).get(cid) or {})
    return coll.get("schema") or {}, (coll.get("name") and _plain(coll["name"])) or ""


def query(cid, vid, space, limit):
    body = {
        "collection": {"id": cid, "spaceId": space},
        "collectionView": {"id": vid, "spaceId": space},
        "source": {"type": "collection", "id": cid, "spaceId": space},
        "loader": {"type": "reducer",
                   "reducers": {"collection_group_results": {"type": "results", "limit": limit}},
                   "sort": [], "filter": {"filters": [], "operator": "and"},
                   "searchQuery": "", "userTimeZone": "Europe/Kyiv"},
    }
    return _post("queryCollection?src=initial_load", body, space)


def rows_of(res):
    rr = (res.get("result") or {}).get("reducerResults") or {}
    grp = rr.get("collection_group_results") or {}
    return grp.get("blockIds") or [], (res.get("result") or {}).get("sizeHint") or 0


# ------------------------------------------------------------ чтение значений

def _plain(rich):
    """Текст из массива Notion. Даты разворачиваем, ссылки на людей
       и страницы пропускаем — в журнале от них толку нет."""
    if not isinstance(rich, list):
        return str(rich or "")
    out = []
    for seg in rich:
        if not isinstance(seg, list) or not seg:
            continue
        text = seg[0]
        marks = seg[1] if len(seg) > 1 and isinstance(seg[1], list) else []
        if text == "‣":
            for m in marks:
                if isinstance(m, list) and m and m[0] == "d":
                    out.append(_date_str(m[1] if len(m) > 1 else {}))
            continue
        out.append(str(text))
    return "".join(out).strip()


def _date_str(d):
    if not isinstance(d, dict):
        return ""
    day = d.get("start_date") or ""
    tm = d.get("start_time") or ""
    return (day + "T" + tm) if (day and tm) else day


# ------------------------------------------------------------------ связи

# Notion хранит связь как ссылку на страницу: в значении лежит только id.
# Название приходится спрашивать отдельно — зато можно пачкой.
_REL = {}


def rel_ids(rich):
    out = []
    for seg in rich or []:
        if not isinstance(seg, list) or len(seg) < 2:
            continue
        for m in (seg[1] if isinstance(seg[1], list) else []):
            if isinstance(m, list) and len(m) > 1 and m[0] == "p":
                out.append(m[1])
    return out


def resolve_relations(ids, space, chunk=60):
    """Дотягиваем названия связанных страниц. Спрашиваем пачками и запоминаем:
       сетапов и сессий в журнале десяток, а угод — сотни."""
    todo = [i for i in dict.fromkeys(ids) if i and i not in _REL]
    for k in range(0, len(todo), chunk):
        part = todo[k:k + chunk]
        body = {"requests": [{"pointer": {"table": "block", "id": i, "spaceId": space},
                              "version": -1} for i in part]}
        try:
            res = _post("syncRecordValues", body, space)
        except NotionError:
            for i in part:
                _REL[i] = ""
            continue
        blocks = ((res.get("recordMap") or {}).get("block") or {})
        for i in part:
            rec = _unwrap(blocks.get(i) or {})
            _REL[i] = _plain((rec.get("properties") or {}).get("title")) if rec else ""
    return _REL


def prefetch_relations(blocks, ids, schema, space):
    """Собираем все связи со всех строк разом — и один раз спрашиваем."""
    rel_cols = [k for k, v in (schema or {}).items() if (v or {}).get("type") == "relation"]
    if not rel_cols:
        return
    want = []
    for bid in ids:
        props = (_unwrap(blocks.get(bid) or {}).get("properties") or {})
        for k in rel_cols:
            want += rel_ids(props.get(k))
    if want:
        resolve_relations(want, space)


def _files(rich):
    """Вложения: [["имя.png", [["a", "https://…"]]]]"""
    out = []
    if not isinstance(rich, list):
        return out
    for seg in rich:
        if not isinstance(seg, list) or len(seg) < 2:
            continue
        for m in seg[1] if isinstance(seg[1], list) else []:
            if isinstance(m, list) and len(m) > 1 and m[0] == "a":
                out.append({"url": m[1], "caption": str(seg[0])})
    return out


def signed(url, block_id):
    """Файлы Notion лежат в закрытом хранилище — публично их отдаёт
       только картиночный прокси самого Notion."""
    if not url:
        return ""
    if "secure.notion-static.com" in url or "prod-files-secure" in url \
       or "attachment:" in url or url.startswith("/image/"):
        return IMG + urllib.parse.quote(url, safe="") + \
            "?table=block&id=" + block_id + "&cache=v2"
    return url


def row_props(block, schema):
    """Строка Notion -> {название колонки: значение}."""
    props = block.get("properties") or {}
    out, files = {}, []
    for pid, rich in props.items():
        meta = schema.get(pid) or {}
        name = meta.get("name") or pid
        ptype = meta.get("type") or ""
        if ptype in ("file", "files"):
            files += [{"url": f["url"], "caption": name} for f in _files(rich)]
            continue
        if ptype == "relation":
            # у человека так лежат сессия, направление и сетап — раньше терялись
            out[name] = ", ".join(x for x in (_REL.get(i, "") for i in rel_ids(rich)) if x)
            continue
        out[name] = _plain(rich)
    return out, files


def looks_like_pair(v):
    """Похоже ли это на инструмент, а не на кусок текста из соседней колонки.

    В таблицах Notion между сделками попадаются строки-разделители вроде
    «1 Месяц» — заголовок месяца, а не сделка. У них заполнено только название,
    и раньше они приезжали в журнал наравне с настоящими сделками.

    Тикеры пишут латиницей и коротко: «NAS 100», «GER40», «S&P 500».
    Кириллица, длинная фраза или полное отсутствие латиницы — не инструмент.
    """
    v = (v or "").strip()
    if not v:
        return False
    if re.search(r"[Ѐ-ӿ]", v):      # кириллица
        return False
    if len(v) > 16:
        return False
    if len(v.split()) > 3:
        return False
    return bool(re.search(r"[A-Za-z]", v))


def map_simple(props, mapping):
    """{колонка: значение} + сопоставление -> наша сделка."""
    t = {}
    for field in FIELDS:
        col = mapping.get(field)
        raw = props.get(col, "") if col else ""
        fn = NORMALIZE.get(field)
        t[field] = fn(raw) if fn else (str(raw).strip() if raw is not None else "")
    return t


# --------------------------------------------------------- содержимое строки

TEXT_BLOCKS = ("text", "header", "sub_header", "sub_sub_header", "quote",
               "callout", "bulleted_list", "numbered_list", "to_do", "code")


def row_content(pid):
    """
    Заметки и картинки внутри карточки сделки — в том порядке, в каком
    они лежат на странице.

    Порядок важен: люди подписывают графики заголовком блока, а сами
    картинки кладут внутрь. Выглядит это так:

        callout «1D»       -> картинка
        callout «15m»      -> картинка
        callout «1m - 5m»  -> три картинки

    Значит подпись родителя и есть таймфрейм. Раньше мы её теряли,
    и у всех перенесённых скриншотов таймфрейм был пустой.
    """
    rm = load_page(pid)
    blocks = rm.get("block") or {}
    text, images = [], []

    def title_of(b):
        return _plain((b.get("properties") or {}).get("title"))

    def walk(key, label, depth):
        b = _unwrap(blocks.get(key) or {})
        bt = b.get("type") or ""
        props = b.get("properties") or {}

        if bt == "image":
            src = _plain(props.get("source")) or (b.get("format") or {}).get("display_source") or ""
            if src:
                cap = _plain(props.get("caption")) or label
                images.append({"url": signed(src, key), "caption": cap})
            return

        own = title_of(b)
        if bt in TEXT_BLOCKS and own:
            text.append(("• " if "list" in bt else "") + own)

        kids = b.get("content") or []
        if not kids or depth > 2:
            return
        # подпись этого блока становится подписью для картинок внутри
        sub = own or label
        missing = [k for k in kids if k not in blocks]
        if missing:
            try:
                more = _post("loadPageChunk", {"pageId": key, "limit": 100,
                                               "cursor": {"stack": []}, "chunkNumber": 0,
                                               "verticalColumns": False})
                blocks.update((more.get("recordMap") or {}).get("block") or {})
            except NotionError:
                pass
        for k in kids:
            walk(k, sub, depth + 1)

    page = _unwrap(blocks.get(pid) or {})
    for key in (page.get("content") or []):
        walk(key, "", 0)

    return "\n".join(text).strip(), images


# ------------------------------------------------------------------- сборка

def describe(t, rm=None, path=""):
    """Читаем таблицу настолько, чтобы понять: журнал это или что-то другое."""
    schema, title = schema_of(rm or {}, t["collection"])
    res = query(t["collection"], t["view"], t["space"], PROBE)
    if not schema:
        schema, title = schema_of(res.get("recordMap") or {}, t["collection"])
    if not schema:
        return None

    ids, total = rows_of(res)
    blocks = (res.get("recordMap") or {}).get("block") or {}
    prefetch_relations(blocks, ids[:PROBE], schema, t["space"])
    seen, row_ids = [], []
    for bid in ids[:PROBE]:
        props, _f = row_props(_unwrap(blocks.get(bid) or {}), schema)
        seen.append(props)
        row_ids.append(bid)

    types = {(v.get("name") or k): (v.get("type") or "") for k, v in schema.items()}
    values = {name: [row.get(name, "") for row in seen] for name in types}
    mapping = guess_mapping(types, values)

    return dict(t, title=title or path or "без назви", path=path, rows=total,
                matched=len(mapping), mapping=mapping, types=types,
                values=values, sample=seen, row_ids=row_ids, schema=schema)


def find_tables(url):
    """
    Возвращает все таблицы, до которых дотянулись.

    Журнал часто устроен так: одна таблица-оглавление, в ней строки
    «Trading Journal (August 2026)», а сами сделки — внутри этих страниц.
    Поэтому если наверху ничего похожего на журнал нет, заходим внутрь строк.
    """
    pid, _view = parse_link(url)
    rm = load_page(pid)
    tops = collections_on(rm, pid)
    if not tops:
        raise NotionError("на цій сторінці немає жодної таблиці. "
                          "Дай посилання на сторінку з таблицею або на саму таблицю")

    # Заходя внутрь строки, Notion отдаёт и родительскую таблицу — иначе
    # она повторится столько раз, сколько строк в оглавлении.
    tables, notes, seen = [], [], set()

    def add(t, rm_src, path=""):
        if t["collection"] in seen:
            return
        seen.add(t["collection"])
        d = describe(t, rm_src, path=path)
        if d:
            tables.append(d)

    for t in tops:
        add(t, rm)

    # Похоже на оглавление — идём внутрь строк
    best = max([t["matched"] for t in tables] or [0])
    if best <= INDEX_MAX:
        for parent in list(tables):
            kids = parent["row_ids"][:DRILL_ROWS]
            if parent["rows"] > len(kids):
                notes.append("зазирнули в перші %d сторінок із %d"
                             % (len(kids), parent["rows"]))
            for i, rid in enumerate(kids):
                name = ""
                for col, ptype in parent["types"].items():
                    if ptype == "title":
                        name = (parent["sample"][i] or {}).get(col, "")
                        break
                try:
                    sub = load_page(rid)
                except NotionError:
                    continue
                for t2 in collections_on(sub, rid):
                    add(t2, sub, path=name)

    tables.sort(key=lambda t: (t["matched"], t["rows"]), reverse=True)
    return tables, notes


def _slim(t):
    """То, что уходит в браузер: без сырых значений."""
    return {"collection": t["collection"], "view": t["view"], "space": t["space"],
            "title": t["title"], "path": t["path"], "rows": t["rows"],
            "matched": t["matched"]}


def preview(url, mapping=None, table=None, sample=5):
    """
    Без table — ищем все таблицы и разбираем лучшую.
    С table — разбираем именно её (человек выбрал из списка).
    """
    if table and table.get("collection"):
        found = {"collection": table["collection"], "view": table["view"],
                 "space": table.get("space") or ""}
        d = describe(found, None, path=table.get("path") or "")
        if not d:
            raise NotionError("не вдалося прочитати колонки таблиці")
        tables, notes = [d], []
    else:
        tables, notes = find_tables(url)
        if not tables:
            raise NotionError("не вдалося прочитати жодну таблицю")
        d = tables[0]

    use = mapping or d["mapping"]
    rows = [map_simple(row, use) for row in d["sample"][:sample]]

    return {"chosen": _slim(d), "tables": [_slim(t) for t in tables],
            "notes": notes, "title": d["title"], "path": d["path"],
            "mapping": use, "total": d["rows"],
            "columns": [{"name": n, "type": t} for n, t in sorted(d["types"].items())],
            "rows": rows}


def run_public_import(job, tables, mapping, opts, shots_dir, known_pairs, existing_ids,
                      sink, seen_trades=None):
    """
    Читаем выбранные таблицы целиком и отдаём готовые сделки в sink.

    tables — список {collection, view, space, path}. Их может быть несколько:
    журнал часто разбит по месяцам, и переносить его надо за один раз.
    Сопоставление колонок одно на всех; там, где оно не подходит,
    для таблицы подбираем своё.
    """
    try:
        want_notes = bool(opts.get("notes", True))
        want_shots = bool(opts.get("shots", True))
        skip_known = bool(opts.get("skipExisting", True))
        # Та сама угода, записана у двох журналах, приїде з різними notion_id —
        # по них її не впізнати. Тоді впізнаємо за відбитком: день, інструмент,
        # напрямок, результат.
        skip_same = bool(opts.get("skipSimilar", True))
        seen_trades = dict(seen_trades or {})

        job.step = "читаємо таблиці"
        plans = []
        for t in tables:
            src = {"collection": t["collection"], "view": t["view"],
                   "space": t.get("space") or ""}
            limit = PAGE_STEP
            while True:
                res = query(src["collection"], src["view"], src["space"], limit)
                ids, total = rows_of(res)
                if len(ids) >= total or limit >= PAGE_CAP:
                    break
                limit = min(limit * 4, PAGE_CAP)
            rm = res.get("recordMap") or {}
            schema, title = schema_of(rm, src["collection"])
            if not schema:
                continue
            job.step = "читаємо звʼязки"
            prefetch_relations(rm.get("block") or {}, ids, schema, src["space"])

            # Своё сопоставление, если общее к этой таблице не подходит
            types = {(v.get("name") or k): (v.get("type") or "") for k, v in schema.items()}
            use = mapping if mapping.get("pair") in types else None
            if use is None:
                probe = [row_props(_unwrap((rm.get("block") or {}).get(b) or {}), schema)[0]
                         for b in ids[:PROBE]]
                vals = {n: [r.get(n, "") for r in probe] for n in types}
                use = guess_mapping(types, vals)
                job.warnings.append("«%s»: колонки інші, звірили окремо" % (title or "таблиця"))
            plans.append((ids, rm, schema, use, title or t.get("path") or ""))

        job.total = sum(len(p[0]) for p in plans)
        batch = []
        odd = []          # названия, не похожие на инструмент, — покажем в конце

        for ids, rm, schema, use, tname in plans:
            blocks = rm.get("block") or {}
            for bid in ids:
                job.done += 1
                if skip_known and bid in existing_ids:
                    job.skipped += 1
                    continue

                props, files = row_props(_unwrap(blocks.get(bid) or {}), schema)
                t = map_simple(props, use)
                t["notion_id"] = bid
                t["import_id"] = job.batch
                # Строка-разделитель отличается от сделки двумя вещами: в поле
                # инструмента у неё текст, и нет ни даты, ни результата. Первое
                # ловит только явный мусор («1 Месяц»), латинское «August 2026»
                # прошло бы насквозь — поэтому вторая проверка и главная.
                empty = (not (t.get("date") or "").strip()
                         and not (t.get("result") or "").strip())
                if empty or not looks_like_pair(t.get("pair")):
                    # не молча: пусть человек видит, что мы не взяли и почему
                    name = (t.get("pair") or "").strip()
                    if name and name not in odd:
                        odd.append(name)
                    job.skipped += 1
                    continue

                # Схожу угоду відсіюємо до скріншотів: качати картинки для
                # того, що ми зараз викинемо, — зайві хвилини й трафік.
                if skip_same:
                    mark = tidy.same_trade_key(t)
                    if mark and seen_trades.get(mark):
                        seen_trades[mark] -= 1
                        job.similar += 1
                        continue

                job.step = "%s · %s" % (t.get("pair") or "?", (t.get("date") or "")[:10])
                images = [{"url": signed(f["url"], bid), "caption": f["caption"]}
                          for f in files] if want_shots else []

                if want_notes or want_shots:
                    try:
                        text, inner = row_content(bid)
                    except NotionError as ex:
                        text, inner = "", []
                        job.warnings.append("картку не прочитали: %s" % ex)
                    if want_shots:
                        images += inner
                    if want_notes and text:
                        t["notes"] = (t["notes"] + "\n\n" + text).strip() if t.get("notes") else text

                shots = []
                for i, im in enumerate(images):
                    try:
                        base = "notion_%s_%d" % (re.sub(r"[^0-9a-f]", "", bid)[:32], i)
                        shots.append({"tf": guess_tf(im.get("caption"), im["url"]),
                                      "file": download(im["url"], shots_dir, base)})
                        job.shots += 1
                    except Exception as ex:
                        job.warnings.append("скрін не завантажився: %s" % ex)
                t["screenshots"] = shots

                pair = (t.get("pair") or "").strip()
                if pair and pair not in known_pairs:
                    known_pairs.add(pair)
                    job.new_assets.append(pair)

                batch.append(t)
                job.added += 1
                if len(batch) >= 25:
                    sink(batch)
                    batch = []

        if batch:
            sink(batch)
        if odd:
            shown = ", ".join("«%s»" % x for x in odd[:5])
            more = " та ще %d" % (len(odd) - 5) if len(odd) > 5 else ""
            job.warnings.append("пропустили рядки, де замість інструмента текст: "
                                + shown + more)
        job.step = "готово"
        job.state = "done"
    except NotionError as ex:
        job.state, job.error = "error", str(ex)
    except Exception as ex:
        job.state, job.error = "error", "несподівана помилка: %s" % ex

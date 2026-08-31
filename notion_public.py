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

from notion_import import (NotionError, Job, guess_mapping, NORMALIZE, FIELDS,
                           download, guess_tf, MAX_SHOT, NET_TIMEOUT)

BASE = "https://www.notion.so/api/v3/"
IMG = "https://www.notion.so/image/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

MIN_GAP = 0.30
PAGE_STEP = 200          # сколько строк просим за раз
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


def find_collection(rm, pid):
    """Находим базу на странице. Ссылка может вести и на саму базу,
       и на страницу, внутри которой она лежит."""
    blocks = rm.get("block") or {}

    def pointer(b):
        return b.get("collection_id") or \
            ((b.get("format") or {}).get("collection_pointer") or {}).get("id")

    order = [pid] + [k for k in blocks if k != pid]
    for key in order:
        b = _unwrap(blocks.get(key) or {})
        if b.get("type") not in ("collection_view", "collection_view_page"):
            continue
        cid = pointer(b)
        views = b.get("view_ids") or []
        if cid and views:
            return {"collection": cid, "view": views[0],
                    "space": b.get("space_id") or "", "block": key}
    raise NotionError("на цій сторінці немає таблиці з угодами. "
                      "Дай посилання саме на базу — ту, де рядки й колонки")


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
        out[name] = _plain(rich)
    return out, files


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
    """Заметки и картинки внутри карточки сделки."""
    rm = load_page(pid)
    text, images = [], []
    for key, rec in (rm.get("block") or {}).items():
        b = _unwrap(rec)
        if key == pid:
            continue
        bt = b.get("type") or ""
        props = b.get("properties") or {}
        if bt in TEXT_BLOCKS:
            s = _plain(props.get("title"))
            if s:
                text.append(("• " if "list" in bt else "") + s)
        elif bt == "image":
            src = _plain(props.get("source")) or (b.get("format") or {}).get("display_source") or ""
            if src:
                images.append({"url": signed(src, key), "caption": _plain(props.get("caption"))})
    return "\n".join(text).strip(), images


# ------------------------------------------------------------------- сборка

def preview(url, mapping=None, sample=5):
    pid, _view = parse_link(url)
    rm = load_page(pid)
    found = find_collection(rm, pid)
    schema, title = schema_of(rm, found["collection"])
    if not schema:
        rm2 = query(found["collection"], found["view"], found["space"], 1).get("recordMap") or {}
        schema, title = schema_of(rm2, found["collection"])
    if not schema:
        raise NotionError("не вдалося прочитати колонки таблиці")

    types = {(v.get("name") or k): (v.get("type") or "") for k, v in schema.items()}
    mapping = mapping or guess_mapping(types)

    res = query(found["collection"], found["view"], found["space"], sample)
    ids, total = rows_of(res)
    blocks = (res.get("recordMap") or {}).get("block") or {}
    rows = []
    for bid in ids[:sample]:
        props, _f = row_props(_unwrap(blocks.get(bid) or {}), schema)
        rows.append(map_simple(props, mapping))

    return {"source": found, "title": title, "mapping": mapping, "total": total,
            "columns": [{"name": n, "type": t} for n, t in sorted(types.items())],
            "rows": rows}


def run_public_import(job, url, mapping, opts, shots_dir, known_pairs, existing_ids, sink):
    """Читаем публичную базу целиком и отдаём готовые сделки в sink."""
    try:
        job.step = "читаємо сторінку"
        pid, _view = parse_link(url)
        rm = load_page(pid)
        found = find_collection(rm, pid)
        schema, _title = schema_of(rm, found["collection"])

        limit = PAGE_STEP
        while True:
            res = query(found["collection"], found["view"], found["space"], limit)
            ids, total = rows_of(res)
            if not schema:
                schema, _title = schema_of(res.get("recordMap") or {}, found["collection"])
            if len(ids) >= total or limit >= PAGE_CAP:
                break
            limit = min(limit * 4, PAGE_CAP)

        blocks = (res.get("recordMap") or {}).get("block") or {}
        job.total = len(ids)

        want_notes = bool(opts.get("notes", True))
        want_shots = bool(opts.get("shots", True))
        skip_known = bool(opts.get("skipExisting", True))
        batch = []

        for bid in ids:
            job.done += 1
            if skip_known and bid in existing_ids:
                job.skipped += 1
                continue

            block = _unwrap(blocks.get(bid) or {})
            props, files = row_props(block, schema)
            t = map_simple(props, mapping)
            t["notion_id"] = bid
            if not (t.get("pair") or "").strip():
                job.skipped += 1
                continue

            job.step = "%s · %s" % (t.get("pair") or "?", (t.get("date") or "")[:10])
            images = [{"url": signed(f["url"], bid), "caption": f["caption"]} for f in files] \
                if want_shots else []

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
        job.step = "готово"
        job.state = "done"
    except NotionError as ex:
        job.state, job.error = "error", str(ex)
    except Exception as ex:
        job.state, job.error = "error", "несподівана помилка: %s" % ex

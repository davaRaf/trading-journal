# -*- coding: utf-8 -*-
"""
Посилання на угоду з бота.

Людина щойно записала угоду в Телеграмі — і одразу хоче нею поділитись.
Раніше для цього треба було йти на сайт: там sharelink.js збирає знімок
угоди й кладе його в share_store. Тут те саме, тільки з бота: під
повідомленням «Записав у журнал» кнопки «Так, посилання / Не треба», далі
питаємо, скільки посилання живе і в якому оформленні, і віддаємо адресу.

Знімок збираємо тою самою формою, що й сайт (sharelink.js: tradeSnapshot
→ tradeDetail), щоб share.html малював його як звичайний. Стан між
кроками не тримаємо: усе потрібне — id угоди, термін, оформлення — їде
в callback_data кнопки.
"""
import botlang
import config
import db
import share_store
import tg_api
from botlang import t

COLLAB = "blackswan"
TTL_ORDER = ["1h", "24h", "7d", "30d", "forever"]
TTL_LABEL = {"1h": "ttl1h", "24h": "ttl24h", "7d": "ttl7d", "30d": "ttl30d", "forever": "ttlForever"}

WIN_SET = ("Win", "WinM")
RES_LABEL = {"Win": "TP", "Loss": "SL", "BE-": "BE−", "BE+": "BE+", "BE": "BE"}


# ------------------------------------------------------------ арифметика ----
# Один в один з static/app.js: netR, isWin, dirType, resLabel.

def is_win(tr):
    return tr.get("result") in WIN_SET


def net_r(tr):
    risk = tr.get("risk")
    risk = risk if isinstance(risk, (int, float)) else 1
    if is_win(tr):
        rr = tr.get("rr")
        return risk * (rr if isinstance(rr, (int, float)) else 0)
    if tr.get("result") == "Loss":
        return -risk
    return 0


def dir_type(tr):
    own = (tr.get("direction_type") or "").strip()
    if own:
        return own
    p = (tr.get("position") or "").strip().lower()
    b = (tr.get("bias") or "").strip().lower()
    if not p or not b:
        return ""
    return "Continuation" if p == b else "Reversal"


def res_label(r, lang):
    if r == "WinM":
        return t(lang, "resHandFull")
    if r == "Skip":
        return t(lang, "resSkip")
    return RES_LABEL.get(r, r or "")


def _r1(v):
    return round(v * 100) / 100


def fmt_r(v):
    if v is None:
        return "—"
    x = _r1(v)
    s = ("%g" % x)
    return ("+" if x > 0 else "") + s + "%"


def _num(v):
    return "" if v is None else ("%g" % v)


# ------------------------------------------------------------------ знімок ----

def trade_detail(tr, lang):
    info = [
        (t(lang, "fSession"), tr.get("session")),
        (t(lang, "fPosition"), tr.get("position")),
        (t(lang, "fBias"), tr.get("bias")),
        (t(lang, "shEntryType"), dir_type(tr)),
        (t(lang, "shModel"), tr.get("entry_model")),
        (t(lang, "fSetup"), tr.get("setup")),
        (t(lang, "fRiskPlain"), (_num(tr.get("risk")) + "%") if tr.get("risk") is not None else ""),
        ("RR", _num(tr.get("rr"))),
        (t(lang, "fEmotion"), tr.get("emotion")),
    ]
    texts = [
        (t(lang, "shEntryBlock"), tr.get("entry_details")),
        (t(lang, "shNotes"), tr.get("notes")),
        (t(lang, "shMistakes"), tr.get("mistakes")),
    ]
    r = tr.get("result")
    return {
        "id": tr.get("id"),
        "time": (tr.get("date") or "")[11:16],
        "pair": tr.get("pair") or "",
        "result": res_label(r, lang),
        "cls": "pos" if is_win(tr) else "neg" if r == "Loss" else "be",
        "skip": r == "Skip",
        "net": net_r(tr),
        "info": [{"k": k, "v": str(v)} for k, v in info if v],
        "texts": [{"k": k, "v": v.strip()} for k, v in texts if (v or "").strip()],
        "shots": [{"tf": s.get("tf") or "", "file": s["file"], "note": (s.get("note") or "").strip()}
                  for s in (tr.get("screenshots") or []) if s.get("file")],
    }


def trade_snapshot(tr, lang, skin=""):
    net = net_r(tr)
    bt = tr.get("kind") == "bt"
    data = {
        "type": "trade",
        "kind": t(lang, "shKindBtTrade" if bt else "shKindTrade"),
        "kindFull": t(lang, "shOgBtTrade" if bt else "shOgTrade"),
        "title": "%s · %s" % (tr.get("pair") or "", res_label(tr.get("result"), lang)),
        "total": net,
        "kpis": [
            {"k": t(lang, "fResult"), "v": res_label(tr.get("result"), lang)},
            {"k": t(lang, "shTotal"), "v": fmt_r(net),
             "cls": "pos" if net > 0 else "neg" if net < 0 else ""},
            {"k": "RR", "v": _num(tr.get("rr")) or "—"},
            {"k": t(lang, "fRiskPlain"), "v": (_num(tr.get("risk")) + "%") if tr.get("risk") is not None else "—"},
        ],
        "trades": [trade_detail(tr, lang)],
        "blocks": [],
    }
    if bt:
        data["bt"] = True
        if tr.get("bt_run"):
            data["btRun"] = tr["bt_run"]
    if skin:
        data["skin"] = skin
    return data


def share_url(rec, user):
    """Адреса як у /api/share: з міткою партнера, якщо хазяїн від нього."""
    url = config.SITE_URL.rstrip("/") + "/s/" + rec["id"]
    ref = (user or {}).get("ref_source") or ""
    if ref in config.PARTNERS:
        short = next((s for s, full in config.PARTNER_ALIASES.items() if full == ref), ref)
        url += "?ref=" + short
    return url


def make_link(user, trade, ttl_key, skin):
    lang = botlang.of(user)
    ttl_key = ttl_key if ttl_key in share_store.TTL else "7d"
    data = trade_snapshot(trade, lang, skin if skin == COLLAB else "")
    rec = share_store.create(data, ttl_key, share_store.TTL[ttl_key], user["id"])
    return share_url(rec, user)


# ------------------------------------------------------------------- кнопки ----

def offer_kb(lang, tid):
    return [[{"text": t(lang, "shYes"), "callback_data": "sh:ttl:%s" % tid},
             {"text": t(lang, "shNo"), "callback_data": "sh:no"}]]


def _ttl_kb(lang, tid):
    rows, row = [], []
    for key in TTL_ORDER:
        row.append({"text": t(lang, TTL_LABEL[key]), "callback_data": "sh:sk:%s:%s" % (tid, key)})
        if len(row) == 2:
            rows.append(row); row = []
    if row:
        rows.append(row)
    return rows


def _skin_kb(lang, tid, ttl_key):
    return [[{"text": t(lang, "shSkinPlain"), "callback_data": "sh:go:%s:%s:plain" % (tid, ttl_key)},
             {"text": "Black Swan", "callback_data": "sh:go:%s:%s:%s" % (tid, ttl_key, COLLAB)}]]


def on_callback(cq, user):
    """Натиснута кнопка посилання. Повертає True, якщо вона наша."""
    data = cq.get("data") or ""
    if not data.startswith("sh:"):
        return False
    chat_id = cq["message"]["chat"]["id"]
    msg_id = cq["message"]["message_id"]
    lang = botlang.of(user)
    parts = data.split(":")
    action = parts[1]
    tg_api.answer_callback(cq["id"])

    if action == "no":
        # лишаємо картку угоди, прибираємо лише кнопки
        tg_api.edit_message_text(chat_id, msg_id, cq["message"].get("text") or t(lang, "shSkipped"))
        return True

    tid = parts[2] if len(parts) > 2 else ""
    trade = db.get_trade(tid, user["id"]) if tid else None
    if not trade:
        tg_api.edit_message_text(chat_id, msg_id, t(lang, "shGone"))
        return True

    if action == "ttl":
        tg_api.edit_message_text(chat_id, msg_id, t(lang, "shTtl"), keyboard=_ttl_kb(lang, tid))
        return True
    if action == "sk" and len(parts) > 3:
        tg_api.edit_message_text(chat_id, msg_id, t(lang, "shSkin"), keyboard=_skin_kb(lang, tid, parts[3]))
        return True
    if action == "go" and len(parts) > 4:
        ttl_key, skin = parts[3], parts[4]
        url = make_link(user, trade, ttl_key, skin)
        lives = t(lang, TTL_LABEL.get(ttl_key, "ttl7d"))
        tg_api.edit_message_text(chat_id, msg_id,
                                 t(lang, "shDone") + "\n" + url + "\n\n" + t(lang, "shLives", lives))
        return True
    return True


if __name__ == "__main__":
    # самоперевірка: знімок тою ж формою, що й sharelink.js
    tr = {"id": "t1", "pair": "GER40", "date": "2026-09-15 09:30", "session": "LONDON",
          "position": "Short", "bias": "Short", "entry_model": "cisd", "setup": "1h/15m/1m",
          "result": "Win", "rr": 6.0, "risk": 0.75, "entry_details": "test", "notes": "",
          "mistakes": "", "emotion": "Жадність", "screenshots": [{"tf": "1m", "file": "a.png"}],
          "kind": ""}
    d = trade_snapshot(tr, "ru", COLLAB)
    assert d["total"] == 4.5 and d["title"] == "GER40 · TP" and d["skin"] == "blackswan"
    assert d["kpis"][1]["v"] == "+4.5%" and d["kpis"][3]["v"] == "0.75%"
    td = d["trades"][0]
    assert td["cls"] == "pos" and td["time"] == "09:30" and td["shots"][0]["file"] == "a.png"
    assert dict((i["k"], i["v"]) for i in td["info"])["Тип входа"] == "Continuation"
    assert net_r({"result": "Loss", "risk": 2}) == -2 and net_r({"result": "BE-", "risk": 2}) == 0
    assert fmt_r(-1.5) == "-1.5%" and fmt_r(0) == "0%"
    print("ok")

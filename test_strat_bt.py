# -*- coding: utf-8 -*-
"""
Торгові стратегії в бектесті: python test_strat_bt.py

Список стратегій у людини один на обидва режими, а своїми в кожному
режимі є правила («Моя ТС») й угоди. Головне, що тут перевіряється:
правка ТС у бектесті НЕ тече в реальну торгівлю, і навпаки.

Дві частини, як у test_billing.py. Перша — чисті функції, бази не треба.
Друга йде в базу з .env і видно її за написом «жива база»; немає
DATABASE_URL — просто пропускається.
"""
import datetime
import os

# config читає .env — спершу він, інакше заглушка нижче перекрила б
# справжню адресу бази, і жива частина мовчки пропускалась би
import config

LIVE = bool(config.DATABASE_URL)
if not LIVE:
    os.environ.setdefault("DATABASE_URL", "postgresql://x/y")

import app
import bt_journals_store
import db
import ts_store

_fails = []


def case(name, got, want):
    ok = got == want
    print(("  ok  " if ok else "ПОМИЛКА") + "  " + name +
          ("" if ok else "  → отримали %r, чекали %r" % (got, want)))
    if not ok:
        _fails.append(name)
    return ok


# --------------------------------------------------- чисті функції ----

def pure():
    print("\nрежим і стратегія в одному kind")
    case("реальна торгівля, всі стратегії", db.strat_kind(""), "")
    case("реальна торгівля, третя", db.strat_kind("3"), "s:3")
    case("перша — це s:0", db.strat_kind("0"), "s:0")
    case("нецифра — всі", db.strat_kind("all"), "")
    case("весь бектест", db.strat_kind("", True), "bt")
    case("бектест третьої", db.strat_kind("3", True), "bt:s:3")
    case("бектест першої", db.strat_kind("0", True), "bt:s:0")
    case("бектест, нецифра — весь", db.strat_kind("all", True), "bt")

    print("\nts_store розкладає kind назад")
    case("реальна третя", ts_store._sk("s:3", 0), ("", "3"))
    case("бектест третьої", ts_store._sk("bt:s:3", 0), ("bt", "3"))
    case("весь бектест", ts_store._sk("bt", 7), ("bt", 7))
    case("порожній kind", ts_store._sk("", 2), ("", 2))

    print("\nугода бектесту памʼятає стратегію")
    t = app.clean_trade({"pair": "US100", "kind": "bt", "ts": "3"}, "t1")
    case("стратегія лишилась", (t["kind"], t["ts"]), ("bt", "3"))
    t = app.clean_trade({"pair": "US100", "kind": "bt", "ts": "0"}, "t2")
    case("перша пишеться порожнім", t["ts"], "")
    t = app.clean_trade({"pair": "US100", "kind": "bt", "ts": "хочу"}, "t3")
    case("сміття не проходить", t["ts"], "")

    print("\nжурнал прогону знає свою стратегію")
    case("номер лишається",
         bt_journals_store.clean({"name": "US100", "ts": "4"})["ts"], "4")
    case("без поля — спільний журнал",
         bt_journals_store.clean({"name": "US100"})["ts"], "")
    case("сміття — спільний журнал",
         bt_journals_store.clean({"name": "US100", "ts": "усі"})["ts"], "")
    case("ts серед полів бази", "ts" in bt_journals_store.FIELDS, True)


# ------------------------------------------------------- жива база ----

REAL = {"models": [{"name": "реальна модель"}]}
BTC = {"models": [{"name": "бектестова модель"}]}


def live():
    print("\nжива база")
    db.init()
    ts_store.init()
    bt_journals_store.init()

    with db.connect() as conn:
        cols = {(r["table_name"], r["column_name"]) for r in conn.execute(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_name IN ('ts_multi','bt_journals')").fetchall()}
    case("колонка ts_multi.data_bt", ("ts_multi", "data_bt") in cols, True)
    case("колонка bt_journals.ts", ("bt_journals", "ts") in cols, True)

    tag = "stratbt_test_%d" % int(datetime.datetime.now().timestamp())
    uid = db.create_user(tag + "@example.com", tag, "h", "s", 1)["id"]
    try:
        sid = ts_store.create(uid, "Скальп")
        case("додана стратегія завелась", bool(sid), True)

        # --- реальні правила ---
        ts_store.put(uid, REAL, "", sid)
        case("реальна ТС лягла", ts_store.get(uid, "", sid=sid), REAL)

        # --- перший захід у бектест знімає копію ---
        case("бектест притяг копію", ts_store.get(uid, "bt", sid=sid), REAL)

        # --- правка в бектесті лишається в бектесті ---
        ts_store.put(uid, BTC, "bt", sid)
        case("бектест змінився", ts_store.get(uid, "bt", sid=sid), BTC)
        case("реальна не зачеплена", ts_store.get(uid, "", sid=sid), REAL)

        # --- і навпаки ---
        ts_store.put(uid, {"models": [{"name": "правка в реалі"}]}, "", sid)
        case("бектест не зачеплено правкою реальної",
             ts_store.get(uid, "bt", sid=sid), BTC)

        # --- складений kind працює так само ---
        case("kind bt:s:N читає бектест",
             ts_store.get(uid, "bt:s:%d" % sid), BTC)

        # --- прибирання одного режиму не чіпає сусідній ---
        ts_store.clear(uid, "bt", sid)
        case("бектест прибрано", ts_store.get(uid, "bt", sid=sid), None)
        case("прибрана копія не знімається вдруге",
             ts_store.get(uid, "bt", sid=sid), None)
        case("реальна на місці",
             ts_store.get(uid, "", sid=sid)["models"][0]["name"], "правка в реалі")

        # --- список стратегій рахує «заповнена» по режиму ---
        ts_store.put(uid, BTC, "bt", sid)
        have = {s["id"]: s["has"] for s in ts_store.lst(uid, "bt")}
        case("у бектесті додана заповнена", have.get(sid), True)
        case("у бектесті перша порожня", have.get(0), False)

        # --- нова стратегія з бектесту: копія лягає в бектестову колонку ---
        sid2 = ts_store.create(uid, "З бектесту", copy_from=sid, kind="bt")
        case("копія в бектесті", ts_store.get(uid, "bt", sid=sid2), BTC)
        case("у реальній порожньо", ts_store.get(uid, "", sid=sid2), None)

        # --- угоди: бектест ріжеться стратегією ---
        db.insert_trades(uid, [
            app.clean_trade({"pair": "US100", "kind": "bt", "ts": str(sid),
                             "date": "2026-09-01"}, "sbt1"),
            app.clean_trade({"pair": "GER40", "kind": "bt",
                             "date": "2026-09-02"}, "sbt2"),
            app.clean_trade({"pair": "US100", "ts": str(sid),
                             "date": "2026-09-03"}, "sbt3"),
        ])
        case("весь бектест", len(db.list_trades(uid, "bt")), 2)
        case("бектест однієї стратегії",
             [t["pair"] for t in db.list_trades(uid, "bt:s:%d" % sid)], ["US100"])
        case("бектест першої стратегії",
             [t["pair"] for t in db.list_trades(uid, "bt:s:0")], ["GER40"])
        case("реальні не приїхали в бектест",
             all(t["kind"] == "bt" for t in db.list_trades(uid, "bt")), True)
        case("реальна стратегія бачить своє",
             [t["pair"] for t in db.list_trades(uid, "s:%d" % sid)], ["US100"])

        # --- журнал прогону: стратегія їде в базу й назад ---
        j = bt_journals_store.add(uid, {"name": "US100 вересень", "ts": str(sid)})
        case("журнал записав стратегію", j["ts"], str(sid))
        back = [x for x in bt_journals_store.lst(uid) if x["id"] == j["id"]][0]
        case("стратегія читається назад", back["ts"], str(sid))
        j2 = bt_journals_store.put(uid, j["id"], {"name": "US100 вересень", "ts": ""})
        case("журнал можна зробити спільним", j2["ts"], "")
    finally:
        with db.connect() as conn:
            conn.execute("DELETE FROM users WHERE id=%s", (uid,))
        print("  ok    тимчасового користувача прибрано")


def main():
    pure()
    if LIVE:
        live()
    else:
        print("\nжива база пропущена: немає DATABASE_URL")
    print("\n" + ("усе добре" if not _fails else "є помилки: " + ", ".join(_fails)))
    return 0 if not _fails else 1


if __name__ == "__main__":
    raise SystemExit(main())

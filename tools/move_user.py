# -*- coding: utf-8 -*-
"""Перенести одного користувача з однієї бази журналу в іншу.

Навіщо: сайт переїхав із Railway на свій сервер, користувачів скопіювали,
а старий адрес лишився живим — і люди встигли зареєструватись там уже
після копіювання. У новій базі їх немає, увійти вони не можуть.

Що переносить: рядок users (id призначається новий — старі номери в новій
базі вже зайняті іншими людьми), усі таблиці з user_id (угоди, стратегія,
Notion, налаштування, розбори днів, чернетки, резервні копії, посилання,
входи через сервіси) і файли скріншотів, на які посилаються угоди.
Список колонок читається з бази, тож нові поля переїдуть самі.

Запуск (на будь-якій машині, що бачить обидві бази):

    python tools/move_user.py --src "postgresql://…стара…" --dst "postgresql://…нова…" \\
        --nick alex_antip [--dry-run]

Якщо в новій базі вже є така пошта або нік — зупиняється і нічого не пише.
"""
import argparse
import sys

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

# таблиці з user_id, крім самої users; все пишеться однією транзакцією
PER_USER = ["trades", "strategies", "notion_conf", "user_prefs", "day_notes",
            "trade_drafts", "backups", "shares", "identities", "link_codes", "notified_events"]


def cols(conn, table):
    rows = conn.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position", (table,)).fetchall()
    return [(r["column_name"], r["data_type"]) for r in rows]


def exists(conn, table):
    return conn.execute("SELECT to_regclass(%s) IS NOT NULL AS ok", (table,)).fetchone()["ok"]


def wrap(value, dtype):
    """jsonb треба загорнути, решта їде як є."""
    if dtype == "jsonb" and value is not None:
        return Jsonb(value)
    return value


def copy_rows(dst, table, rows, new_user_id):
    if not rows:
        return 0
    both = [c for c in cols(dst, table) if c[0] in rows[0].keys()]
    names = [c[0] for c in both]
    sql = 'INSERT INTO "%s" (%s) VALUES (%s) ON CONFLICT DO NOTHING' % (
        table, ", ".join('"%s"' % n for n in names), ", ".join(["%s"] * len(names)))
    n = 0
    for r in rows:
        vals = []
        for name, dtype in both:
            v = new_user_id if (name == "user_id" and new_user_id is not None) else r[name]
            vals.append(wrap(v, dtype))
        n += dst.execute(sql, vals).rowcount
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="звідки (стара база)")
    ap.add_argument("--dst", required=True, help="куди (нова база)")
    ap.add_argument("--nick", required=True, help="нік користувача")
    ap.add_argument("--dry-run", action="store_true", help="лише показати, що перенеслось би")
    a = ap.parse_args()

    with psycopg.connect(a.src, row_factory=dict_row) as src, \
         psycopg.connect(a.dst, row_factory=dict_row) as dst:

        user = src.execute("SELECT * FROM users WHERE lower(nickname)=lower(%s)", (a.nick,)).fetchone()
        if not user:
            sys.exit("у старій базі нема користувача %r" % a.nick)
        old_id = user["id"]

        norm = (user.get("email_norm") or user.get("email") or "").strip().lower()
        clash = dst.execute(
            "SELECT id, nickname, email FROM users WHERE lower(nickname)=lower(%s) OR email_norm=%s",
            (user["nickname"], norm)).fetchone()
        if clash:
            sys.exit("у новій базі вже є такий нік або пошта: %r — нічого не робимо" % dict(clash))

        plan = {}
        for t in PER_USER:
            if exists(src, t) and exists(dst, t):
                plan[t] = src.execute('SELECT * FROM "%s" WHERE user_id=%%s' % t, (old_id,)).fetchall()
        names = [r["name"] for r in src.execute(
            "SELECT DISTINCT jsonb_array_elements(screenshots)->>'file' AS name "
            "FROM trades WHERE user_id=%s", (old_id,)).fetchall() if r["name"]]
        files = src.execute("SELECT * FROM files WHERE name = ANY(%s)", (names,)).fetchall() if names else []

        print("користувач %s (id %s у старій базі), пошта %s" % (user["nickname"], old_id, user["email"]))
        for t, rows in plan.items():
            if rows:
                print("  %-16s %d" % (t, len(rows)))
        print("  %-16s %d (посилань на скріни %d)" % ("files", len(files), len(names)))
        if a.dry_run:
            print("dry-run: нічого не записано")
            return

        with dst.transaction():
            ucols = [c for c in cols(dst, "users") if c[0] != "id" and c[0] in user]
            new = dst.execute(
                'INSERT INTO users (%s) VALUES (%s) RETURNING id' % (
                    ", ".join('"%s"' % c[0] for c in ucols), ", ".join(["%s"] * len(ucols))),
                [wrap(user[c[0]], c[1]) for c in ucols]).fetchone()["id"]
            done = {t: copy_rows(dst, t, rows, new) for t, rows in plan.items() if rows}
            if files:
                done["files"] = copy_rows(dst, "files", files, None)
        print("перенесено: новий id %s;" % new, ", ".join("%s %d" % kv for kv in done.items()))


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""
Telegram-помощник журнала. Запуск:  python bot.py

Делает две вещи:
  * спрашивает про эмоцию по сделкам, добавленным на сайте без неё;
  * напоминает о важных новостях — за полчаса и утренней сводкой.
"""
import datetime
import time
import traceback
from zoneinfo import ZoneInfo

import calendar_feed
import db
import emotions
import llm
import tg_api
from config import BOT_TOKEN

KYIV = ZoneInfo("Europe/Kyiv")
ALERT_MINUTES = 30       # за сколько минут до новости предупреждаем
JOB_EVERY = 60           # как часто проверяем расписание


def now_kyiv():
    return datetime.datetime.now(KYIV)


# ------------------------------------------------------------ команды ----

def on_start(chat_id, tg_id, username, arg):
    if not arg:
        user = db.get_user_by_telegram(tg_id)
        if user:
            tg_api.send_message(chat_id, "Акаунт «%s» уже прив'язаний. "
                                "Нагадаю про важливі новини і запитаю про емоції після угод."
                                % user["nickname"])
        else:
            tg_api.send_message(chat_id, "Привіт! Щоб прив'язати журнал, відкрий налаштування "
                                "на сайті → «Telegram» і натисни «Отримати код».")
        return
    status, user = db.consume_link_code(arg.strip(), tg_id, username)
    if status == "ok":
        tg_api.send_message(chat_id, "✅ Журнал «%s» прив'язано.\n"
                            "Тепер я нагадаю про важливі новини за %d хв і вранці, "
                            "а після кожної угоди без емоції запитаю, що ти відчував.\n"
                            "Команда /report — розбір, які емоції коштують дорожче."
                            % (user["nickname"], ALERT_MINUTES))
    elif status == "taken":
        tg_api.send_message(chat_id, "Цей Telegram уже прив'язаний до іншого журналу. "
                            "Спершу відв'яжи його в налаштуваннях того акаунта.")
    else:
        tg_api.send_message(chat_id, "Код не підійшов — він діє 15 хвилин і лише один раз. "
                            "Візьми новий у налаштуваннях на сайті.")


def on_callback(cq):
    data = cq.get("data") or ""
    chat_id = cq["message"]["chat"]["id"]
    msg_id = cq["message"]["message_id"]
    user = db.get_user_by_telegram(cq["from"]["id"])
    if not user:
        tg_api.answer_callback(cq["id"], "Журнал не прив'язаний")
        return

    if data.startswith("emofree:"):
        trade_id = data.split(":", 1)[1]
        trade = db.get_trade(trade_id, user["id"])
        if trade:
            tg_api.edit_message_text(chat_id, msg_id,
                                     "%s\n\nНапиши в чат, що відчував — запишу як є."
                                     % emotions.prompt_text(trade))
        tg_api.answer_callback(cq["id"])
        return

    if data.startswith("emo:"):
        _, trade_id, code = data.split(":", 2)
        label = emotions.LABELS.get(code)
        trade = db.get_trade(trade_id, user["id"])
        if not trade or not label:
            tg_api.answer_callback(cq["id"], "Угоду не знайдено")
            return
        if db.set_trade_emotion(trade_id, label):
            tg_api.edit_message_text(chat_id, msg_id, "Записав емоцію: %s ✍️" % label)
            tg_api.answer_callback(cq["id"])
        else:
            tg_api.answer_callback(cq["id"], "Емоцію вже записано")
        return

    tg_api.answer_callback(cq["id"])


def on_text(chat_id, tg_id, text):
    """Свободный ответ засчитываем, если ждём эмоцию ровно по одной сделке."""
    user = db.get_user_by_telegram(tg_id)
    if not user:
        tg_api.send_message(chat_id, "Спершу прив'яжи журнал: налаштування на сайті → «Telegram».")
        return
    pending = db.pending_emotion_trades(user["id"])
    if not pending:
        return
    if len(pending) > 1:
        tg_api.send_message(chat_id, "Зараз чекаю емоції по %d угодах — натисни кнопку під "
                            "потрібним повідомленням, щоб я не переплутав." % len(pending))
        return
    trade = pending[0]
    raw = text.strip()[:200]
    label = emotions.classify(raw)        # свои слова сводим к категории для статистики
    shown = "%s (%s)" % (label, raw) if label and label.lower() != raw.lower() else raw
    if db.set_trade_emotion(trade["id"], label or raw, raw):
        if trade["emotion_prompt_msg_id"]:
            try:
                tg_api.edit_message_text(chat_id, trade["emotion_prompt_msg_id"],
                                         "Записав емоцію: %s ✍️" % shown)
            except tg_api.TelegramError:
                pass
        tg_api.send_message(chat_id, "Записав ✍️")


MIN_FOR_REPORT = 5


def emotion_stats(rows):
    """Считаем сами: числа моделі не доверяем, она только формулирует вывод."""
    by = {}
    for r in rows:
        risk = r["risk"] if r["risk"] is not None else 1.0
        rr = r["rr"] if r["rr"] is not None else 0.0
        res = r["result"]
        val = risk * rr if res == "Win" else (-risk if res == "Loss" else 0.0)
        s = by.setdefault(r["emotion"], {"n": 0, "win": 0, "loss": 0, "net": 0.0})
        s["n"] += 1
        s["net"] += val
        if res == "Win": s["win"] += 1
        elif res == "Loss": s["loss"] += 1
    for s in by.values():
        s["wr"] = 100.0 * s["win"] / s["n"] if s["n"] else 0.0
    return dict(sorted(by.items(), key=lambda kv: kv[1]["net"]))


def stats_table(stats):
    return "\n".join(
        "%s — %d угод, win rate %.0f%%, підсумок %+.1f%%" % (name, s["n"], s["wr"], s["net"])
        for name, s in stats.items())


def on_report(chat_id, tg_id):
    user = db.get_user_by_telegram(tg_id)
    if not user:
        tg_api.send_message(chat_id, "Спершу прив'яжи журнал у налаштуваннях на сайті.")
        return
    rows = db.trades_with_emotion(user["id"])
    if not rows:
        tg_api.send_message(chat_id, "Поки нема жодної угоди із заповненою емоцією.")
        return
    stats = emotion_stats(rows)
    table = stats_table(stats)
    if len(rows) < MIN_FOR_REPORT:
        tg_api.send_message(chat_id, "Емоції по угодах:\n%s\n\nЩе замало даних для висновків — "
                            "потрібно хоча б %d угод." % (table, MIN_FOR_REPORT))
        return
    text = llm.ask(
        "Ти — спокійний тренер з трейдингу. Нижче статистика угод трейдера за емоційним "
        "станом під час входу. Числа вже пораховані — використовуй ЛИШЕ їх, нічого не "
        "вигадуй і не рахуй заново.\n\n%s\n\n"
        "Українською, до 5 речень: назви емоцію, яка коштує найдорожче, емоцію, з якою "
        "результат найкращий, і дай одну конкретну пораду. Без вступів і без списків."
        % table)
    if text:
        tg_api.send_message(chat_id, "📊 Емоції та результат:\n%s\n\n%s" % (table, text))
    else:
        tg_api.send_message(chat_id, "📊 Емоції та результат:\n%s" % table)


def handle_update(u):
    if "callback_query" in u:
        on_callback(u["callback_query"])
        return
    msg = u.get("message") or {}
    text = (msg.get("text") or "").strip()
    if not text:
        return
    chat_id = msg["chat"]["id"]
    sender = msg.get("from") or {}
    tg_id = sender.get("id")
    username = sender.get("username")
    if text.startswith("/start"):
        on_start(chat_id, tg_id, username, text[len("/start"):].strip())
    elif text.startswith("/report"):
        on_report(chat_id, tg_id)
    elif text.startswith("/"):
        tg_api.send_message(chat_id, "Я розумію /start і /report. Решта — кнопками під питаннями.")
    else:
        on_text(chat_id, tg_id, text)


# ---------------------------------------------------------- напоминания ----

def fmt_event(e, tz=KYIV):
    dt = calendar_feed.event_time(e)
    when = dt.astimezone(tz).strftime("%H:%M") if dt else "??:??"
    return "%s  %s — %s" % (when, e.get("country") or "", e.get("title") or "")


def job_alerts(events, users):
    """Красные новости в ближайшие полчаса."""
    now = datetime.datetime.now(datetime.timezone.utc)
    for e in events:
        if not calendar_feed.is_high(e):
            continue
        dt = calendar_feed.event_time(e)
        if not dt:
            continue
        left = (dt - now).total_seconds() / 60
        if not (0 <= left <= ALERT_MINUTES):
            continue
        key = calendar_feed.event_key(e)
        for user in users:
            if not db.record_notified(user["id"], key, "alert30"):
                continue          # уже предупреждали
            try:
                tg_api.send_message(user["telegram_id"],
                                    "⚠️ Через %d хв — важлива новина\n%s"
                                    % (round(left), fmt_event(e)))
            except tg_api.TelegramError as ex:
                print("alert:", ex)


def job_digest(events, users):
    """Утренняя сводка по красным новостям на сегодня."""
    local = now_kyiv()
    today = local.date()
    todays = [e for e in events if calendar_feed.is_high(e)
              and calendar_feed.event_time(e)
              and calendar_feed.event_time(e).astimezone(KYIV).date() == today]
    for user in users:
        if not user["digest_enabled"]:
            continue
        if local.hour != user["digest_hour"] or local.minute != user["digest_minute"]:
            continue
        if not db.record_notified(user["id"], "digest:%s" % today, "digest"):
            continue
        if todays:
            body = "\n".join(fmt_event(e) for e in todays)
            text = "☀️ Важливі новини сьогодні:\n%s" % body
        else:
            text = "☀️ Сьогодні важливих новин немає."
        try:
            tg_api.send_message(user["telegram_id"], text)
        except tg_api.TelegramError as ex:
            print("digest:", ex)


def run_due_jobs():
    users = db.linked_users()
    if not users:
        return
    events, _ = calendar_feed.calendar_events()
    job_alerts(events, users)
    job_digest(events, users)


# --------------------------------------------------------------- цикл ----

def main():
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN не задан — заполни .env (см. .env.example)")
    db.init()
    me = tg_api.get_me()
    db.meta_set("bot_username", me["username"])
    print("Бот @%s запущен" % me["username"])

    offset = int(db.meta_get("tg_offset", 0)) or None
    last_jobs = 0
    while True:
        try:
            updates = tg_api.get_updates(offset)
            for u in updates:
                try:
                    handle_update(u)
                except Exception:
                    traceback.print_exc()
                offset = u["update_id"] + 1
                db.meta_set("tg_offset", offset)
            if time.time() - last_jobs >= JOB_EVERY:
                last_jobs = time.time()
                run_due_jobs()
        except KeyboardInterrupt:
            print("stop"); return
        except Exception:
            traceback.print_exc()
            time.sleep(5)


if __name__ == "__main__":
    main()

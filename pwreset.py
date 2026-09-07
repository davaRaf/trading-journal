# -*- coding: utf-8 -*-
"""
«Забув пароль»: одноразове посилання, яке приходить на пошту і в Телеграм.

Чому саме посилання, а не код: код доводиться переносити руками, а
посилання відкривається одним дотиком — і з листа, і з чату бота.
Живе воно пів години й згорає після першого використання (db.take_reset),
тому лист, що залишився в скриньці, другого разу вже нічого не відкриє.

Шлемо в усі канали, які є в людини. Пошта могла загубитись у спамі,
телефон — лишитись удома; хай приходить туди й туди, а людина візьме
те, що ближче.
"""
import hashlib
import secrets

import config
import db
import mailer
import tg_api

TTL_MIN = 30
# Пошта, яку сайт вигадав сам за людину, коли вона зайшла через Google
# чи Discord і сервіс адреси не дав. Листи туди слати нікуди.
FAKE_DOMAIN = "@login.statsai"


def token_hash(token):
    """У базі тримаємо відбиток, а не сам ключ: витік бази не має
    відкривати чужі акаунти."""
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def has_email(user):
    mail = ((user or {}).get("email") or "").strip()
    return bool(mail) and not mail.lower().endswith(FAKE_DOMAIN)


def has_telegram(user):
    return bool((user or {}).get("telegram_id"))


# ------------------------------------------------------------- слова ----

ORDER = ("uk", "ru", "en")

SUBJECT = ("StatsAI — відновлення пароля",
           "StatsAI — восстановление пароля",
           "StatsAI — password reset")

LETTER = (
    "Привіт!\n\n"
    "Хтось (сподіваємось, ти) попросив новий пароль до журналу StatsAI.\n"
    "Відкрий це посилання й задай пароль — воно живе %(min)d хвилин:\n\n"
    "%(link)s\n\n"
    "Якщо пароль ти не забував — просто не відкривай листа. Поки посилання\n"
    "ніхто не відкрив, старий пароль працює як працював.\n",

    "Привет!\n\n"
    "Кто-то (надеемся, ты) попросил новый пароль к журналу StatsAI.\n"
    "Открой эту ссылку и задай пароль — она живёт %(min)d минут:\n\n"
    "%(link)s\n\n"
    "Если пароль ты не забывал — просто не открывай письмо. Пока ссылку\n"
    "никто не открыл, старый пароль работает как работал.\n",

    "Hi!\n\n"
    "Someone (hopefully you) asked for a new StatsAI password.\n"
    "Open this link and set one — it lives for %(min)d minutes:\n\n"
    "%(link)s\n\n"
    "If you did not ask, just ignore this letter. Until the link is opened,\n"
    "your old password keeps working.\n",
)

TG_TEXT = (
    "🔑 <b>Новий пароль до журналу</b>\n\n"
    "Відкрий посилання й задай пароль — воно живе %(min)d хвилин:\n%(link)s\n\n"
    "Не ти просив? Тоді нічого не роби: старий пароль лишається чинним.",

    "🔑 <b>Новый пароль к журналу</b>\n\n"
    "Открой ссылку и задай пароль — она живёт %(min)d минут:\n%(link)s\n\n"
    "Не ты просил? Тогда ничего не делай: старый пароль остаётся в силе.",

    "🔑 <b>New journal password</b>\n\n"
    "Open the link and set a password — it lives for %(min)d minutes:\n%(link)s\n\n"
    "Did not ask? Do nothing: your old password stays valid.",
)


def _t(row, lang):
    return row[ORDER.index(lang)] if lang in ORDER else row[0]


# ------------------------------------------------------------- робота ----

def link_for(base_url, token):
    return "%s/reset?t=%s" % ((base_url or config.SITE_URL).rstrip("/"), token)


def start(user, base_url, lang="uk"):
    """Зробити посилання й надіслати його всюди, куди можемо.

    Повертає список каналів, які спрацювали: ["email", "telegram"].
    Порожній список означає, що сказати людині нема куди — але назовні
    ми про це не говоримо (див. app.py): відповідь на «забув пароль»
    однакова завжди, інакше нею можна перевіряти, хто тут є.
    """
    token = secrets.token_urlsafe(32)
    db.create_reset(user["id"], token_hash(token), TTL_MIN)
    link = link_for(base_url, token)
    words = {"link": link, "min": TTL_MIN}
    done = []

    if has_email(user) and mailer.enabled():
        if mailer.send(user["email"], _t(SUBJECT, lang), _t(LETTER, lang) % words):
            done.append("email")

    if has_telegram(user):
        try:
            tg_api.call("sendMessage", {
                "chat_id": user["telegram_id"],
                "text": _t(TG_TEXT, lang) % words,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            })
            done.append("telegram")
        except Exception as ex:
            print("пароль: у Телеграм не пішло — %s" % ex, flush=True)

    if not done:
        # Ні пошти, ні бота — або пошта ще не налаштована. Кладемо
        # посилання в журнал сервера: на своїй машині це єдиний спосіб
        # пройти весь шлях, а на сервері — слід, що людині допомогти
        # нікуди, і чому.
        # flush обов'язковий: без нього рядок лежить у буфері й до
        # журналу сервера доходить хтозна-коли — а потрібен він саме
        # тоді, коли лист не пішов.
        print("пароль: нема куди надіслати (%s) — посилання %s"
              % (user.get("email"), link), flush=True)
    return done

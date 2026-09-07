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

Тон листа — діловий, на «ви», хоч бот в усьому іншому говорить просто і
на «ти». Лист про пароль людина бачить у скриньці поряд із банківськими
й службовими, часто на тлі тривоги «мене зламали»: панібратство тут
читається як підробка, а не як дружність.
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

SUBJECT = ("Відновлення пароля до журналу StatsAI",
           "Восстановление пароля к журналу StatsAI",
           "StatsAI password reset")

LETTER = (
    "Доброго дня!\n\n"
    "Ми отримали запит на відновлення пароля до вашого акаунта в журналі "
    "StatsAI.\n\n"
    "Щоб задати новий пароль, перейдіть за посиланням:\n"
    "%(link)s\n\n"
    "Посилання дійсне %(min)d хвилин і спрацьовує один раз.\n\n"
    "Якщо запиту ви не надсилали, залиште цей лист без уваги: поточний "
    "пароль лишається чинним.\n\n"
    "--\n"
    "StatsAI — помічник трейдера\n"
    "%(site)s\n",

    "Здравствуйте!\n\n"
    "Мы получили запрос на восстановление пароля к вашему аккаунту в журнале "
    "StatsAI.\n\n"
    "Чтобы задать новый пароль, перейдите по ссылке:\n"
    "%(link)s\n\n"
    "Ссылка действительна %(min)d минут и срабатывает один раз.\n\n"
    "Если запрос отправляли не вы, оставьте это письмо без внимания: текущий "
    "пароль остаётся действующим.\n\n"
    "--\n"
    "StatsAI — помощник трейдера\n"
    "%(site)s\n",

    "Hello,\n\n"
    "We have received a request to reset the password for your StatsAI "
    "account.\n\n"
    "To set a new password, follow this link:\n"
    "%(link)s\n\n"
    "The link is valid for %(min)d minutes and works once.\n\n"
    "If you did not make this request, please ignore this message: your "
    "current password remains valid.\n\n"
    "--\n"
    "StatsAI — trading assistant\n"
    "%(site)s\n",
)

TG_TEXT = (
    "🔑 <b>Відновлення пароля StatsAI</b>\n\n"
    "Щоб задати новий пароль, перейдіть за посиланням:\n%(link)s\n\n"
    "Посилання дійсне %(min)d хвилин і спрацьовує один раз. Якщо запиту ви "
    "не надсилали, залиште це повідомлення без уваги.",

    "🔑 <b>Восстановление пароля StatsAI</b>\n\n"
    "Чтобы задать новый пароль, перейдите по ссылке:\n%(link)s\n\n"
    "Ссылка действительна %(min)d минут и срабатывает один раз. Если запрос "
    "отправляли не вы, оставьте это сообщение без внимания.",

    "🔑 <b>StatsAI password reset</b>\n\n"
    "To set a new password, follow this link:\n%(link)s\n\n"
    "The link is valid for %(min)d minutes and works once. If you did not "
    "make this request, please ignore this message.",
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
    site = (base_url or config.SITE_URL).rstrip("/")
    link = link_for(site, token)
    words = {"link": link, "min": TTL_MIN, "site": site}
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

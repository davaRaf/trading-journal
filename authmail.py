# -*- coding: utf-8 -*-
"""
Листи, якими людина доводить, що адреса її: підтвердження пошти при
реєстрації і посилання на новий пароль.

Обидва влаштовані однаково — одноразове посилання з обмеженим часом
життя (db.create_link / db.take_link). Різниця в тому, скільки воно живе
і що робиться на тому кінці:

  password — пів години. Лист із таким посиланням лежить у скриньці, і
             що менше він живе, то менше з ним можна зробити.
  confirm  — доба. Людина відкриває пошту, коли зручно, а нічого небез-
             печного за цим посиланням не стоїть.

Посилання на новий пароль шлемо ще й у Телеграм, якщо журнал до нього
прив'язаний: пошта могла загубитись у спамі, телефон — лишитись удома.
А от підтвердження пошти — тільки поштою: воно саме про те, що адреса
робоча, і надіслане повз неї нічого не доводить.

Тон листів діловий, на «ви», хоч бот в усьому іншому говорить просто і
на «ти». Такі листи людина бачить у скриньці поряд із банківськими й
службовими, часто на тлі тривоги «мене зламали»: панібратство тут
читається як підробка, а не як дружність.
"""
import hashlib
import secrets

import config
import db
import mailer
import tg_api

RESET_MIN = 30
CONFIRM_MIN = 24 * 60
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

CONFIRM_SUBJECT = ("Підтвердження пошти в журналі StatsAI",
                   "Подтверждение почты в журнале StatsAI",
                   "Confirm your StatsAI email")

CONFIRM_LETTER = (
    "Доброго дня!\n\n"
    "На цю адресу зареєстровано акаунт у журналі трейдера StatsAI. "
    "Залишилось підтвердити, що пошта справді ваша.\n\n"
    "Для цього перейдіть за посиланням:\n"
    "%(link)s\n\n"
    "Посилання дійсне добу. Підтверджена пошта потрібна для одного: щоб "
    "ви могли повернути доступ, якщо забудете пароль.\n\n"
    "Якщо акаунт створювали не ви, залиште цей лист без уваги — без "
    "підтвердження адреса до журналу не прив'яжеться.\n\n"
    "--\n"
    "StatsAI — помічник трейдера\n"
    "%(site)s\n",

    "Здравствуйте!\n\n"
    "На этот адрес зарегистрирован аккаунт в журнале трейдера StatsAI. "
    "Осталось подтвердить, что почта действительно ваша.\n\n"
    "Для этого перейдите по ссылке:\n"
    "%(link)s\n\n"
    "Ссылка действительна сутки. Подтверждённая почта нужна для одного: "
    "чтобы вы могли вернуть доступ, если забудете пароль.\n\n"
    "Если аккаунт создавали не вы, оставьте это письмо без внимания — без "
    "подтверждения адрес к журналу не привяжется.\n\n"
    "--\n"
    "StatsAI — помощник трейдера\n"
    "%(site)s\n",

    "Hello,\n\n"
    "An account in the StatsAI trading journal has been registered with this "
    "address. All that is left is to confirm the email is yours.\n\n"
    "To do that, follow this link:\n"
    "%(link)s\n\n"
    "The link is valid for one day. A confirmed email serves one purpose: it "
    "lets you regain access if you forget your password.\n\n"
    "If you did not create the account, please ignore this message — without "
    "confirmation the address stays unlinked.\n\n"
    "--\n"
    "StatsAI — trading assistant\n"
    "%(site)s\n",
)


def _t(row, lang):
    return row[ORDER.index(lang)] if lang in ORDER else row[0]


# ------------------------------------------------------------- робота ----

def _make(user, base_url, kind, minutes, page):
    """Спільний початок обох листів: ключ, запис у базу, готова адреса."""
    token = secrets.token_urlsafe(32)
    db.create_link(user["id"], token_hash(token), kind, minutes)
    site = (base_url or config.SITE_URL).rstrip("/")
    return site, "%s/%s?t=%s" % (site, page, token)


def start(user, base_url, lang="ru"):
    """Посилання на новий пароль — поштою і в Телеграм.

    Повертає список каналів, які спрацювали: ["email", "telegram"].
    Порожній список означає, що сказати людині нема куди — але назовні
    ми про це не говоримо (див. app.py): відповідь на «забув пароль»
    однакова завжди, інакше нею можна перевіряти, хто тут є.
    """
    site, link = _make(user, base_url, "password", RESET_MIN, "reset")
    words = {"link": link, "min": RESET_MIN, "site": site}
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


def start_confirm(user, base_url, lang="uk"):
    """Лист із підтвердженням пошти. True — пішов.

    Тільки поштою: лист саме про те, що адреса робоча, і надісланий повз
    неї (у Телеграм) нічого не доводив би.
    """
    if not has_email(user):
        return False
    site, link = _make(user, base_url, "confirm", CONFIRM_MIN, "confirm")
    words = {"link": link, "site": site}
    if not mailer.enabled():
        print("пошта: підтвердження для %s не пішло (скринька не налаштована) "
              "— посилання %s" % (user.get("email"), link), flush=True)
        return False
    return mailer.send(user["email"], _t(CONFIRM_SUBJECT, lang),
                       _t(CONFIRM_LETTER, lang) % words)

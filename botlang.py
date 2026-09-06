# -*- coding: utf-8 -*-
"""
Слова бота трьома мовами.

Модель у боті говорить мовою людини сама (див. bot.user_lang), а от усе,
що складене кодом — питання сценарію, кнопки, підписи полів — було
зашите українською. Виходило навпіл: відповідь російською, а кнопки під
нею українською.

Мову беремо ту саму, що й модель: bot.user_lang запам'ятовує її в meta
під ключем «lang:<telegram_id>» після кожного повідомлення.

Значення, які лягають у журнал (емоції), тут не перекладаються: у базі
має бути одне написання на всіх, інакше розріз по емоціях розсиплеться
на мовні варіанти. Перекладаємо тільки те, що людина бачить.
"""
import db

DEFAULT = "uk"

PHRASES = {
    # ---- кнопка й команди ----
    "btnTrade":    ("➕ Записати угоду", "➕ Записать сделку", "➕ Add a trade"),
    "needLink":    ("Спершу прив'яжи журнал.", "Сначала привяжи журнал.",
                    "Link your journal first."),
    "shotOutside": ("Щоб додати скрін, почни запис угоди — кнопка «%s» унизу.",
                    "Чтобы добавить скрин, начни запись сделки — кнопка «%s» внизу.",
                    "To attach a screenshot, start a trade — the «%s» button below."),

    # ---- прив'язка журналу ----
    "linkHow":     ("Щоб почати, прив'яжи журнал:\n\n"
                    "1. Відкрий %s\n"
                    "2. Налаштування → «Telegram»\n"
                    "3. Тисни «Отримати код» і надішли його мені",
                    "Чтобы начать, привяжи журнал:\n\n"
                    "1. Открой %s\n"
                    "2. Настройки → «Telegram»\n"
                    "3. Нажми «Получить код» и пришли его мне",
                    "To start, link your journal:\n\n"
                    "1. Open %s\n"
                    "2. Settings → «Telegram»\n"
                    "3. Tap «Get code» and send it to me"),
    "linkShort":   ("Код чекає тут: %s\nНалаштування → «Telegram»",
                    "Код ждёт здесь: %s\nНастройки → «Telegram»",
                    "The code is here: %s\nSettings → «Telegram»"),
    "whatNow":     ("Що тепер буде:\n\n"
                    "• попереджу про важливі новини — за %d хв і вранці\n"
                    "• після угоди без емоції спитаю, що ти відчував\n"
                    "• попроси розбір — покажу, які емоції коштують тобі дорожче\n"
                    "• кнопкою «%s» унизу запишеш угоду прямо з чату",
                    "Что теперь будет:\n\n"
                    "• предупрежу о важных новостях — за %d мин и утром\n"
                    "• после сделки без эмоции спрошу, что ты чувствовал\n"
                    "• попроси разбор — покажу, какие эмоции стоят тебе дороже\n"
                    "• кнопкой «%s» внизу запишешь сделку прямо из чата",
                    "What happens next:\n\n"
                    "• I warn about important news — %d min ahead and in the morning\n"
                    "• after a trade with no emotion I ask what you felt\n"
                    "• ask for a review — I show which emotions cost you more\n"
                    "• the «%s» button below saves a trade right from the chat"),

    # ---- питання кроків ----
    "qPair":       ("Яка пара?", "Какая пара?", "Which pair?"),
    "qDate":       ("Коли це було?", "Когда это было?", "When was it?"),
    "qSession":    ("Яка сесія?", "Какая сессия?", "Which session?"),
    "qPosition":   ("Напрямок?", "Направление?", "Direction?"),
    "qBias":       ("Який біас?", "Какой биас?", "What was your bias?"),
    "qSetup":      ("Сетап?", "Сетап?", "Setup?"),
    "qEntryModel": ("Модель входу?", "Модель входа?", "Entry model?"),
    "qAccount":    ("Який рахунок?", "Какой счёт?", "Which account?"),
    "qResult":     ("Чим закінчилась?", "Чем закончилась?", "How did it end?"),
    "qRr":         ("Скільки RR?", "Сколько RR?", "How many RR?"),
    "qRisk":       ("Який ризик, %%?", "Какой риск, %%?", "What risk, %%?"),
    "qShot":       ("Надішли скрін угоди — картинкою в чат.",
                    "Пришли скрин сделки — картинкой в чат.",
                    "Send a screenshot of the trade as an image."),
    "qEmotion":    ("Яка емоція була під час угоди?",
                    "Какая эмоция была во время сделки?",
                    "What did you feel during the trade?"),

    # ---- підказки під питанням ----
    "hintOwn":     ("Можна написати своє.", "Можно написать своё.",
                    "You can type your own."),
    "hintNumber":  ("Напиши числом.", "Напиши числом.", "Type a number."),
    "hintDate":    ("Або напиши дату: 2026-09-05.", "Или напиши дату: 2026-09-05.",
                    "Or type a date: 2026-09-05."),
    "hintEmotion": ("Або опиши своїми словами.", "Или опиши своими словами.",
                    "Or describe it in your own words."),

    # ---- кнопки ----
    "today":       ("Сьогодні", "Сегодня", "Today"),
    "yesterday":   ("Вчора", "Вчера", "Yesterday"),
    "asLastTime":  ("Як минулого разу (%s)", "Как в прошлый раз (%s)",
                    "Same as last time (%s)"),
    "back":        ("← Назад", "← Назад", "← Back"),
    "skip":        ("Пропустити", "Пропустить", "Skip"),
    "cancel":      ("✕ Скасувати", "✕ Отменить", "✕ Cancel"),
    "save":        ("✅ Записати", "✅ Записать", "✅ Save"),
    "next":        ("Далі →", "Дальше →", "Next →"),
    "ownWords":    ("✍️ Написати своє", "✍️ Написать своё", "✍️ Write your own"),

    # ---- підписи результатів (коди Win/Loss/BE лишаються в журналі) ----
    "resHand":     ("Рукою", "Рукой", "By hand"),
    "resSkip":     ("Скіп", "Скип", "Skip"),

    # ---- картка ----
    "fPair":       ("Пара", "Пара", "Pair"),
    "fDate":       ("Дата", "Дата", "Date"),
    "fSession":    ("Сесія", "Сессия", "Session"),
    "fPosition":   ("Напрямок", "Направление", "Direction"),
    "fBias":       ("Біас", "Биас", "Bias"),
    "fSetup":      ("Сетап", "Сетап", "Setup"),
    "fEntryModel": ("Модель входу", "Модель входа", "Entry model"),
    "fAccount":    ("Рахунок", "Счёт", "Account"),
    "fResult":     ("Результат", "Результат", "Result"),
    "fRr":         ("RR", "RR", "RR"),
    "fRisk":       ("Ризик, %%", "Риск, %%", "Risk, %%"),
    "fEmotion":    ("Емоція", "Эмоция", "Emotion"),
    "fShots":      ("Скрін: %d", "Скрин: %d", "Screenshots: %d"),
    "cardEmpty":   ("Поки що порожньо.", "Пока пусто.", "Nothing yet."),
    "cardHead":    ("Ось що вийшло:", "Вот что получилось:", "Here is what we have:"),
    "cardAsk":     ("Записати в журнал?", "Записать в журнал?", "Save to the journal?"),

    # ---- відповіді сценарію ----
    "pressButtons": ("Натисни «Записати» або «Скасувати» під карткою.",
                     "Нажми «Записать» или «Отменить» под карточкой.",
                     "Tap «Save» or «Cancel» under the card."),
    "notNumber":   ("Це не схоже на число. Напиши, наприклад, 1.5",
                    "Это не похоже на число. Напиши, например, 1.5",
                    "That does not look like a number. Try 1.5"),
    "notDate":     ("Не зрозумів дату. Напиши так: 2026-09-05",
                    "Не понял дату. Напиши так: 2026-09-05",
                    "I did not get the date. Use 2026-09-05"),
    "useButton":   ("Обери кнопкою, будь ласка.", "Выбери кнопкой, пожалуйста.",
                    "Please pick one of the buttons."),
    "cancelled":   ("Скасував. Нічого не записав.", "Отменил. Ничего не записал.",
                    "Cancelled. Nothing was saved."),
    "oldStep":     ("Це кнопка з попереднього кроку", "Это кнопка с предыдущего шага",
                    "That button is from an earlier step"),
    "oldButton":   ("Кнопка застаріла", "Кнопка устарела", "That button is out of date"),
    "gone":        ("Ця угода вже закрита", "Эта сделка уже закрыта",
                    "That trade is already closed"),
    "firstStep":   ("Це перший крок", "Это первый шаг", "This is the first step"),
    "shotOk":      ("Скрін прийняв (%d). Можна ще один або далі.",
                    "Скрин принял (%d). Можно ещё один или дальше.",
                    "Got the screenshot (%d). Send another or continue."),
    "shotAdded":   ("Скрін прийняв — додам до цієї угоди.",
                    "Скрин принял — добавлю к этой сделке.",
                    "Got it — I will attach it to this trade."),
    "shotFailed":  ("Не вдалось забрати картинку. Спробуй ще раз.",
                    "Не получилось забрать картинку. Попробуй ещё раз.",
                    "Could not fetch the image. Try again."),
    "saved":       ("Записав у журнал ✍️", "Записал в журнал ✍️", "Saved to the journal ✍️"),
    "openIt":      ("Подивитись: ", "Посмотреть: ", "Open: "),
    "noPair":      ("Без пари не запишу — почни спочатку кнопкою.",
                    "Без пары не запишу — начни заново кнопкой.",
                    "No pair, no trade — start again with the button."),

    # ---- емоції (підписи; у журнал іде українське написання) ----
    "emSp":        ("Спокій", "Спокойствие", "Calm"),
    "emVp":        ("Впевненість", "Уверенность", "Confidence"),
    "emZh":        ("Жадібність", "Жадность", "Greed"),
    "emSt":        ("Страх", "Страх", "Fear"),
    "emAz":        ("Азарт", "Азарт", "Thrill"),
    "emPm":        ("Помста", "Месть", "Revenge"),
    "emNd":        ("Нудьга", "Скука", "Boredom"),
    "emFm":        ("ФОМО", "ФОМО", "FOMO"),

    # ---- питання про емоцію після угоди ----
    "emAsk":       ("Записав угоду: %s\nЯку емоцію відчував під час неї?",
                    "Записал сделку: %s\nКакую эмоцию ты испытывал во время неё?",
                    "Trade saved: %s\nWhat did you feel during it?"),
    "emSaved":     ("Записав емоцію: %s ✍️", "Записал эмоцию: %s ✍️",
                    "Emotion saved: %s ✍️"),
    "emTaken":     ("Емоцію вже записано", "Эмоция уже записана",
                    "That emotion is already saved"),
    "emNoTrade":   ("Угоду не знайдено", "Сделка не найдена", "Trade not found"),
    "emFree":      ("Напиши в чат, що відчував — запишу як є.",
                    "Напиши в чат, что чувствовал — запишу как есть.",
                    "Tell me what you felt — I will save it as is."),
    "emManyOpen":  ("Зараз чекаю емоції по %d угодах — натисни кнопку під "
                    "потрібним повідомленням, щоб я не переплутав.",
                    "Сейчас жду эмоции по %d сделкам — нажми кнопку под нужным "
                    "сообщением, чтобы я не перепутал.",
                    "I am waiting on %d trades — tap the button under the right "
                    "message so I do not mix them up."),
    "noJournal":   ("Журнал не прив'язаний", "Журнал не привязан",
                    "No journal linked"),
}

ORDER = ("uk", "ru", "en")


def t(lang, key, *args):
    """Фраза потрібною мовою. Невідома мова — українська, як усюди в боті."""
    row = PHRASES.get(key)
    if not row:
        return key
    i = ORDER.index(lang) if lang in ORDER else 0
    text = row[i]
    return (text % args) if args else text.replace("%%", "%")


def of_tg(tg_id):
    """Мова людини за її телеграм-номером.

    Пише її bot.user_lang після кожного повідомлення, тому окремо питати
    нічого не треба — беремо готове. Немає запису (людина ще нічого не
    писала) — українська.
    """
    if not tg_id:
        return DEFAULT
    try:
        return db.meta_get("lang:%s" % tg_id, "") or DEFAULT
    except Exception:
        return DEFAULT


def of(user):
    """Те саме, але для рядка користувача з бази."""
    return of_tg((user or {}).get("telegram_id"))

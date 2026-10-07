# -*- coding: utf-8 -*-
"""
Postgres (Neon). Соединения короткоживущие: и сайт, и бот ходят в одну базу
из разных процессов, держать общее соединение между ними незачем.
"""
import datetime
import secrets
import threading

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

import tidy
from config import (DATABASE_URL, DB_POOL_MAX, EARLY_MIGRATION,
                    FREE_BT, FREE_TRADES, IMPORT_WINDOW_DAYS)

# Текстовые поля сделки. Порядок важен: по нему строятся INSERT/UPDATE.
TEXT_FIELDS = ["pair", "date", "session", "position", "entry_model", "bias", "setup",
               "direction_type", "result", "account", "entry_details", "notes", "mistakes",
               "comments", "emotion", "bt_run", "notion_id", "import_id", "ts"]
# rr_plan — скільки дав би тейк, якби досидів. Із різниці з rr виходить,
# скільки людина лишила на столі, вийшовши рукою.
NUM_FIELDS = ["rr", "risk", "rr_plan"]
FIELDS = TEXT_FIELDS + NUM_FIELDS

# Поля, написания в которых можно свести к одному (tidy.py). Список закрытый:
# имя колонки уходит прямо в SQL.
TIDY_FIELDS = ("pair", "session", "entry_model", "setup", "account")

LINK_CODE_TTL = datetime.timedelta(minutes=15)


# Пул соединений.
#
# Раньше каждый запрос открывал соединение и тут же закрывал. Пока
# пользователь один — незаметно, но на полусотне человек это упирается:
# рукопожатие с Postgres стоит дороже самого запроса, а у базы кончается
# лимит соединений.
#
# Пул держит несколько соединений открытыми и выдаёт их по кругу.
# psycopg_pool необязателен: если его нет (старое окружение), работаем
# по-прежнему, только медленнее.
#
# Размер задаётся в config (DB_POOL_MAX). Было жёстко 8 — этого хватало,
# пока сайт обслуживал единицы; на сотне человек восьмёрка становится
# горлышком: запросы выстраиваются в очередь за свободным соединением,
# хотя база при этом скучает.
try:
    from psycopg_pool import ConnectionPool
except ImportError:
    ConnectionPool = None

_pool = None
_pool_lock = threading.Lock()


def _get_pool():
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = ConnectionPool(
                    DATABASE_URL,
                    min_size=2, max_size=DB_POOL_MAX,
                    max_idle=300,               # Neon рвёт простаивающие сам
                    kwargs={"row_factory": dict_row},
                    check=ConnectionPool.check_connection,
                    open=True)
    return _pool


def connect():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL не задан — заполни .env (см. .env.example)")
    if ConnectionPool is None:
        return psycopg.connect(DATABASE_URL, row_factory=dict_row)
    return _get_pool().connection()


def now():
    return datetime.datetime.now(datetime.timezone.utc)


# ---------------------------------------------------------------- схема ----

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id                BIGSERIAL PRIMARY KEY,
  email             TEXT NOT NULL,
  nickname          TEXT NOT NULL,
  email_norm        TEXT NOT NULL UNIQUE,
  pw_hash           TEXT NOT NULL,
  pw_salt           TEXT NOT NULL,
  pw_iters          INTEGER NOT NULL,
  telegram_id       BIGINT UNIQUE,
  telegram_username TEXT,
  digest_hour       SMALLINT NOT NULL DEFAULT 8,
  digest_minute     SMALLINT NOT NULL DEFAULT 0,
  digest_enabled    BOOLEAN NOT NULL DEFAULT TRUE,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS users_nickname_norm ON users (lower(nickname));

CREATE TABLE IF NOT EXISTS trades (
  id                    TEXT PRIMARY KEY,
  user_id               BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  "pair"                TEXT NOT NULL DEFAULT '',
  "date"                TEXT NOT NULL DEFAULT '',
  "session"             TEXT NOT NULL DEFAULT '',
  "position"            TEXT NOT NULL DEFAULT '',
  "entry_model"         TEXT NOT NULL DEFAULT '',
  "bias"                TEXT NOT NULL DEFAULT '',
  "setup"               TEXT NOT NULL DEFAULT '',
  "direction_type"      TEXT NOT NULL DEFAULT '',
  "result"              TEXT NOT NULL DEFAULT '',
  "account"             TEXT NOT NULL DEFAULT '',   -- на каком счёте набиралась: имя пишет человек
  "entry_details"       TEXT NOT NULL DEFAULT '',
  "notes"               TEXT NOT NULL DEFAULT '',
  "mistakes"            TEXT NOT NULL DEFAULT '',
  "comments"            TEXT NOT NULL DEFAULT '',
  "emotion"             TEXT NOT NULL DEFAULT '',
  "notion_id"           TEXT NOT NULL DEFAULT '',   -- id записи в Notion: чтобы импорт не задваивал
  "import_id"           TEXT NOT NULL DEFAULT '',   -- каким переносом принесена: чтобы можно было отменить
  rr                    DOUBLE PRECISION,
  risk                  DOUBLE PRECISION,
  rr_plan               DOUBLE PRECISION,           -- сколько дал бы тейк, если бы досидел
  screenshots           JSONB NOT NULL DEFAULT '[]'::jsonb,
  hidden                BOOLEAN NOT NULL DEFAULT FALSE,
  emotion_prompt_status TEXT NOT NULL DEFAULT 'na',
  emotion_prompt_msg_id BIGINT,
  emotion_prompt_at     TIMESTAMPTZ,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS trades_user ON trades (user_id);
CREATE INDEX IF NOT EXISTS trades_user_date ON trades (user_id, "date");
CREATE INDEX IF NOT EXISTS trades_pending_emotion ON trades (user_id)
  WHERE emotion_prompt_status = 'pending';

CREATE TABLE IF NOT EXISTS link_codes (
  code       TEXT PRIMARY KEY,
  user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ NOT NULL,
  used_at    TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS notified_events (
  user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  event_key   TEXT NOT NULL,
  kind        TEXT NOT NULL,
  notified_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, event_key, kind)
);

CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

-- Своими словами ответ храним отдельно: в emotion лежит категория для статистики,
-- а тут — как человек это сказал.
ALTER TABLE trades ADD COLUMN IF NOT EXISTS emotion_raw TEXT;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS "notion_id" TEXT NOT NULL DEFAULT '';
ALTER TABLE trades ADD COLUMN IF NOT EXISTS "import_id" TEXT NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS trades_import ON trades (user_id, "import_id");

-- Счёт, на котором набиралась сделка, и RR, на который человек рассчитывал.
-- У всего, что записано раньше, счёт пустой: задним числом не подписываем.
ALTER TABLE trades ADD COLUMN IF NOT EXISTS "account" TEXT NOT NULL DEFAULT '';
ALTER TABLE trades ADD COLUMN IF NOT EXISTS rr_plan DOUBLE PRECISION;

-- Журнал можно открыть другим: тогда его смотрят по ссылке /u/<ник>.
-- По умолчанию закрыт: открытость человек включает сам.
ALTER TABLE users ADD COLUMN IF NOT EXISTS public_journal BOOLEAN NOT NULL DEFAULT FALSE;
-- дозвіл забрати свою ТС за посиланням на неї (кнопка «Скопіювати до себе»)
ALTER TABLE users ADD COLUMN IF NOT EXISTS ts_copy BOOLEAN NOT NULL DEFAULT FALSE;
-- стратегія, відкрита на сайті востаннє: туди ж пише угоди бот
ALTER TABLE users ADD COLUMN IF NOT EXISTS ts_active TEXT NOT NULL DEFAULT '';
-- дозвіл забрати свою ТС за посиланням на неї (кнопка «Скопіювати до себе»)

-- Опитування «звідки дізнався» жило один день і прибране — колонку теж.
ALTER TABLE users DROP COLUMN IF EXISTS heard_from;

-- Недописана угода, яку людина заповнює в боті по кроках. Лежить у базі,
-- а не в пам'яті процесу: виклад коду перезапускає бота, і чернетка,
-- набрана до половини, інакше зникала б разом з ним.
-- На людину одна: другу угоду починають, коли попередню записали чи кинули.
-- Одноразові посилання з листів: новий пароль (kind='password') і
-- підтвердження пошти (kind='confirm'). Механіка в них однакова, різні
-- лише час життя й те, що робиться на тому кінці, — тому тримаємо в
-- одній таблиці.
-- Тримаємо відбиток ключа, а не сам ключ: витік бази не має відкривати
-- чужі акаунти. Рядок лишається й після використання — по ньому видно,
-- що посилання вже спрацювало, і другий раз воно не відкриється.
CREATE TABLE IF NOT EXISTS auth_links (
  token_hash TEXT PRIMARY KEY,
  user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind       TEXT NOT NULL DEFAULT 'password',
  expires_at TIMESTAMPTZ NOT NULL,
  used_at    TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS auth_links_user ON auth_links (user_id, kind);

-- Попередня назва тієї ж таблиці. Жила рівно один день і тільки на моїй
-- машині — на сервер не потрапила, тому просто прибираємо.
DROP TABLE IF EXISTS pw_resets;

-- Часовий пояс людини. Календар новин і розсилки бота живуть у ньому:
-- раніше й там, і там був зашитий Київ, і той, хто дивиться журнал із
-- Варшави чи Дубая, читав чужий час. 'Europe/Kyiv' лишається за
-- замовчуванням — саме так усе працювало до появи цієї колонки.
ALTER TABLE users ADD COLUMN IF NOT EXISTS tz TEXT NOT NULL DEFAULT 'Europe/Kyiv';

-- Чи підтвердив людина свою пошту, перейшовши за посиланням із листа.
-- NULL — ще ні. Тим, хто вже був у журналі до появи підтвердження,
-- ставимо позначку одноразово в init(): просити їх зайвий раз нема за що.
ALTER TABLE users ADD COLUMN IF NOT EXISTS email_confirmed_at TIMESTAMPTZ;

-- «Покоління» входів людини. Номер лежить і тут, і в кукі; кука зі старим
-- номером більше не пускає. Зміна пароля, 2FA чи кнопка «вийти на всіх
-- пристроях» додає одиницю — і всі інші пристрої вилітають.
ALTER TABLE users ADD COLUMN IF NOT EXISTS session_gen INTEGER NOT NULL DEFAULT 0;

-- Двофакторний вхід кодом із застосунку (Google Authenticator, Authy).
-- twofa_secret — ключ застосунку (base32). Не відбиток, як у пароля: з
-- нього щоразу рахується код, тож сервер мусить мати його самого.
-- twofa_backup — відбитки запасних кодів (sha256), кожен одноразовий.
-- twofa_last_step — крок часу останнього прийнятого коду: той самий код
-- удруге не пройде, навіть поки він ще живий.
ALTER TABLE users ADD COLUMN IF NOT EXISTS twofa_secret TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS twofa_enabled_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS twofa_backup JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE users ADD COLUMN IF NOT EXISTS twofa_last_step BIGINT;

-- Профіль: фото (ім'я файла в таблиці files, NULL — буква ніка на кольоровому
-- тлі) і коли востаннє міняли нік.
ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS nick_changed_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS trade_drafts (
  user_id    BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  chat_id    BIGINT NOT NULL,
  step       TEXT NOT NULL DEFAULT '',
  data       JSONB NOT NULL DEFAULT '{}'::jsonb,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Реальная сделка или бэктест. Пусто — реальная: всё, что записано до
-- появления бэктеста, остаётся торговлей, задним числом ничего не метим.
-- Список значений держим в Python (_trade_values, clean_trade), а не в
-- CHECK: добавить ограничение «если ещё нет» одной строкой Postgres не даёт.
ALTER TABLE trades ADD COLUMN IF NOT EXISTS "kind" TEXT NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS trades_user_kind ON trades (user_id, "kind");

-- Подпись прогона: «EURUSD H1, sweep+fvg, 2023». Одной строкой вместо пары
-- дат — человек сам пишет, что именно гонял. У реальных сделок пусто.
ALTER TABLE trades ADD COLUMN IF NOT EXISTS "bt_run" TEXT NOT NULL DEFAULT '';
-- стратегія угоди: "" — перша, інакше id з ts_multi (ts_store.py)
ALTER TABLE trades ADD COLUMN IF NOT EXISTS "ts" TEXT NOT NULL DEFAULT '';

-- Угоди з Notion, які людина прибрала з журналу руками. Тримаємо не саму
-- угоду, а позначки, за якими перенесення її впізнає: id запису в Notion,
-- відбиток (день, інструмент, напрямок, результат) і те, яким перенесенням
-- вона приїхала.
--
-- Навіщо: базу можна перенести ще раз (кнопка в «Підключеннях»), а що вже
-- перенесено — рахувалося по тому, що лежить у журналі. Прибрана угода
-- зникала з цього рахунку й наступного разу приїжджала знову, наче
-- нова. Людина викидає — журнал відрощує назад.
--
-- Рядки прив'язані до перенесення: коли базу знімають цілком («прибрати»),
-- її могильник теж прибирається — після цього перенести базу заново можна
-- повністю.
CREATE TABLE IF NOT EXISTS notion_gone (
  id         BIGSERIAL PRIMARY KEY,
  user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  notion_id  TEXT NOT NULL DEFAULT '',
  import_id  TEXT NOT NULL DEFAULT '',
  mark       TEXT NOT NULL DEFAULT '',
  removed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS notion_gone_user ON notion_gone (user_id);

-- ---------------------------------------------------------------- підписка --
--
-- Журнал став платним: безкоштовно людина записує перші 20 справжніх угод і
-- окремо 20 прогонів бектесту, далі — підписка. Нічого не видаляється:
-- закриваються тільки нові записи, перенесення з Notion і те, що коштує
-- грошей за модель (помічник, розбори).
--
-- Чому лічильник, а не COUNT(*) по угодах: delete_trade прибирає рядок
-- фізично. По COUNT людина записала б 20, прибрала всі й записала ще 20 —
-- і так без кінця. Ці лічильники тільки ростуть.
--
-- Ліміти зберігаються в кожного свої (…_cap), щоб адмін міг дати бонус
-- одній людині, не чіпаючи решту. Самі суми тарифів лежать у config.py:
-- змінити ціну не означає чіпати схему.
ALTER TABLE users ADD COLUMN IF NOT EXISTS plan TEXT NOT NULL DEFAULT 'free';
ALTER TABLE users ADD COLUMN IF NOT EXISTS paid_until TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS free_trades_used INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS free_trades_cap INTEGER NOT NULL DEFAULT 20;
ALTER TABLE users ADD COLUMN IF NOT EXISTS free_bt_used INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS free_bt_cap INTEGER NOT NULL DEFAULT 20;
ALTER TABLE users ADD COLUMN IF NOT EXISTS imports_used INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS imports_cap INTEGER NOT NULL DEFAULT 3;
-- Стеля була 30, стала 20 (власники, 29.09.2026). ADD COLUMN IF NOT EXISTS
-- на вже наявній колонці нічого не робить — DEFAULT у ній лишився б старий,
-- і кожен новий акаунт знову заводився б з тридцяткою. Тому окремим рядком.
ALTER TABLE users ALTER COLUMN free_trades_cap SET DEFAULT 20;
ALTER TABLE users ALTER COLUMN free_bt_cap SET DEFAULT 20;
-- Набір цін: 'std' — звичайні, 'early' — назавжди дешевші для тих, хто був
-- у журналі до появи платних підписок. own_price_cents — разова своя ціна
-- (NULL — рахуємо за набором).
ALTER TABLE users ADD COLUMN IF NOT EXISTS price_plan TEXT NOT NULL DEFAULT 'std';
ALTER TABLE users ADD COLUMN IF NOT EXISTS own_price_cents INTEGER;
-- Доки триває вікно перенесення з Notion. NULL — рахуємо звичайно, 30 днів від
-- реєстрації. Дата тут потрібна «раннім»: вони зареєструвались місяці тому, і
-- від created_at вікно в них було б зачинене ще до першого запуску підписок.
ALTER TABLE users ADD COLUMN IF NOT EXISTS imports_until TIMESTAMPTZ;
-- Звідки реєструвались: за парою «адреса + відбиток пристрою» ловимо другий
-- безкоштовний акаунт того самого автора. Сам по собі збіг адреси нічого не
-- означає (мобільні оператори дають одну адресу тисячам людей) — він лише
-- лишає позначку в адмінці.
ALTER TABLE users ADD COLUMN IF NOT EXISTS signup_ip TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS signup_device TEXT;
-- Чому саме цій людині дали бонус чи свою ціну: щоб через місяць не
-- гадати, що це було.
ALTER TABLE users ADD COLUMN IF NOT EXISTS billing_note TEXT;
-- коли людині дали Special (довічну): в адмінці видно, кому й відколи
ALTER TABLE users ADD COLUMN IF NOT EXISTS special_since TIMESTAMPTZ;
-- промокод: який ввели (лишається й після оплати — видно, хто прийшов від
-- партнера) і коли по ньому заплатили; після оплати вдруге не приймається
ALTER TABLE users ADD COLUMN IF NOT EXISTS promo_code TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS promo_used_at TIMESTAMPTZ;
-- Пошта, зведена до однієї скриньки (див. email_key): без хвоста після
-- «+», а в gmail ще й без крапок. За email_norm людина заводила скільки
-- завгодно безкоштовних журналів на той самий ящик.
--
-- Індекс навмисно не унікальний: у базі вже лежать такі пари, заведені до
-- цієї перевірки, і UNIQUE не дав би застосувати схему. Нових не буде —
-- реєстрація дивиться сюди перед створенням.
ALTER TABLE users ADD COLUMN IF NOT EXISTS email_key TEXT NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS users_email_key ON users (email_key);

-- Звернення до моделі: скільки витрачено у поточному вікні й коли вікно
-- закінчується. Розділи журналу відкриті всі, а платне — саме це: кожна
-- відповідь помічника, розбору чи звірки коштує нам грошей.
--
-- Вікно рухається саме: перше звернення після ai_reset_at обнуляє
-- лічильник і відсуває дату ще на місяць. Окремого прибирання за
-- розкладом не треба — ніхто не ходить по базі вночі, щоб обнулити.
ALTER TABLE users ADD COLUMN IF NOT EXISTS ai_used INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS ai_cap INTEGER NOT NULL DEFAULT 15;
ALTER TABLE users ADD COLUMN IF NOT EXISTS ai_reset_at TIMESTAMPTZ;

-- Номер людини на боці платіжки. Треба рівно для одного: відкрити їй
-- кабінет Creem, де вона сама скасує продовження чи змінить картку. Перший
-- платіж його й приносить — до першого платежу кабінету нема чого показувати.
ALTER TABLE users ADD COLUMN IF NOT EXISTS creem_customer TEXT NOT NULL DEFAULT '';

-- Замок на акаунт, який ставить і знімає тільки власник руками з /admin.
-- Текст у колонці — те, що людина побачить на весь екран замість журналу;
-- порожньо означає, що замка немає. Два стани в одній колонці навмисно:
-- замок без слів нічим не кращий за тишу, а слова без замка нічого не
-- тримають, тож і зберігати їх окремо нема сенсу.
ALTER TABLE users ADD COLUMN IF NOT EXISTS lock_note TEXT NOT NULL DEFAULT '';

-- Події платіжки. Ключ — її власний id події: та сама подія приходить
-- повторно (платіжки шлють вебхук, доки не отримають 200), і другий раз
-- вона має нічого не змінити.
CREATE TABLE IF NOT EXISTS payments (
  id           TEXT PRIMARY KEY,
  user_id      BIGINT REFERENCES users(id) ON DELETE SET NULL,
  event        TEXT NOT NULL DEFAULT '',
  amount_cents INTEGER,
  currency     TEXT NOT NULL DEFAULT 'EUR',
  raw          JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS payments_user ON payments (user_id, created_at);

-- Уся історія реєстрацій за адресами, а не тільки остання: users.signup_ip
-- в людини один, а знати треба всі акаунти, що приходили з цієї адреси.
CREATE TABLE IF NOT EXISTS signup_ips (
  id         BIGSERIAL PRIMARY KEY,
  ip         TEXT NOT NULL DEFAULT '',
  device     TEXT NOT NULL DEFAULT '',
  user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS signup_ips_ip ON signup_ips (ip);
CREATE INDEX IF NOT EXISTS signup_ips_user ON signup_ips (user_id);

-- Рахунки на оплату криптою. Гроші від усіх приходять на одну нашу
-- адресу, і в переказі не написано, хто заплатив, — тому кожному рахунку
-- дається трохи своя сума (11,9943 замість 11,99), і саме останні цифри
-- працюють номером. Звідси UNIQUE на суму серед тих, що ще чекають:
-- двох однакових сум одночасно бути не може, інакше оплату зарахували б
-- не тому.
--
-- Суму тримаємо цілим числом найдрібніших часток (у USDT їх мільйон на
-- монету): у дробових числах «11,99» не завжди дорівнює «11,99».
CREATE TABLE IF NOT EXISTS crypto_invoices (
  id         BIGSERIAL PRIMARY KEY,
  user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  plan       TEXT NOT NULL,
  units      BIGINT NOT NULL,
  status     TEXT NOT NULL DEFAULT 'new',   -- new | paid | expired
  tx         TEXT NOT NULL DEFAULT '',
  payer      TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ NOT NULL,
  paid_at    TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS crypto_inv_user ON crypto_invoices (user_id, created_at);
CREATE INDEX IF NOT EXISTS crypto_inv_open ON crypto_invoices (status, expires_at);
-- Той самий переказ не має закрити два рахунки.
CREATE UNIQUE INDEX IF NOT EXISTS crypto_inv_tx ON crypto_invoices (tx)
    WHERE tx <> '';
-- Дві однакові суми одночасно — заборонені, поки обидві чекають оплати.
CREATE UNIQUE INDEX IF NOT EXISTS crypto_inv_units ON crypto_invoices (units)
    WHERE status = 'new';

-- Перекази, які прийшли, але не збіглися з жодним рахунком: людина
-- округлила суму або заплатила, коли рахунок уже згорів. Гроші в нас,
-- тому такий переказ не можна просто загубити — він лежить тут і видно
-- його в адмінці, звідки прив'язується до людини руками.
CREATE TABLE IF NOT EXISTS crypto_orphans (
  tx         TEXT PRIMARY KEY,
  units      BIGINT NOT NULL,
  payer      TEXT NOT NULL DEFAULT '',
  at_ms      BIGINT NOT NULL DEFAULT 0,
  settled_to BIGINT REFERENCES users(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Адреси, які адмін дозволив руками: «це інша людина, пропускай». Без
-- цього списку сімʼя за одним роутером чи двоє з одного офісу не змогли б
-- завести другий акаунт.
CREATE TABLE IF NOT EXISTS ip_allow (
  ip         TEXT PRIMARY KEY,
  note       TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Бан з адмінки: адреса, пристрій (хеш) і пошта людини, яку прибрали.
-- Окремою таблицею, бо signup_ips зникає разом з акаунтом.
CREATE TABLE IF NOT EXISTS bans (
  kind       TEXT NOT NULL,              -- ip | device | email
  value      TEXT NOT NULL,
  note       TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (kind, value)
);
"""


def init():
    with connect() as conn:
        conn.execute(SCHEMA)
        conn.commit()
    _grandfather_emails()
    _fill_email_keys()
    _start_limits()
    _grandfather_early()


def _fill_email_keys():
    """Проставити email_key тим, хто заведений до появи колонки.

    Без вимикача й без позначки: тут не роздається нічого й нічого не
    втрачається — рядок рахується з пошти, яка вже лежить у базі. Порожні
    добираємо на кожному запуску, бо так само доводиться чинити рядки,
    що приїхали в базу руками.
    """
    with connect() as conn:
        rows = conn.execute("SELECT id, email FROM users WHERE email_key=''").fetchall()
        for r in rows:
            conn.execute("UPDATE users SET email_key=%s WHERE id=%s",
                         (email_key(r["email"]), r["id"]))
        if rows:
            conn.commit()
            print("пошта зведена до скриньки: %d рядків" % len(rows), flush=True)


# Запуск лімітів одним запитом — щоб перевірка ганяла саме той текст, який
# піде на бій, а не схожий на нього.
LIMITS_SQL = """
UPDATE users SET free_trades_cap = CASE WHEN free_trades_cap = 30 THEN %s
                                        ELSE free_trades_cap END,
                 free_bt_cap     = CASE WHEN free_bt_cap = 30 THEN %s
                                        ELSE free_bt_cap END,
                 free_trades_used = 0, free_bt_used = 0, imports_used = 0,
                 ai_used = 0, ai_reset_at = NULL
"""


def _start_limits():
    """Момент, з якого ліміти починають рахуватись. До нього їх немає.

    Робить дві речі разом, бо це одна подія — викладка:

    Перше — опускає стелю з тридцятки до двадцятки (рішення власників
    29.09.2026). DEFAULT у схемі стосується тільки нових рядків, а в тих,
    хто вже заведений, у колонці лежить стара тридцятка, і розділ
    «Підписка» показував би 30 навіть після правки config. Беремо рівно
    тридцятку: у кого стеля інша — це бонус від адміна, його не чіпаємо.

    Друге — обнуляє лічильники всім без винятку. Угоди, записані до
    викладки, в ліміт не йдуть: люди писали їх, коли ліміту не було, і
    відлік для всіх починається з нуля з цієї хвилини. Саме «всім», а не
    тільки набору 'std', — інакше той, кого вже перевели на ранні ціни чи
    промокод, стартував би з витраченим.

    Записане не зникає: закриваються тільки нові записи, весь журнал
    лишається на місці й видно в аналітиці.

    За вимикачем EARLY_MIGRATION — тим самим, що й знижка «раннім», бо це
    одна й та сама викладка, і двома вимикачами один з них забули б.
    Робоча копія ходить у бойову базу, тож без вимикача ліміт живим людям
    запустив би місцевий прогін, а не викладка. Позначка в meta не дасть
    спрацювати вдруге — відлік не перезапуститься на наступному рестарті.
    """
    if not EARLY_MIGRATION or meta_get("limits_started"):
        return
    with connect() as conn:
        conn.execute(LIMITS_SQL, (FREE_TRADES, FREE_BT))
        conn.commit()
    meta_set("limits_started", now().isoformat())


def _grandfather_emails():
    """Хто зареєструвався до появи підтвердження — вважається підтвердженим.

    Робимо це рівно один раз (позначка в meta), інакше кожен запуск
    підтверджував би й тих, хто щойно зареєструвався й ще не відкрив листа.
    """
    if meta_get("emails_grandfathered"):
        return
    with connect() as conn:
        conn.execute("UPDATE users SET email_confirmed_at=created_at "
                     "WHERE email_confirmed_at IS NULL")
        conn.commit()
    meta_set("emails_grandfathered", "1")


# Сама міграція «ранніх» одним запитом — щоб перевірка ганяла саме той
# текст, який піде на бій, а не схожий на нього.
EARLY_SQL = """
UPDATE users SET price_plan='early',
       imports_until=now() + (%s || ' days')::interval
 WHERE price_plan='std'
"""


def _grandfather_early():
    """Хто був у журналі до платних підписок — той «ранній»: знижка назавжди.

    Спрацьовує рівно один раз (позначка в meta), інакше кожен перезапуск
    роздавав би знижку й тим, хто прийшов уже на платне.

    Не при першому запуску, а за вимикачем EARLY_MIGRATION: робоча копія
    ходить у ту саму базу, що й бій, і без вимикача знижку роздав би
    місцевий прогін — за дні до самої викладки.

    Лічильники тут не чіпаємо: їх обнуляє _start_limits(), і не цим людям,
    а всім одразу — відлік ліміту починається з викладки для кожного.
    Вікно перенесення з Notion відкриваємо наново: від created_at воно в
    «ранніх» давно минуло.

    Оплачене не чіпаємо: plan і paid_until лишаються як є. Партнерський
    набір теж: WHERE price_plan='std' обходить тих, кого перевів промокод
    FX LAB, — ціна в них та сама, а от в обліку партнера вони мусять
    лишитись своїми.
    """
    if not EARLY_MIGRATION or meta_get("early_marked"):
        return
    with connect() as conn:
        conn.execute(EARLY_SQL, (IMPORT_WINDOW_DAYS,))
        conn.commit()
    meta_set("early_marked", now().isoformat())


# ----------------------------------------------------------------- meta ----

def meta_get(key, default=None):
    with connect() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key=%s", (key,)).fetchone()
    return row["value"] if row else default


def meta_set(key, value):
    with connect() as conn:
        conn.execute("INSERT INTO meta (key, value) VALUES (%s, %s) "
                     "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value",
                     (key, str(value)))
        conn.commit()


# ------------------------------------------------------------ пользователи ----

# Поштові служби, де крапки в імені скриньки нічого не означають: у них
# «i.van@» і «ivan@» — той самий ящик.
DOTLESS_MAIL = ("gmail.com", "googlemail.com")


def email_key(email):
    """Пошта, зведена до однієї скриньки.

    email_norm — це просто нижній регістр, і для входу цього досить. Але
    для «один безкоштовний журнал на людину» цього мало: «ivan+1@gmail»,
    «ivan+2@gmail» і «i.v.a.n@gmail» — три різні рядки й один живий ящик.
    Двадцятка множилась на стільки, скільки людині не ліньки придумати
    хвостиків.

    Що робимо: хвіст після «+» відкидаємо скрізь (так домовились усі
    великі служби), крапки прибираємо тільки там, де вони справді нічого
    не значать — інакше зіпсуємо чужі адреси, де крапка є частиною імені.
    """
    e = (email or "").strip().lower()
    if "@" not in e:
        return e
    box, dom = e.rsplit("@", 1)
    box = box.split("+", 1)[0]
    if dom in DOTLESS_MAIL:
        box = box.replace(".", "")
    return (box + "@" + dom) if box else e


def user_by_email_key(email):
    """Чи є вже журнал на цю саму скриньку — з будь-якими хвостиками.

    Дивимось у email_key, а не в email_norm: саме тут ловиться той, хто
    заводить другий безкоштовний акаунт на ту саму пошту.
    """
    key = email_key(email)
    if not key:
        return None
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE email_key=%s LIMIT 1", (key,)).fetchone()


def create_user(email, nickname, pw_hash, pw_salt, pw_iters):
    with connect() as conn:
        row = conn.execute(
            "INSERT INTO users (email, nickname, email_norm, email_key, "
            "pw_hash, pw_salt, pw_iters) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING *",
            (email, nickname, email.strip().lower(), email_key(email),
             pw_hash, pw_salt, pw_iters)).fetchone()
        conn.commit()
    return row


def get_user(uid):
    with connect() as conn:
        return conn.execute("SELECT * FROM users WHERE id=%s", (uid,)).fetchone()


def get_user_by_login(login):
    """Вход по почте или по нику — на экране входа одно поле на оба варианта."""
    key = (login or "").strip().lower()
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE email_norm=%s OR lower(nickname)=%s LIMIT 1",
            (key, key)).fetchone()


def get_user_by_email(email):
    """Тільки за поштою — для «забув пароль».

    Ніком тут не шукаємо навмисне: посилання йде на пошту, тож людина
    все одно має її пам'ятати, а пошук за ніком дав би змогу перевіряти
    чужі ніки на існування.
    """
    key = (email or "").strip().lower()
    if not key:
        return None
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE email_norm=%s LIMIT 1", (key,)).fetchone()


def get_user_by_nick(nick):
    """Хозяин открытого журнала по нику из ссылки /u/<ник>.
    Ник ищем без учёта регистра — так же, как при входе."""
    key = (nick or "").strip().lower()
    if not key:
        return None
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE lower(nickname)=%s LIMIT 1", (key,)).fetchone()


def set_lock(user_id, note):
    """Замок на акаунт: текст — поставити, порожньо — зняти.

    Ставить і знімає тільки власник руками з /admin. Сама людина зняти
    його не може нічим: замок перевіряється на сервері, а не в браузері.
    """
    with connect() as conn:
        conn.execute("UPDATE users SET lock_note=%s WHERE id=%s",
                     ((note or "").strip(), user_id))
        conn.commit()


def locked_users():
    """{id: текст} по всіх, у кого стоїть замок.

    Запитом по всіх, а не по одному: замкнених одиниці (зазвичай нікого),
    і тримати їх у пам'яті дешевше, ніж питати базу на кожен запит кожної
    людини (див. app.py: _locked).
    """
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, lock_note FROM users WHERE lock_note <> ''").fetchall()
    return {r["id"]: r["lock_note"] for r in rows}


def set_nickname(user_id, nick):
    """Новий нік. False — зайнятий (унікальний індекс на lower(nickname))."""
    try:
        with connect() as conn:
            conn.execute("UPDATE users SET nickname=%s, nick_changed_at=now() WHERE id=%s",
                         (nick, user_id))
            conn.commit()
        return True
    except psycopg.errors.UniqueViolation:
        return False


def set_avatar(user_id, name):
    """Нове фото (або None — прибрати). Повертає ім'я попереднього файла."""
    with connect() as conn:
        old = conn.execute("SELECT avatar FROM users WHERE id=%s", (user_id,)).fetchone()
        conn.execute("UPDATE users SET avatar=%s WHERE id=%s", (name, user_id))
        conn.commit()
    return old["avatar"] if old else None


def profile_stats(user_id, today, weeks=12, tz=None):
    """Цифри для профілю — про звичку вести журнал, а не про прибуток.

    today — дата людини в її поясі (datetime.date): «серія» й карта
    активності рахуються в її днях, а не в годиннику сервера.

    День у карті світиться, якщо людина того дня хоч щось записала:
    угода (пропуск теж рахується — це теж запис), розбір дня або
    посилання, яким вона поділилась. Рішення власника 16.09.2026:
    раніше світились тільки дні з угодами, вихідних у карті не було
    зовсім, і цифри поруч не сходились між собою.

    Вихідні тепер у карті є (крипта торгується і в суботу), але порожній
    вихідний серію не рве — ринок здебільшого зачинений.
    """
    import datetime as _dt
    with connect() as conn:
        t = conn.execute(
            """SELECT count(*) FILTER (WHERE result<>'Skip') AS trades,
                      count(DISTINCT left("date", 10)) AS days,
                      min(left("date", 10)) FILTER (WHERE "date"<>'') AS first
               FROM trades WHERE user_id=%s""", (user_id,)).fetchone()
        per_day = conn.execute(
            """SELECT left("date", 10) AS d, count(*) AS n FROM trades
               WHERE user_id=%s AND "date" ~ '^\\d{4}-\\d{2}-\\d{2}'
               GROUP BY 1 ORDER BY 1""", (user_id,)).fetchall()
        hundredth = conn.execute(
            """SELECT left("date", 10) AS d FROM trades
               WHERE user_id=%s AND result<>'Skip' AND "date" ~ '^\\d{4}-\\d{2}-\\d{2}'
               ORDER BY "date", created_at OFFSET 99 LIMIT 1""", (user_id,)).fetchone()
        pairs = conn.execute(
            """SELECT "pair", count(*) AS n FROM trades
               WHERE user_id=%s AND "pair"<>'' AND result<>'Skip'
               GROUP BY 1 ORDER BY n DESC, 1 LIMIT 3""", (user_id,)).fetchall()
        try:
            reviews = conn.execute(
                "SELECT count(*) AS n FROM day_notes WHERE user_id=%s AND data <> '{}'::jsonb",
                (user_id,)).fetchone()["n"]
            review_rows = conn.execute(
                "SELECT \"date\" AS d FROM day_notes WHERE user_id=%s AND data <> '{}'::jsonb",
                (user_id,)).fetchall()
        except psycopg.errors.UndefinedTable:
            conn.rollback()
            reviews, review_rows = 0, []
        try:
            share_rows = conn.execute(
                "SELECT created FROM shares WHERE user_id=%s", (user_id,)).fetchall()
        except psycopg.errors.UndefinedTable:
            conn.rollback()
            share_rows = []

    trades_day = {}
    for r in per_day:
        try:
            trades_day[_dt.date.fromisoformat(r["d"])] = r["n"]
        except ValueError:
            pass

    review_day = set()
    for r in review_rows:
        try:
            review_day.add(_dt.date.fromisoformat(str(r["d"])[:10]))
        except ValueError:
            pass

    # посилання прив'язані до миті створення, тож дату беремо в поясі людини
    shares_day = {}
    for r in share_rows:
        try:
            day = _dt.datetime.fromtimestamp(int(r["created"]), tz).date()
        except (ValueError, OSError, TypeError):
            continue
        shares_day[day] = shares_day.get(day, 0) + 1

    # скільки записів того дня — з цього й насиченість клітинки
    active = {}
    for src in (trades_day, shares_day):
        for day, n in src.items():
            active[day] = active.get(day, 0) + n
    for day in review_day:
        active[day] = active.get(day, 0) + 1

    day1 = _dt.timedelta(days=1)

    def step_back(d):
        """Крок назад по днях: порожні вихідні перестрибуємо — вони не рвуть
        серію. Вихідний із записом — звичайний день серії."""
        d -= day1
        while d.weekday() >= 5 and d not in active:
            d -= day1
        return d

    # серія: дні підряд із записами. Сьогодні ще без записів — не обрив,
    # рахуємо від попереднього дня.
    streak, d = 0, today
    while d.weekday() >= 5 and d not in active:
        d -= day1
    if d not in active:
        d = step_back(d)
    while d in active:
        streak += 1
        d = step_back(d)

    best, run, prev = 0, 0, None
    for day in sorted(active):
        run = run + 1 if prev is not None and step_back(day) == prev else 1
        best = max(best, run)
        prev = day

    # Календар активності (рішення власника 16.09.2026: сітка квадратиків
    # була незрозуміла, тепер це звичайний календар місяця). Віддаємо самі
    # дні із записами за останній рік — з них браузер малює будь-який місяць.
    since = today - _dt.timedelta(days=370)
    log = {}
    for day, n in active.items():
        if day < since or day > today:
            continue
        log[day.isoformat()] = {"t": trades_day.get(day, 0),
                                "r": 1 if day in review_day else 0,
                                "s": shares_day.get(day, 0), "n": n}

    # найраніший місяць, куди має сенс гортати
    oldest = min(active) if active else today
    log_from = max(oldest, since).isoformat()

    return {
        "trades": t["trades"] or 0, "days": t["days"] or 0, "reviews": reviews or 0,
        "streak": streak, "best_streak": max(best, streak),
        "first": t["first"] or None, "hundredth": hundredth["d"] if hundredth else None,
        "pairs": [[r["pair"], r["n"]] for r in pairs],
        "log": log, "log_from": log_from, "today": today.isoformat(),
    }


def set_ts_copy(user_id, on):
    with connect() as conn:
        conn.execute("UPDATE users SET ts_copy=%s WHERE id=%s", (bool(on), user_id))
        conn.commit()


def set_ts_active(user_id, sid):
    sid = str(sid or "").strip()
    sid = sid if sid.isdigit() and sid != "0" else ""
    with connect() as conn:
        conn.execute("UPDATE users SET ts_active=%s WHERE id=%s", (sid, user_id))
        conn.commit()


def set_public(user_id, on):
    with connect() as conn:
        conn.execute("UPDATE users SET public_journal=%s WHERE id=%s",
                     (bool(on), user_id))
        conn.commit()


def set_tz(user_id, tz):
    """Часовий пояс людини (назва IANA, як «Europe/Kyiv»)."""
    with connect() as conn:
        conn.execute("UPDATE users SET tz=%s WHERE id=%s", (tz, user_id))
        conn.commit()


def get_user_by_telegram(tg_id):
    with connect() as conn:
        return conn.execute("SELECT * FROM users WHERE telegram_id=%s", (tg_id,)).fetchone()


def linked_users():
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE telegram_id IS NOT NULL ORDER BY id").fetchall()


# ---------------------------------------------------------------- сделки ----

def _row_to_trade(row):
    if row is None:
        return None
    t = {"id": row["id"]}
    for f in TEXT_FIELDS:
        t[f] = row[f] or ""
    for f in NUM_FIELDS:
        t[f] = row[f]
    t["screenshots"] = row["screenshots"] or []
    if row["hidden"]:
        t["hidden"] = True
    t["kind"] = row["kind"] or ""
    return t


def list_trades(user_id, kind=""):
    """Сделки человека. По умолчанию — только реальная торговля.

    `kind`: "" — реальные, "bt" — бэктест, "all" — и то, и другое. Умолчание
    выбрано так, чтобы бэктест никуда не просочился сам: бот, помощник,
    чужой журнал по ссылке и перенос из Notion зовут эту функцию без
    аргумента и продолжают видеть только настоящие сделки. "all" нужен
    одному месту — снимку для бэкапа, он спасает всё подряд.
    """
    sql = "SELECT * FROM trades WHERE user_id=%s"
    args = [user_id]
    if kind != "all":
        sql += ' AND "kind"=%s'
        args.append("bt" if kind == "bt" else "")
    # "s:3" — реальні угоди однієї стратегії ("s:0" — першої), див. strat_kind
    if str(kind or "").startswith("s:"):
        sql += ' AND "ts"=%s'
        args.append("" if kind[2:] in ("", "0") else kind[2:])
    sql += " ORDER BY created_at"
    with connect() as conn:
        rows = conn.execute(sql, args).fetchall()
    return [_row_to_trade(r) for r in rows]


def strat_kind(v):
    """Стратегія з браузера → kind для list_trades / ts_store: "s:<номер>"
    або "" (усі стратегії / одна-єдина)."""
    v = str(v or "").strip()
    return "s:" + v if v.isdigit() else ""


def get_trade(tid, user_id):
    """Угода людини. Хазяїн — обов'язковий: раніше він мав значення за
    замовчуванням (None = будь-чия угода), і досить було один раз його не
    передати, щоб за відомим id віддати чужий запис. Усі, хто кличе, його
    й так передають — тепер інакше не вийде."""
    with connect() as conn:
        return _row_to_trade(conn.execute(
            "SELECT * FROM trades WHERE id=%s AND user_id=%s",
            (tid, user_id)).fetchone())


def notion_known(user_id):
    """Что у человека уже есть: инструменты и id записей Notion.
    Импорт по ним понимает, что переносить не нужно."""
    with connect() as conn:
        rows = conn.execute('SELECT DISTINCT "pair", "notion_id" FROM trades '
                            'WHERE user_id=%s', (user_id,)).fetchall()
    known = {(r["pair"] or "").strip() for r in rows if (r["pair"] or "").strip()}
    seen = {r["notion_id"] for r in rows if r["notion_id"]}
    return known, seen


def notion_gone(user_id):
    """Що людина прибрала з журналу руками: id записів у Notion і скільки
    угод із кожним відбитком прибрано. Перенесення рахує їх такими, що вже
    приїжджали, — інакше прибране повертається наступним перенесенням."""
    with connect() as conn:
        rows = conn.execute("SELECT notion_id, mark FROM notion_gone "
                            "WHERE user_id=%s", (user_id,)).fetchall()
    ids = {r["notion_id"] for r in rows if r["notion_id"]}
    marks = {}
    for r in rows:
        if r["mark"]:
            marks[r["mark"]] = marks.get(r["mark"], 0) + 1
    return ids, marks


def import_seen(user_id, rows):
    """Усе, за чим перенесення впізнає «це в нас уже було»: інструменти,
    id записів Notion і відбитки. Рахуємо разом і живі угоди, і прибрані —
    перше перенесення й повторне мають дивитись однаково."""
    known, seen = notion_known(user_id)
    gone_ids, gone_marks = notion_gone(user_id)
    marks = tidy.prints(rows)
    for k, n in gone_marks.items():
        marks[k] = marks.get(k, 0) + n
    return known, seen | gone_ids, marks


def _remember_gone(conn, user_id, t):
    """Кладемо прибрану угоду в могильник — але тільки ту, що приїхала з
    Notion: записану на сайті звідти ніхто не привезе.

    Той самий запис двічі не пишемо: id у Notion один, і другий рядок лише
    зайвий раз відняв би відбиток."""
    nid = (t.get("notion_id") or "").strip()
    imp = (t.get("import_id") or "").strip()
    if not nid and not imp:
        return
    conn.execute(
        "INSERT INTO notion_gone (user_id, notion_id, import_id, mark) "
        "SELECT %s, %s, %s, %s WHERE NOT EXISTS ("
        "  SELECT 1 FROM notion_gone WHERE user_id=%s AND notion_id=%s "
        "  AND notion_id <> '')",
        (user_id, nid, imp, tidy.same_trade_key(t) or "", user_id, nid))


def count_import(user_id, batch):
    with connect() as conn:
        row = conn.execute('SELECT count(*) AS n FROM trades WHERE user_id=%s '
                           'AND "import_id"=%s', (user_id, batch)).fetchone()
    return row["n"]


def rename_value(user_id, field, values, to, kind="", conn=None):
    """Сводит несколько написаний одного имени в одно.

    Имя колонки подставляется в SQL, поэтому берём его только из своего
    списка — снаружи сюда приходит поле из запроса.

    `kind` — в каком журнале переименовываем: "" реальный, "bt" бэктест,
    "all" оба. Умолчание то же, что у `list_trades`: списки написаний
    человек видит по реальным сделкам, и правка не должна молча трогать
    прогоны на истории, которых в том списке не было.

    `conn` — готовое соединение, когда переименование должно уехать в базу
    одной транзакцией с чем-то ещё (так это делает карточка счёта: имя
    карточки и имя в сделках обязаны меняться вместе или никак).
    """
    if field not in TIDY_FIELDS:
        raise ValueError("нельзя менять поле %r" % (field,))
    values = [v for v in (values or []) if v != to]
    if not values:
        return 0
    # sql-ok: field звірено з TIDY_FIELDS на початку функції
    sql = ('UPDATE trades SET "%s"=%%s WHERE user_id=%%s '
           'AND "%s" = ANY(%%s)' % (field, field))
    args = [to, user_id, values]
    if kind != "all":
        sql += " AND kind=%s"
        args.append("bt" if kind == "bt" else "")
    if conn is not None:
        return conn.execute(sql, tuple(args)).rowcount
    with connect() as c:
        cur = c.execute(sql, tuple(args))
        c.commit()
    return cur.rowcount


def count_imports(user_id):
    """Сколько сделок принесло каждое перенесение — одним запросом.

    Журнал часто собран из нескольких баз Notion (у человека месяцы лежат
    в разных таблицах), и список источников считает их все сразу."""
    with connect() as conn:
        rows = conn.execute('SELECT "import_id" AS b, count(*) AS n FROM trades '
                            "WHERE user_id=%s AND \"import_id\"<>'' "
                            'GROUP BY "import_id"', (user_id,)).fetchall()
    return {r["b"]: r["n"] for r in rows}


def drop_import(user_id, batch):
    """Убирает сделки одного переноса. Возвращает (сколько убрали, какие
    файлы скриншотов больше никому не нужны)."""
    with connect() as conn:
        gone = conn.execute('SELECT screenshots FROM trades WHERE user_id=%s '
                            'AND "import_id"=%s', (user_id, batch)).fetchall()
        if not gone:
            return 0, []
        conn.execute('DELETE FROM trades WHERE user_id=%s AND "import_id"=%s',
                     (user_id, batch))
        # Базу зняли цілком — могильник цього перенесення більше ні до чого:
        # хто перенесе її заново, має отримати всі угоди, а не з дірками.
        conn.execute("DELETE FROM notion_gone WHERE user_id=%s AND import_id=%s",
                     (user_id, batch))
        left = conn.execute("SELECT screenshots FROM trades WHERE user_id=%s",
                            (user_id,)).fetchall()
        conn.commit()
    files = {s.get("file") for r in gone for s in (r["screenshots"] or []) if s.get("file")}
    # файл может быть общим с оставшейся сделкой — такие не трогаем
    used = {s.get("file") for r in left for s in (r["screenshots"] or []) if s.get("file")}
    return len(gone), sorted(files - used)


def files_in_use(names):
    """Які з цих файлів ще згадані хоч в одній угоді — будь-чиїй.

    Перед видаленням файлу: один скрін буває в двох угодах (імпорт власного
    вивантаження), і стерти його разом з однією — дірка в другій."""
    names = [n for n in names if n]
    if not names:
        return set()
    with connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT s->>'file' AS f FROM trades, jsonb_array_elements("
            "CASE WHEN jsonb_typeof(screenshots)='array' THEN screenshots "
            "ELSE '[]'::jsonb END) s WHERE s->>'file' = ANY(%s)", (names,)).fetchall()
    return {r["f"] for r in rows}


def owns_screenshot(user_id, filename):
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM trades WHERE user_id=%s AND screenshots @> %s LIMIT 1",
            (user_id, Jsonb([{"file": filename}]))).fetchone()
    return row is not None


def session_gen(user_id):
    """Поточне покоління входів. None — такої людини вже немає."""
    with connect() as conn:
        row = conn.execute("SELECT session_gen FROM users WHERE id=%s",
                           (user_id,)).fetchone()
    return row["session_gen"] if row else None


def bump_session_gen(user_id):
    """+1 до покоління: усі видані раніше куки перестають пускати."""
    with connect() as conn:
        row = conn.execute("UPDATE users SET session_gen=session_gen+1 WHERE id=%s "
                           "RETURNING session_gen", (user_id,)).fetchone()
        conn.commit()
    return row["session_gen"] if row else None


def twofa_enable(user_id, secret, backup_hashes, step):
    with connect() as conn:
        conn.execute("UPDATE users SET twofa_secret=%s, twofa_enabled_at=now(), "
                     "twofa_backup=%s, twofa_last_step=%s WHERE id=%s",
                     (secret, Jsonb(list(backup_hashes)), step, user_id))
        conn.commit()


def twofa_disable(user_id):
    with connect() as conn:
        conn.execute("UPDATE users SET twofa_secret=NULL, twofa_enabled_at=NULL, "
                     "twofa_backup='[]'::jsonb, twofa_last_step=NULL WHERE id=%s",
                     (user_id,))
        conn.commit()


def twofa_set_backup(user_id, backup_hashes):
    with connect() as conn:
        conn.execute("UPDATE users SET twofa_backup=%s WHERE id=%s",
                     (Jsonb(list(backup_hashes)), user_id))
        conn.commit()


def twofa_take_step(user_id, step):
    """Прийняти код кроку step. Атомарно: два однакові запити одночасно —
    пройде лише один, а старший крок після молодшого не пройде зовсім."""
    with connect() as conn:
        row = conn.execute(
            "UPDATE users SET twofa_last_step=%s WHERE id=%s AND twofa_secret IS NOT NULL "
            "AND (twofa_last_step IS NULL OR twofa_last_step < %s) RETURNING id",
            (step, user_id, step)).fetchone()
        conn.commit()
    return row is not None


def twofa_take_backup(user_id, code_hash):
    """Витратити запасний код. Атомарно: один код — один вхід."""
    with connect() as conn:
        row = conn.execute(
            "UPDATE users SET twofa_backup=twofa_backup - %s::text WHERE id=%s "
            "AND twofa_secret IS NOT NULL AND twofa_backup ? %s::text "
            "RETURNING jsonb_array_length(twofa_backup) AS left",
            (code_hash, user_id, code_hash)).fetchone()
        conn.commit()
    return None if row is None else row["left"]


def set_password(user_id, pw_hash, pw_salt, pw_iters):
    """Новий пароль. Старий перевіряє той, хто кличе — тут лише запис."""
    with connect() as conn:
        conn.execute("UPDATE users SET pw_hash=%s, pw_salt=%s, pw_iters=%s WHERE id=%s",
                     (pw_hash, pw_salt, pw_iters, user_id))


def create_link(user_id, token_hash, kind="password", minutes=30):
    """Нове посилання з листа. Старі невикористані того ж виду гасимо:
    попросив ще раз — значить, попереднє не дійшло або загубилось."""
    with connect() as conn:
        conn.execute("DELETE FROM auth_links "
                     "WHERE user_id=%s AND kind=%s AND used_at IS NULL",
                     (user_id, kind))
        conn.execute(
            "INSERT INTO auth_links (token_hash, user_id, kind, expires_at) "
            "VALUES (%s, %s, %s, now() + make_interval(mins => %s))",
            (token_hash, user_id, kind, int(minutes)))
        conn.commit()


def take_link(token_hash, kind="password"):
    """Погасити посилання й повернути господаря. None — не годиться.

    Вид перевіряємо разом із ключем: посиланням на підтвердження пошти
    не можна відкрити зміну пароля, навіть якщо ключ підійшов.

    Позначку «використано» ставимо тим самим запитом, що й перевіряємо:
    два одночасні натискання не мають обидва відкрити зміну пароля.
    """
    with connect() as conn:
        row = conn.execute(
            "UPDATE auth_links SET used_at=now() "
            "WHERE token_hash=%s AND kind=%s AND used_at IS NULL "
            "AND expires_at > now() "
            "RETURNING user_id", (token_hash, kind)).fetchone()
        conn.commit()
        if not row:
            return None
        return conn.execute("SELECT * FROM users WHERE id=%s",
                            (row["user_id"],)).fetchone()


def confirm_email(user_id):
    """Пошту підтверджено. Повторне підтвердження часу не зсуває —
    цікавить перший раз."""
    with connect() as conn:
        conn.execute("UPDATE users SET email_confirmed_at=now() "
                     "WHERE id=%s AND email_confirmed_at IS NULL", (user_id,))
        conn.commit()


def public_screenshot(user_id, filename):
    """Скрин из чужого журнала. Открытость проверяем тем же запросом, что и
    владение файлом: закрыл журнал — картинки перестали отдаваться сразу."""
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM trades t JOIN users u ON u.id=t.user_id "
            "WHERE t.user_id=%s AND u.public_journal AND t.screenshots @> %s LIMIT 1",
            (user_id, Jsonb([{"file": filename}]))).fetchone()
    return row is not None


def _trade_values(t):
    # емоцію — кодом, хоч би звідки прийшла угода (сайт, бот, Notion, файл):
    # тоді в розрізі кожна емоція одним рядком на будь-якій мові
    if t.get("emotion"):
        import emotions
        t = dict(t, emotion=emotions.norm(t["emotion"]))
    vals = [t.get(f) or "" for f in TEXT_FIELDS]
    vals += [t.get(f) for f in NUM_FIELDS]
    vals += [Jsonb(t.get("screenshots") or []), bool(t.get("hidden"))]
    # Тип сделки — из белого списка. Значение приходит из браузера, и другого
    # места, где его можно подменить, у него нет.
    vals += ["bt" if t.get("kind") == "bt" else ""]
    return vals


_COLS = ", ".join('"%s"' % f for f in FIELDS) + ', screenshots, hidden, "kind"'
_PLACEHOLDERS = ", ".join(["%s"] * (len(FIELDS) + 3))
_SETS = ", ".join('"%s"=%%s' % f for f in FIELDS) + ', screenshots=%s, hidden=%s, "kind"=%s'


# ---------------------------------------------------------------------------
# Один инструмент — одно написание.
#
# Поле свободное: сегодня человек напишет «GER40», завтра «ger 40» — и в
# статистике это два разных инструмента, винрейт и профит-фактор делятся
# пополам. Перед записью подставляем то написание, которое в журнале уже
# есть.
#
# Сводим регистр, пробелы, знаки и известные имена одного актива из
# tidy.SAME: «US100», «Nasdaq» и «NQ» — один инструмент, «US30» и «US100» —
# разные. Незнакомые синонимы по-прежнему сводит человек в окне сведения.
# ---------------------------------------------------------------------------
def _known_pairs(conn, user_id, skip_id=None):
    """Написание -> как этот инструмент чаще всего записан в журнале.

    Поровну — берём первое по алфавиту, чтобы от запуска к запуску
    подставлялось одно и то же.
    """
    sql = 'SELECT "pair" AS p, count(*) AS n FROM trades WHERE user_id=%s'
    args = [user_id]
    if skip_id:                 # своё же прежнее написание не эталон себе
        sql += " AND id<>%s"
        args.append(skip_id)
    sql += ' GROUP BY "pair"'
    rows = conn.execute(sql, args).fetchall()
    best = {}
    for r in sorted(rows, key=lambda r: (-r["n"], (r["p"] or ""))):
        v = (r["p"] or "").strip()
        k = tidy.pair_key(v)
        if k and k not in best:
            best[k] = v
    return best


def _one_spelling(conn, user_id, trades, skip_id=None):
    """Приводит инструмент к написанию, принятому в журнале.

    Незнакомый инструмент остаётся как написан — и задаёт написание
    остальным в этой же пачке: из таблицы «ger 40» и «GER 40» приезжают
    вперемешку.
    """
    known = _known_pairs(conn, user_id, skip_id)
    for t in trades:
        v = str(t.get("pair") or "").strip()
        k = tidy.pair_key(v)
        if not k:
            continue
        if k in known:
            t["pair"] = known[k]
        else:
            known[k] = v


def insert_trade(user_id, t, emotion_status="na"):
    with connect() as conn:
        _one_spelling(conn, user_id, [t])
        conn.execute(
            "INSERT INTO trades (id, user_id, %s, emotion_prompt_status) "
            "VALUES (%%s, %%s, %s, %%s)" % (_COLS, _PLACEHOLDERS),
            [t["id"], user_id] + _trade_values(t) + [emotion_status])
        conn.commit()
    return t


def insert_trades(user_id, trades, emotion_status="na"):
    """Пачкой и одним подключением: импорт из Notion приносит сотни сделок,
    а база в облаке — каждый отдельный заход это лишний рейс туда-обратно."""
    if not trades:
        return 0
    sql = ("INSERT INTO trades (id, user_id, %s, emotion_prompt_status) "
           "VALUES (%%s, %%s, %s, %%s)" % (_COLS, _PLACEHOLDERS))
    with connect() as conn:
        _one_spelling(conn, user_id, trades)
        rows = [[t["id"], user_id] + _trade_values(t) + [emotion_status] for t in trades]
        with conn.cursor() as cur:
            cur.executemany(sql, rows)
        conn.commit()
    return len(rows)


# Що можна дописати в уже перенесену угоду. Імена йдуть прямо в SQL,
# тому список закритий; службових полів і емоції тут немає — емоцію
# людина ставить сама, і імпорт її не пише.
FILL_FIELDS = ("pair", "date", "session", "position", "entry_model", "bias",
               "setup", "direction_type", "result", "account", "entry_details",
               "notes", "mistakes", "comments")


def fill_blanks(user_id, trade_id, t):
    """Дописує в угоду тільки те, чого в ній немає. Повертає 1, якщо змінили.

    Повторний імпорт знайомі угоди пропускає — інакше пішли б дублі. Але
    якщо перший раз колонку не впізнали, порожнє поле так і лишиться
    порожнім назавжди. Тут воно заповнюється, а заповнене — ні: у журналі
    могли виправити руками, і затерти це було б гірше за порожнечу."""
    if not trade_id:
        return 0
    sets, empty, vals = [], [], []
    for f in FILL_FIELDS:
        v = (t.get(f) or "").strip() if isinstance(t.get(f), str) else t.get(f)
        if not v:
            continue
        sets.append('"{0}"=CASE WHEN "{0}" IS NULL OR "{0}"=\'\' THEN %s ELSE "{0}" END'.format(f))
        empty.append('("{0}" IS NULL OR "{0}"=\'\')'.format(f))
        vals.append(v)
    for f in NUM_FIELDS:
        if t.get(f) is None:
            continue
        sets.append('"{0}"=COALESCE("{0}", %s)'.format(f))
        empty.append('"{0}" IS NULL'.format(f))
        vals.append(t[f])
    if not sets:
        return 0
    with connect() as conn:
        cur = conn.execute(
            "UPDATE trades SET %s WHERE user_id=%%s AND id=%%s AND (%s)"
            % (", ".join(sets), " OR ".join(empty)),
            vals + [user_id, trade_id])
        conn.commit()
    return cur.rowcount


def update_trade(user_id, t):
    with connect() as conn:
        _one_spelling(conn, user_id, [t], skip_id=t["id"])
        cur = conn.execute(
            "UPDATE trades SET %s WHERE id=%%s AND user_id=%%s" % _SETS,
            _trade_values(t) + [t["id"], user_id])
        conn.commit()
    return cur.rowcount > 0


def delete_trade(user_id, tid):
    """Прибирає угоду й запам'ятовує, що її прибрали: угоди з Notion інакше
    повертаються наступним перенесенням (див. notion_gone)."""
    with connect() as conn:
        row = conn.execute("SELECT * FROM trades WHERE id=%s AND user_id=%s",
                           (tid, user_id)).fetchone()
        if not row:
            return False
        conn.execute("DELETE FROM trades WHERE id=%s AND user_id=%s", (tid, user_id))
        _remember_gone(conn, user_id, dict(row))
        conn.commit()
    return True


# ------------------------------------------------------- эмоция по сделке ----

def mark_emotion_pending(tid, msg_id=None):
    with connect() as conn:
        conn.execute("UPDATE trades SET emotion_prompt_status='pending', "
                     "emotion_prompt_msg_id=%s, emotion_prompt_at=now() WHERE id=%s",
                     (msg_id, tid))
        conn.commit()


def set_emotion_prompt_msg(tid, msg_id):
    with connect() as conn:
        conn.execute("UPDATE trades SET emotion_prompt_msg_id=%s WHERE id=%s", (msg_id, tid))
        conn.commit()


def set_trade_emotion(tid, emotion, raw=None):
    """Пишем ответ только если промпт всё ещё ждёт — защита от второго нажатия."""
    import emotions
    emotion = emotions.norm(emotion)
    with connect() as conn:
        cur = conn.execute(
            "UPDATE trades SET \"emotion\"=%s, emotion_raw=%s, emotion_prompt_status='answered' "
            "WHERE id=%s AND emotion_prompt_status='pending'", (emotion, raw, tid))
        conn.commit()
    return cur.rowcount > 0


def trades_with_emotion(user_id):
    """Для разбора: только закрытые сделки, где эмоция известна."""
    with connect() as conn:
        return conn.execute(
            "SELECT \"emotion\", \"result\", rr, risk, \"date\", \"pair\", \"setup\", "
            "\"mistakes\", emotion_raw FROM trades "
            "WHERE user_id=%s AND \"emotion\" <> '' AND \"result\" NOT IN ('', 'Open') "
            "ORDER BY \"date\"",
            (user_id,)).fetchall()


def pending_emotion_trades(user_id):
    with connect() as conn:
        return conn.execute(
            "SELECT id, \"pair\", \"date\", emotion_prompt_msg_id FROM trades "
            "WHERE user_id=%s AND emotion_prompt_status='pending' ORDER BY emotion_prompt_at",
            (user_id,)).fetchall()


# ------------------------------------------------------- привязка Telegram ----

def create_link_code(user_id):
    code = secrets.token_hex(4)
    with connect() as conn:
        conn.execute("INSERT INTO link_codes (code, user_id, expires_at) VALUES (%s, %s, %s)",
                     (code, user_id, now() + LINK_CODE_TTL))
        conn.commit()
    return code


def consume_link_code(code, tg_id, tg_username):
    """Возвращает ('ok', user) / ('bad', None) / ('taken', None)."""
    with connect() as conn:
        row = conn.execute(
            "SELECT user_id FROM link_codes WHERE code=%s AND used_at IS NULL "
            "AND expires_at > now()", (code,)).fetchone()
        if not row:
            return "bad", None
        try:
            conn.execute("UPDATE users SET telegram_id=%s, telegram_username=%s WHERE id=%s",
                         (tg_id, tg_username, row["user_id"]))
        except psycopg.errors.UniqueViolation:
            conn.rollback()
            return "taken", None
        conn.execute("UPDATE link_codes SET used_at=now() WHERE code=%s", (code,))
        user = conn.execute("SELECT * FROM users WHERE id=%s", (row["user_id"],)).fetchone()
        conn.commit()
    return "ok", user


def unlink_telegram(user_id):
    with connect() as conn:
        conn.execute("UPDATE users SET telegram_id=NULL, telegram_username=NULL WHERE id=%s",
                     (user_id,))
        conn.commit()


# --------------------------------------------------------- напоминания ----

def frequent_values(user_id, field, limit=6):
    """Чим людина справді користується в цьому полі — від частого до рідкого.

    Кнопки в боті збираємо саме звідси, а не зі списку «всі значення»:
    інакше поруч із трьома робочими сетапами стоїть десяток тих, що
    траплялись одного разу. Поле беремо тільки зі свого списку — воно
    йде в SQL підстановкою, і чужому рядку тут не місце.
    """
    if field not in TEXT_FIELDS:
        raise ValueError("невідоме поле: %s" % field)
    with connect() as conn:
        # sql-ok: field зі свого списку, рядком сюди не потрапить
        rows = conn.execute(
            'SELECT "%s" AS v, count(*) AS n FROM trades '
            'WHERE user_id=%%s AND "%s" <> %%s '
            'GROUP BY v ORDER BY n DESC, v LIMIT %%s' % (field, field),
            (user_id, "", limit)).fetchall()
    return [r["v"] for r in rows]


def last_number(user_id, field):
    """Останнє число в полі — щоб запропонувати «як минулого разу»."""
    if field not in NUM_FIELDS:
        raise ValueError("невідоме поле: %s" % field)
    with connect() as conn:
        # sql-ok: field зі свого списку, рядком сюди не потрапить
        row = conn.execute(
            'SELECT "%s" AS v FROM trades WHERE user_id=%%s AND "%s" IS NOT NULL '
            'ORDER BY created_at DESC LIMIT 1' % (field, field), (user_id,)).fetchone()
    return (row or {}).get("v")


# ---------------------------------------------------------------- чернетка ----

def draft_get(user_id):
    with connect() as conn:
        row = conn.execute("SELECT chat_id, step, data FROM trade_drafts WHERE user_id=%s",
                           (user_id,)).fetchone()
    if not row:
        return None
    return {"chat_id": row["chat_id"], "step": row["step"], "data": row["data"] or {}}


def draft_save(user_id, chat_id, step, data):
    with connect() as conn:
        conn.execute(
            "INSERT INTO trade_drafts (user_id, chat_id, step, data) "
            "VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (user_id) DO UPDATE SET chat_id=EXCLUDED.chat_id, "
            "step=EXCLUDED.step, data=EXCLUDED.data, updated_at=now()",
            (user_id, chat_id, step, Jsonb(data or {})))
        conn.commit()


def draft_clear(user_id):
    with connect() as conn:
        conn.execute("DELETE FROM trade_drafts WHERE user_id=%s", (user_id,))
        conn.commit()


def already_notified(user_id, event_key, kind):
    with connect() as conn:
        row = conn.execute("SELECT 1 FROM notified_events WHERE user_id=%s AND event_key=%s "
                           "AND kind=%s", (user_id, event_key, kind)).fetchone()
    return row is not None


def record_notified(user_id, event_key, kind):
    """True — если запись создана нами (значит уведомление ещё не отправляли)."""
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO notified_events (user_id, event_key, kind) VALUES (%s, %s, %s) "
            "ON CONFLICT DO NOTHING", (user_id, event_key, kind))
        conn.commit()
    return cur.rowcount > 0


def payment_once(event_id, user_id, event, amount_cents=None,
                 currency="EUR", raw=None):
    """Записати подію від платіжки. Повертає False, якщо таку вже бачили.

    Платіжки доставляють повідомлення «хоча б один раз»: мережа моргнула,
    ми не встигли відповісти — і те саме прилетить ще раз. Без цього
    заслону повторна доставка продовжила б підписку двічі за одні гроші.

    Ключ — id самої події, а не оплати: на одну оплату подій кілька.
    """
    import json as _json
    with connect() as conn:
        row = conn.execute(
            "INSERT INTO payments (id, user_id, event, amount_cents, currency, raw) "
            "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING RETURNING id",
            (str(event_id), user_id, event or "", amount_cents, currency or "EUR",
             _json.dumps(raw or {}))).fetchone()
        conn.commit()
    return bool(row)


def set_creem_customer(user_id, customer_id):
    """Запам'ятати номер людини на боці платіжки.

    Пишемо тільки якщо номер новий: той самий приходить з кожною подією, і
    зайвий UPDATE на кожне продовження ні до чого. Порожній номер не
    затирає збережений — подія могла прийти без нього.
    """
    cid = str(customer_id or "").strip()[:128]
    if not user_id or not cid:
        return False
    with connect() as conn:
        cur = conn.execute(
            "UPDATE users SET creem_customer=%s "
            "WHERE id=%s AND creem_customer IS DISTINCT FROM %s",
            (cid, user_id, cid))
        conn.commit()
    return cur.rowcount > 0

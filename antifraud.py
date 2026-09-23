# -*- coding: utf-8 -*-
"""Один акаунт на людину — рівно настільки, наскільки це чесно зробити.

Правило власника (22.09.2026, варіант «б»): реєстрацію закриваємо лише
тоді, коли збіглися **обидва** признаки — і адреса, і пристрій. Збігся
сам IP — пропускаємо й ставимо позначку в адмінці.

Чому не по самому IP: мобільні оператори ховають за одну адресу тисячі
людей (CGNAT), у гуртожитку чи офісі теж один вихід на всіх. Заслон по
IP закрив би двері живим людям, а той, кому треба, однаково перемкнув би
мережу. Разом із пристроєм картина інша: це вже «той самий браузер на
тому самому комп'ютері в тій самій мережі».

Пристрій пізнаємо за відбитком браузера (екран, пояс, мова, платформа) —
його ж бачимо і в новому вікні, і в режимі анонімного перегляду. Куки
тут не допомогли б зовсім: їх чистять одним рухом, і весь заслон
обійшовся б цим рухом.

Відбиток зберігаємо тільки хешем: сам рядок нам не потрібен, порівнювати
можна й хеші, а в базі не лежить зайвий опис чужого комп'ютера.

Помилятися цей заслон буде — сім'я за одним роутером з однаковими
телефонами виглядає звідси як одна людина. Тому плашка відмови не
глуха: вона кличе написати нам, а адмін додає адресу в ip_allow.
"""
import hashlib

import db

# Скільки сусідів показуємо в адмінці. Більше — це вже не картка людини,
# а звіт; якщо їх справді багато, видно й по перших.
NEIGHBOURS = 8


def device_hash(raw):
    """Відбиток пристрою → короткий хеш. Порожньо лишається порожнім:
    «не знаємо» не має злипатися в один пристрій на всіх."""
    s = (raw or "").strip()
    if not s:
        return ""
    return hashlib.sha256(s.encode("utf-8", "replace")).hexdigest()[:32]


def allowed(ip):
    """Адресу адмін дозволив руками — «це інша людина, пропускай»."""
    if not ip:
        return False
    with db.connect() as conn:
        return bool(conn.execute("SELECT 1 FROM ip_allow WHERE ip=%s",
                                 (ip,)).fetchone())


def allow(ip, note=""):
    with db.connect() as conn:
        conn.execute("INSERT INTO ip_allow (ip, note) VALUES (%s,%s) "
                     "ON CONFLICT (ip) DO UPDATE SET note=EXCLUDED.note",
                     (ip, note or ""))
        conn.commit()
    return True


def forbid(ip):
    """Прибрати дозвіл — помилились, це таки та сама людина."""
    with db.connect() as conn:
        conn.execute("DELETE FROM ip_allow WHERE ip=%s", (ip,))
        conn.commit()
    return True


def twin(ip, device):
    """Акаунт із тією самою адресою І тим самим пристроєм, або None.

    Обидві умови обов'язкові, і обидві мають бути непорожні: без відбитка
    (стара сторінка, вимкнений JS) блокувати нема на чому — там лишається
    сам IP, а по ньому ми не закриваємо.
    """
    if not ip or not device:
        return None
    with db.connect() as conn:
        return conn.execute(
            "SELECT s.user_id, s.created_at, u.nickname FROM signup_ips s "
            "JOIN users u ON u.id = s.user_id "
            "WHERE s.ip=%s AND s.device=%s ORDER BY s.id LIMIT 1",
            (ip, device)).fetchone()


def blocked(ip, device):
    """Чи закривати реєстрацію. Дозволена адреса знімає заслон одразу."""
    if allowed(ip):
        return None
    return twin(ip, device)


def remember(user_id, ip, device):
    """Записати, звідки й з чого зайшли. Два місця навмисно: в users —
    остання реєстрація (її видно в картці), у signup_ips — уся історія,
    по ній і шукаємо сусідів."""
    with db.connect() as conn:
        conn.execute("UPDATE users SET signup_ip=%s, signup_device=%s WHERE id=%s",
                     (ip or "", device or "", user_id))
        conn.execute("INSERT INTO signup_ips (ip, device, user_id) VALUES (%s,%s,%s)",
                     (ip or "", device or "", user_id))
        conn.commit()


def neighbours(user_id):
    """Хто ще схожий на цю людину — для картки в адмінці.

    Три окремі списки, бо важать вони по-різному: спільний IP — це
    частіше збіг, спільний пристрій — уже майже напевно одна людина, а
    спільна база Notion — той самий журнал, перенесений двічі.
    """
    out = {"ip": [], "device": [], "notion": [], "allowed": False}
    with db.connect() as conn:
        me = conn.execute("SELECT signup_ip, signup_device FROM users WHERE id=%s",
                          (user_id,)).fetchone() or {}
        ip = (me.get("signup_ip") or "").strip()
        device = (me.get("signup_device") or "").strip()
        if ip:
            out["allowed"] = bool(conn.execute("SELECT 1 FROM ip_allow WHERE ip=%s",
                                               (ip,)).fetchone())
            out["ip"] = conn.execute(
                "SELECT DISTINCT u.nickname, s.created_at FROM signup_ips s "
                "JOIN users u ON u.id = s.user_id "
                "WHERE s.ip=%s AND s.user_id<>%s ORDER BY s.created_at DESC LIMIT %s",
                (ip, user_id, NEIGHBOURS)).fetchall()
        if device:
            out["device"] = conn.execute(
                "SELECT DISTINCT u.nickname, s.created_at FROM signup_ips s "
                "JOIN users u ON u.id = s.user_id "
                "WHERE s.device=%s AND s.user_id<>%s ORDER BY s.created_at DESC LIMIT %s",
                (device, user_id, NEIGHBOURS)).fetchall()
        # Та сама база Notion у двох акаунтах. Таблиця з'являється при
        # першому перенесенні, тому її може не бути зовсім.
        try:
            out["notion"] = conn.execute(
                "SELECT DISTINCT u.nickname, s2->>'url' AS url "
                "FROM notion_conf n1 "
                "CROSS JOIN LATERAL jsonb_array_elements("
                "  COALESCE(n1.data->'sources','[]'::jsonb)) s1 "
                "JOIN notion_conf n2 ON n2.user_id <> n1.user_id "
                "CROSS JOIN LATERAL jsonb_array_elements("
                "  COALESCE(n2.data->'sources','[]'::jsonb)) s2 "
                "JOIN users u ON u.id = n2.user_id "
                "WHERE n1.user_id=%s AND s1->>'url' = s2->>'url' "
                "  AND COALESCE(s1->>'url','') <> '' LIMIT %s",
                (user_id, NEIGHBOURS)).fetchall()
        except Exception:
            out["notion"] = []
    return out

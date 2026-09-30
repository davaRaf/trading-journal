# -*- coding: utf-8 -*-
"""
Завантаження файлів: python test_uploads.py

Три речі, на яких тут ловляться підробки:

1. Тип — за першими байтами. «opasnyy.php.jpg» і data-URL із написом
   «image/png» кажуть лише те, що захотів сказати клієнт.
2. Ім'я — своє. Того, що прислали, ми не використовуємо взагалі, тому
   ні розширення, ні шлях у ньому нічого не вирішують.
3. Шлях — усередині своєї папки. Назва, що починається з кореня, раніше
   заміняла папку цілком, і /static/ діставав будь-який файл на сервері.

Бази не треба: filestore.put підміняємо, файли пишемо в тимчасову папку.
"""
import os
import tempfile

os.environ.setdefault("DATABASE_URL", "postgresql://x/y")

import app
import filestore
import ts_store

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
JPG = b"\xff\xd8\xff\xe0" + b"0" * 64
GIF = b"GIF89a" + b"0" * 64
WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"0" * 64
HTML = b"<html><script>alert(1)</script></html>"
PHP = b"<?php system($_GET['c']); ?>"
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'


def check(name, cond):
    print("  %-4s  %s" % ("ok" if cond else "ПАДАЄ", name))
    assert cond, name


def url(kind, raw):
    import base64
    return "data:image/%s;base64,%s" % (kind, base64.b64encode(raw).decode())


def by_bytes():
    """Тип беремо з байтів, а не зі слова в data-URL."""
    check("png упізнали", filestore.kind(PNG) == "png")
    check("jpeg упізнали", filestore.kind(JPG) == "jpg")
    check("gif упізнали", filestore.kind(GIF) == "gif")
    check("webp упізнали", filestore.kind(WEBP) == "webp")
    check("сторінка з <script> — не картинка", filestore.kind(HTML) is None)
    check("php — не картинка", filestore.kind(PHP) is None)
    check("svg не пускаємо навіть малюнком", filestore.kind(SVG) is None)
    check("порожнє — не картинка", filestore.kind(b"") is None)


def extension_is_ours(tmp):
    """Розширення ставимо своє, за вмістом, хоч би що казав клієнт."""
    name = ts_store.save_shot(7, url("png", JPG), tmp)
    check("jpeg під виглядом png лягає як .jpg", name.endswith(".jpg"))
    check("ім'я своє, за шаблоном", bool(ts_store.NAME_RE.match(name)))
    check("в імені номер господаря", name.startswith("ts7_"))
    check("файл справді записався", os.path.exists(os.path.join(tmp, name)))


def not_an_image(tmp):
    """Не картинку не беремо, хоч би як її назвали."""
    for what, raw in (("сторінку", HTML), ("php", PHP), ("svg", SVG)):
        try:
            ts_store.save_shot(7, url("png", raw), tmp)
            ok = False
        except filestore.ShotError as e:
            ok = e.code == "bad_image"
        check("%s під виглядом картинки не проходить" % what, ok)


def too_big(tmp):
    """Завелике — відмова, а не тихо повний диск."""
    big = PNG + b"0" * ts_store.MAX_BYTES
    try:
        ts_store.save_shot(7, url("png", big), tmp)
        ok = False
    except filestore.ShotError as e:
        ok = e.code == "too_big" and e.status == 413
    check("понад межу не приймаємо", ok)


def paths_stay_inside():
    """Шлях не виходить за свою папку — ні вгору, ні з кореня."""
    base = app.STATIC
    check("звичайний файл — можна", bool(app.under(base, "app.css")))
    check("підпапка — можна", bool(app.under(base, "avatars/cat.svg")))
    check("вгору по дереву — ні", app.under(base, "../app.py") is None)
    check("глибше вгору — ні", app.under(base, "a/../../config.py") is None)
    check("шлях від кореня — ні", app.under(base, "/etc/passwd") is None)
    check("шлях із диском — ні", app.under(base, "C:/Windows/win.ini") is None)
    check("зворотні скісні — ні", app.under(base, ".." + chr(92) + "app.py") is None)


def main():
    real_put = filestore.put
    filestore.put = lambda *a, **k: None      # бази в тесті немає
    tmp = tempfile.mkdtemp(prefix="shots")
    try:
        print("тип за байтами")
        by_bytes()
        print("розширення")
        extension_is_ours(tmp)
        print("не картинка")
        not_an_image(tmp)
        print("розмір")
        too_big(tmp)
        print("шляхи")
        paths_stay_inside()
    finally:
        filestore.put = real_put
    print("\nвсе гаразд")


if __name__ == "__main__":
    main()

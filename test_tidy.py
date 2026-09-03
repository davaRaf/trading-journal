# -*- coding: utf-8 -*-
"""
Перевірка пошуку однакового під різними іменами: python test_tidy.py

Головне тут — не «знайшли», а «не злипло зайве». Звести «US30» і «US100»
в одне гірше, ніж лишити «NAS 100» окремим рядком: статистика стане не
розділеною, а брехливою.
"""
import tidy


def t(pair="", session="", entry_model="", setup=""):
    return {"pair": pair, "session": session,
            "entry_model": entry_model, "setup": setup}


def names(groups, field="pair"):
    """Знайдені написання одного імені — відсортовані, щоб порівнювати."""
    for g in groups:
        if g["field"] == field:
            return sorted(v["value"] for v in g["variants"])
    return []


def case(name, got, want):
    ok = got == want
    print(("  ok  " if ok else "ПОМИЛКА") + "  " + name +
          ("" if ok else "  → отримали %s, чекали %s" % (got, want)))
    return ok


def main():
    ok = True

    # --- що має злипнутись ---
    ok &= case("пробіл усередині",
               names(tidy.scan([t("NAS100"), t("NAS 100")])),
               ["NAS 100", "NAS100"])
    ok &= case("регістр",
               names(tidy.scan([t("XAUUSD"), t("xauusd")])),
               ["XAUUSD", "xauusd"])
    ok &= case("дефіс і крапка",
               names(tidy.scan([t("US-100"), t("US.100")])),
               ["US-100", "US.100"])
    ok &= case("відомі назви одного інструмента",
               names(tidy.scan([t("US100"), t("NAS100")])),
               ["NAS100", "US100"])
    # «GER40» з кириличною Е всередині — оком не відрізнити, а це інший рядок
    ok &= case("кириличні двійники латинських літер",
               names(tidy.scan([t("GER40"), t("GЕR40")])),
               ["GER40", "GЕR40"])
    ok &= case("модель входу: регістр і пробіли",
               names(tidy.scan([t(entry_model="liquidity sweep"),
                                t(entry_model="Liquidity Sweep")]), "entry_model"),
               ["Liquidity Sweep", "liquidity sweep"])
    ok &= case("сесія під двома іменами",
               names(tidy.scan([t(session="NEW YORK"), t(session="NY")]), "session"),
               ["NEW YORK", "NY"])

    # --- що злипатись не повинно ---
    ok &= case("різні інструменти", tidy.scan([t("US30"), t("US100")]), [])
    ok &= case("одне написання — не група", tidy.scan([t("US100"), t("US100")]), [])
    ok &= case("порожні значення не рахуємо", tidy.scan([t(""), t("")]), [])
    ok &= case("порожнє й заповнене — не група", tidy.scan([t(""), t("US100")]), [])
    ok &= case("схожі, але різні моделі",
               tidy.scan([t(entry_model="cisd"), t(entry_model="cisd 2.0")]), [])
    ok &= case("порожній журнал", tidy.scan([]), [])

    # --- як показуємо ---
    groups = tidy.scan([t("NAS 100"), t("NAS 100"), t("NAS 100"), t("NAS100")])
    ok &= case("головним стає найчастіше написання", groups[0]["best"], "NAS 100")
    ok &= case("рахуємо угоди кожного написання",
               [(v["value"], v["count"]) for v in groups[0]["variants"]],
               [("NAS 100", 3), ("NAS100", 1)])
    ok &= case("усього в групі", groups[0]["total"], 4)

    many = tidy.scan([t("US100"), t("US 100")] * 5 + [t(session="NY"), t(session="ny")])
    ok &= case("більша група — першою", many[0]["field"], "pair")

    print("\n" + ("усе добре" if ok else "є помилки"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""Подделка Notion API для проверки импорта. Порт 8899."""
import base64, json, re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PNG = base64.b64decode(
    b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")

DB = {
    "object": "database", "id": "db-1",
    "title": [{"plain_text": "Trading Journal"}],
    "properties": {
        "Pair":        {"type": "title"},
        "Date":        {"type": "date"},
        "Направление": {"type": "select"},
        "Bias":        {"type": "select"},
        "Trade type":  {"type": "select"},
        "Entry model": {"type": "select"},
        "Setup":       {"type": "rich_text"},
        "Session":     {"type": "select"},
        "Результат":   {"type": "status"},
        "R:R":         {"type": "number"},
        "Risk %":      {"type": "number"},
        "Причина входа": {"type": "rich_text"},
        "Ошибки":      {"type": "rich_text"},
        "Скрины":      {"type": "files"},
        "Прочее":      {"type": "rich_text"},
    },
}


def page(i, pair, date, side, res, rr, risk, files=False):
    def sel(v): return {"type": "select", "select": {"name": v} if v else None}
    return {
        "object": "page", "id": "page-%d" % i, "has_children": True,
        "properties": {
            "Pair": {"type": "title", "title": [{"plain_text": pair}]},
            "Date": {"type": "date", "date": {"start": date}},
            "Направление": sel(side),
            "Bias": sel(side),
            "Trade type": sel("Продолжение" if i % 3 else "Разворот"),
            "Entry model": sel("cisd"),
            "Setup": {"type": "rich_text", "rich_text": [{"plain_text": "Frank manipulation"}]},
            "Session": sel("LONDON"),
            "Результат": {"type": "status", "status": {"name": res}},
            "R:R": {"type": "number", "number": rr},
            "Risk %": {"type": "number", "number": risk},
            "Причина входа": {"type": "rich_text",
                              "rich_text": [{"plain_text": "снятие хая, возврат в диапазон"}]},
            "Ошибки": {"type": "rich_text", "rich_text": [{"plain_text": "ранний вход" if i % 2 else ""}]},
            "Скрины": {"type": "files", "files": (
                [{"type": "external", "name": "15m.png",
                  "external": {"url": "http://127.0.0.1:8899/img/shot-15m.png"}}] if files else [])},
            "Прочее": {"type": "rich_text", "rich_text": []},
        },
    }


PAGES = [
    page(1, "US100",  "2026-02-10T09:54:00.000+02:00", "Long",  "TP",  2.2, 1.0, True),
    page(2, "GER40",  "2026-02-11",                    "Short", "SL",  1.8, 0.5),
    page(3, "XAUUSD", "2026-02-12T14:30:00.000+02:00", "long",  "BE+", 3.0, 1.0, True),
    page(4, "ES500",  "12.02.2026 16:00",              "sell",  "Win", 1.5, 2.0),
    page(5, "BTCUSD", "2026-02-13",                    "Short", "Loss", 4.0, 0.25),
]

BLOCKS = {
    "page-1": [
        {"type": "paragraph", "has_children": False,
         "paragraph": {"rich_text": [{"plain_text": "Вход после смены характера. Держал до цели."}]}},
        {"type": "bulleted_list_item", "has_children": False,
         "bulleted_list_item": {"rich_text": [{"plain_text": "не двигал стоп"}]}},
        {"type": "image", "has_children": False, "id": "img-1",
         "image": {"type": "external", "caption": [{"plain_text": "1H контекст"}],
                   "external": {"url": "http://127.0.0.1:8899/img/ctx.png"}}},
    ],
}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _j(self, obj, code=200):
        d = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(d)))
        self.end_headers()
        self.wfile.write(d)

    def _auth(self):
        if self.headers.get("Authorization") != "Bearer secret_good":
            self._j({"message": "API token is invalid."}, 401)
            return False
        return True

    def do_GET(self):
        if self.path.startswith("/img/"):
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(PNG)))
            self.end_headers()
            self.wfile.write(PNG)
            return
        if not self._auth():
            return
        if self.path.startswith("/v1/users/me"):
            return self._j({"name": "StatsAI import",
                            "bot": {"workspace_name": "Мій воркспейс"}})
        m = re.match(r"^/v1/blocks/([\w-]+)/children", self.path)
        if m:
            return self._j({"results": BLOCKS.get(m.group(1), []), "has_more": False})
        self._j({"message": "not found"}, 404)

    def do_POST(self):
        if not self._auth():
            return
        if self.path.startswith("/v1/search"):
            return self._j({"results": [DB], "has_more": False})
        if re.match(r"^/v1/databases/[\w-]+/query", self.path):
            return self._j({"results": PAGES, "has_more": False})
        self._j({"message": "not found"}, 404)


ThreadingHTTPServer(("127.0.0.1", 8899), H).serve_forever()

# -*- coding: utf-8 -*-
"""Куки: Secure тільки за https, гасіння тими самими ознаками."""
import sys, os
os.environ.setdefault("SESSION_SECRET", "x" * 40)
import auth, oauth

class H:
    def __init__(self, proto=None):
        self.headers = {"X-Forwarded-Proto": proto} if proto else {}
        self.headers = type("D", (), {"get": lambda s, k, d=None: (proto if k == "X-Forwarded-Proto" else d)})()

assert auth.is_https(H("https")) is True
assert auth.is_https(H("http")) is False
assert auth.is_https(H(None)) is False
assert auth.is_https(H("https, http")) is True          # ланцюжок проксі

c = auth.cookie_header("v", secure=True)
assert "Secure" in c and "HttpOnly" in c and "SameSite=Lax" in c and "Max-Age=2592000" in c, c
assert "Secure" not in auth.cookie_header("v", secure=False)

# гасіння має повторювати ознаки, інакше браузер лишить стару куку
d = auth.clear_cookie_header(secure=True)
assert "Max-Age=0" in d and "Secure" in d and "HttpOnly" in d, d
assert "Secure" not in auth.clear_cookie_header(secure=False)

assert "Secure" in oauth.state_cookie("s", True)
assert "Secure" not in oauth.state_cookie("s", False)
assert "Secure" in oauth.clear_state_cookie(True)

# підпис сесії живий
uid = auth.read_session(auth.make_session(7))
assert uid == 7, uid
assert auth.read_session("сміття") is None
assert auth.read_session(auth.make_session(7, ttl=-1)) is None   # протермінована

print("тести куки пройшли")

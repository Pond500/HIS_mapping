"""
paths.py
========
Where the app sits on its host. Behind the server's nginx it is served under a
prefix (https://HOST/his_mapping/...), which nginx strips before passing the
request on; so the routes stay "/login", "/api/...", but every link, fetch and
redirect the browser sees must carry the prefix, or it lands on the bare host
(another project's pages, or nothing).

ROOT_PATH in .env, e.g. "/his_mapping". Empty (the default) = served at "/",
as on a developer machine and in the tests.
"""

import os

from dotenv import load_dotenv

load_dotenv()

ROOT_PATH = os.getenv("ROOT_PATH", "").strip().rstrip("/")
if ROOT_PATH and not ROOT_PATH.startswith("/"):
    ROOT_PATH = "/" + ROOT_PATH


def url(path: str) -> str:
    """A path inside the app ("/login") as the browser must ask for it."""
    return ROOT_PATH + path


class RestorePrefix:
    """Puts the prefix back on a request whose proxy stripped it.

    ASGI expects `path` to still include `root_path`; Starlette's routes cope either
    way, but a mount does not: with "/static/..." under root_path "/his_mapping",
    StaticFiles looked for the file at the wrong place and every stylesheet and
    script answered 404 (the login page came out unstyled on the server, 2026-11-12).
    With this, the proxy may strip the prefix or pass it on; both work."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if ROOT_PATH and scope["type"] in ("http", "websocket"):
            path = scope["path"]
            if path != ROOT_PATH and not path.startswith(ROOT_PATH + "/"):
                full = ROOT_PATH + path
                scope = {**scope, "path": full, "raw_path": full.encode()}
        await self.app(scope, receive, send)

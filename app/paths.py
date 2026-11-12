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

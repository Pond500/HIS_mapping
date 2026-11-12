"""Behind nginx the app lives under a prefix (app/paths.py). A link written as
"/login" instead of "{{ base }}/login" sends the browser to the bare host, which
on the server is not this app at all."""

import pathlib
import re

APP = pathlib.Path(__file__).resolve().parent.parent / "app"
ROUTES = r"(?:api|static|login|logout|health-report|summary|reviews|people|import|walkthrough|registration|workplaces|rounds|users|profile|manual)"
BARE = re.compile(r"[\"'`]/" + ROUTES + r"(?![A-Za-z])|href=\"/\"")


def test_no_template_links_past_the_prefix():
    bad = [f"{f.name}:{n}: {line.strip()}"
           for f in sorted((APP / "templates").glob("*.html"))
           for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1)
           if BARE.search(line)]
    assert not bad, "\n".join(bad)


def test_static_scripts_call_the_api_through_the_prefix():
    for f in (APP / "static" / "js").glob("*.js"):
        bad = [n for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1)
               if re.search(r"[\"'`]/api/", line) and "BASE_URL" not in line]
        assert not bad, f"{f.name} lines {bad}"


def test_url_adds_the_prefix(monkeypatch):
    from app import paths
    monkeypatch.setattr(paths, "ROOT_PATH", "/his_mapping")
    assert paths.url("/login") == "/his_mapping/login"


def test_a_stripped_prefix_is_put_back(monkeypatch):
    # the server's nginx strips /his_mapping; StaticFiles then 404'd every stylesheet
    import asyncio
    from app import paths
    monkeypatch.setattr(paths, "ROOT_PATH", "/his_mapping")
    seen = []

    async def inner(scope, receive, send):
        seen.append(scope["path"])

    mw = paths.RestorePrefix(inner)
    for p in ("/static/css/envocc.css", "/his_mapping/static/css/envocc.css", "/his_mapping"):
        asyncio.run(mw({"type": "http", "path": p, "raw_path": p.encode()}, None, None))
    assert seen == ["/his_mapping/static/css/envocc.css", "/his_mapping/static/css/envocc.css", "/his_mapping"]

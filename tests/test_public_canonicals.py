import importlib
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree

import pytest
from fastapi.testclient import TestClient


class PageHead(HTMLParser):
    def __init__(self):
        super().__init__()
        self.canonicals = []
        self.open_graph_urls = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "link" and attrs.get("rel") == "canonical":
            self.canonicals.append(attrs.get("href"))
        if tag == "meta" and attrs.get("property") == "og:url":
            self.open_graph_urls.append(attrs.get("content"))


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("VOICEFORGE_ENGINE", "mock")
    monkeypatch.setenv("VOICEFORGE_DATA_DIR", str(tmp_path / "data"))
    import app.config
    import app.main

    importlib.reload(app.config)
    module = importlib.reload(app.main)
    with TestClient(module.app) as test_client:
        yield test_client


def assert_page_url(response, expected):
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    head = PageHead()
    head.feed(response.text)
    assert head.canonicals == [expected]
    assert head.open_graph_urls == [expected]


def test_sitemap_pages_have_correct_canonicals_before_javascript(client):
    sitemap = ElementTree.fromstring(client.get("/sitemap.xml").text)
    urls = sitemap.findall("{http://www.sitemaps.org/schemas/sitemap/0.9}url")
    assert len(urls) >= 8
    for url in urls:
        canonical = url.findtext("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")
        path = canonical.removeprefix("https://aivoicegeneratorhq.com")
        for suffix in ("", "?utm_source=test&preset=energetic&next=%2Fpricing"):
            assert_page_url(client.get(path + suffix), canonical)


@pytest.mark.parametrize("host", ["preview.example:8080", "preview.example/path"])
def test_canonicals_use_public_origin_instead_of_request_host(client, host):
    for path in ("/", "/pricing", "/studio"):
        response = client.get(path, headers={
            "host": host,
            "x-forwarded-host": "untrusted.example",
            "x-forwarded-proto": "http",
        })
        assert_page_url(response, "https://aivoicegeneratorhq.com" + path)


def test_index_alias_keeps_home_canonical(client):
    assert_page_url(client.get("/index.html"), "https://aivoicegeneratorhq.com/")


def test_javascript_does_not_rewrite_server_urls():
    javascript = (Path(__file__).parents[1] / "app" / "static" / "app.js").read_text(
        encoding="utf-8"
    )
    assert 'link[rel="canonical"]' not in javascript
    assert 'meta[property="og:url"]' not in javascript

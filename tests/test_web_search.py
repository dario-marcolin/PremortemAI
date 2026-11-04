import pytest

from premortem import config
from premortem.tools import web_search as ws


class FakeClient:
    def __init__(self, response):
        self.response = response

    def invoke(self, _input):
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


@pytest.fixture
def fake_client(monkeypatch):
    monkeypatch.setattr(config, "TAVILY_API_KEY", "test-key")

    def install(response):
        monkeypatch.setattr(ws, "_client", lambda: FakeClient(response))

    return install


def search(query="plant-based snacks market France"):
    return ws.web_search.invoke({"query": query})


def test_results_are_compact(fake_client):
    results = [
        {"title": f"T{i}", "url": f"https://example.com/{i}", "content": "x" * 2000, "raw_content": "page"}
        for i in range(8)
    ]
    fake_client({"results": results})
    out = search()
    assert len(out) == config.MAX_SEARCH_RESULTS
    assert set(out[0]) == {"title", "url", "snippet"}
    assert len(out[0]["snippet"]) == ws.SNIPPET_CHARS


def test_results_without_url_are_dropped(fake_client):
    fake_client({"results": [{"title": "no url", "content": "x"}, {"title": "ok", "url": "https://a.fr"}]})
    assert [r["url"] for r in search()] == ["https://a.fr"]


@pytest.mark.parametrize(
    "response",
    [RuntimeError("timeout"), {"error": "rate limit"}, {"results": []}, "No search results found"],
)
def test_errors_are_returned_as_data(fake_client, response):
    fake_client(response)
    out = search()
    assert len(out) == 1 and "error" in out[0]


def test_missing_api_key(monkeypatch):
    monkeypatch.setattr(config, "TAVILY_API_KEY", None)
    assert "TAVILY_API_KEY" in search()[0]["error"]


@pytest.mark.skipif(not config.TAVILY_API_KEY, reason="needs TAVILY_API_KEY")
def test_live_search():
    out = search()
    assert out and all(r["url"].startswith("http") for r in out)

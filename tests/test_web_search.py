import pytest

from premortem import config
from premortem.config import RunSettings
from premortem.llm import using_settings
from premortem.tools import web_search as ws

SETTINGS = RunSettings.preset("anthropic", "sk-ant-test", tavily_api_key="tvly-test")


class FakeClient:
    def __init__(self, response):
        self.response = response

    def invoke(self, _input):
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


@pytest.fixture
def fake_client(monkeypatch):
    def install(response):
        monkeypatch.setattr(ws, "_client", lambda _key: FakeClient(response))

    return install


def search(query="plant-based snacks market France", settings=SETTINGS):
    with using_settings(settings):
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


def test_missing_api_key_is_a_warning_not_a_crash():
    no_tavily = RunSettings.preset("anthropic", "sk-ant-test")
    assert search(settings=no_tavily) == [{"error": ws.NO_KEY}]


def test_outside_a_run_there_is_no_key():
    assert ws.web_search.invoke({"query": "x"}) == [{"error": ws.NO_KEY}]


def test_each_search_uses_the_key_of_its_own_run(monkeypatch):
    seen = []
    monkeypatch.setattr(ws, "_client", lambda key: seen.append(key) or FakeClient({"results": []}))
    search(settings=RunSettings.preset("anthropic", "a", tavily_api_key="tvly-A"))
    search(settings=RunSettings.preset("anthropic", "b", tavily_api_key="tvly-B"))
    assert seen == ["tvly-A", "tvly-B"]


LIVE = RunSettings.from_env(mode="public")  # only Tavily is read here


@pytest.mark.skipif(not LIVE.tavily_api_key, reason="needs TAVILY_API_KEY")
def test_live_search():
    out = search(settings=LIVE)
    assert out and all(r["url"].startswith("http") for r in out)

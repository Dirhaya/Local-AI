"""No live internet needed: URL guards, pinning, extraction, and route gating."""
from unittest.mock import patch
import socket

import pytest
from fastapi import HTTPException

from app.browser_core import (
    FetchedPage, _PinnedHTTPSConnection, extract_readable_page,
    extract_search_results, fetch_public_html, normalize_public_url,
    research_search, resolve_public_addresses,
)


@pytest.mark.parametrize("url", [
    "http://example.com", "https://localhost/", "https://a.local/", "https://printer/",
    "https://127.0.0.1/", "https://169.254.169.254/latest/meta-data/",
    "https://10.0.0.1", "https://[::1]", "https://[::ffff:127.0.0.1]",
    "https://[64:ff9b::7f00:1]", "https://224.0.0.1/",
    "https://example.com:8080/", "https://user:pass@example.com/",
    "https://example.com/\nHeader: injected", "file:///etc/passwd", "javascript:alert(1)",
    "https://example.com\\@127.0.0.1/",
])
def test_rejects_non_public_or_unsafe_urls(url):
    with pytest.raises(ValueError):
        normalize_public_url(url)


def test_normalizes_url_without_resolving():
    with patch("socket.getaddrinfo", side_effect=AssertionError("must not resolve")):
        assert normalize_public_url("https://Example.COM:443/café?q=a%20b#part") == "https://example.com/caf%C3%A9?q=a%20b"


def test_rejects_mixed_public_and_private_dns_answers():
    answers = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
    ]
    with patch("socket.getaddrinfo", return_value=answers):
        with pytest.raises(ValueError, match="private"):
            resolve_public_addresses("example.com")


def test_pins_numeric_ip_and_keeps_tls_hostname():
    raw = object()
    tls = object()
    connection = _PinnedHTTPSConnection("example.com", "93.184.216.34", 4)
    with patch("socket.create_connection", return_value=raw) as connect:
        with patch.object(connection._context, "wrap_socket", return_value=tls) as wrap:
            connection.connect()
    connect.assert_called_once_with(("93.184.216.34", 443), 4)
    wrap.assert_called_once_with(raw, server_hostname="example.com")
    assert connection.sock is tls


def test_search_extracts_only_safe_organic_results_and_unwraps_links():
    html = """<div class="result result--ad"><a class="result__a" href="https://ad.example.com">Ad</a></div>
    <div class="result"><a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fairline.example%2Fflights">A <b>flight</b></a>
      <span class="result__snippet">Price must be checked. &lt;img onerror=evil&gt;</span></div>
    <div class="result"><a class="result__a" href="javascript:alert(1)">Bad</a></div>
    <div class="result"><a class="result__a" href="https://127.0.0.1">Private</a></div>
    <div class="result"><a class="result__a" href="https://airline.example/flights">Duplicate</a></div>"""
    results = extract_search_results(html)
    assert len(results) == 1
    assert results[0]["title"] == "A flight"
    assert results[0]["url"] == "https://airline.example/flights"
    # Markup is retained solely as inert text. UI must render textContent/escape.
    assert "<img onerror=evil>" in results[0]["snippet"]


def test_reader_strips_executable_and_navigation_content():
    page = FetchedPage("https://example.com/", b"<title>Flight</title><nav>Navigation</nav><main>Useful<script>evil()</script><iframe src='https://bad.example'></iframe><form>Password</form></main>", "text/html")
    output = extract_readable_page(page)
    assert output == {"url": "https://example.com/", "title": "Flight", "text": "Useful"}


def test_search_failure_is_honest_and_gives_manual_handoff():
    with patch("app.browser_core.fetch_public_html", side_effect=ValueError("Website returned HTTP 429.")):
        result = research_search("DXB to London flights")
    assert result["results"] == []
    assert "429" in result["warning"]
    assert result["search_url"].startswith("https://duckduckgo.com/?q=")


def test_search_blocked_page_does_not_invent_results():
    with patch("app.browser_core.fetch_public_html", return_value=FetchedPage("https://html.duckduckgo.com/", b"<html>CAPTCHA</html>", "text/html")):
        result = research_search("shopping")
    assert result["results"] == []
    assert "blocked" in result["warning"]


def test_network_disabled_blocks_before_fetch():
    from app.browser import ResearchRequest, research, read_page, PageRequest

    class LockedNetwork:
        def settings(self):
            return {"network_enabled": False}

    with patch("app.browser.research_search", side_effect=AssertionError("network must not be called")):
        with pytest.raises(HTTPException) as exc:
            research(ResearchRequest(query="flights"), LockedNetwork())
        assert exc.value.status_code == 403
    with patch("app.browser.fetch_public_html", side_effect=AssertionError("network must not be called")):
        with pytest.raises(HTTPException):
            read_page(PageRequest(url="https://example.com/"), LockedNetwork())


def test_redirect_destination_is_revalidated_before_next_connection():
    class Response:
        status = 302
        def getheader(self, key):
            return "https://127.0.0.1/private" if key == "Location" else None
        def close(self):
            pass

    class Connection:
        sock = None
        def __init__(self, *args):
            pass
        def request(self, *args, **kwargs):
            pass
        def getresponse(self):
            return Response()
        def close(self):
            pass

    with patch("app.browser_core.resolve_public_addresses", return_value=["93.184.216.34"]):
        with patch("app.browser_core._PinnedHTTPSConnection", Connection):
            with pytest.raises(ValueError, match="Private"):
                fetch_public_html("https://example.com/")


def test_summarize_uses_only_selected_public_results_and_no_memory():
    from app.browser import summarize_errand

    class ResearchVault:
        def __init__(self):
            self.checked = False
        def get(self, kind, identity):
            assert (kind, identity) == ("errands", "research-1")
            return {"id": identity, "query": "flights", "category": "flights", "results": [
                {"title": "Airline", "url": "https://airline.example/", "snippet": "Check availability"}
            ]}
        def check_unlocked(self):
            self.checked = True
        def put(self, kind, record):
            assert self.checked
            return record
        def list(self, kind):
            raise AssertionError("Summary must not read private memory or other records")

    vault = ResearchVault()
    with patch("app.ai.generate", return_value="Check the airline website.") as model:
        record = summarize_errand("research-1", vault)
    assert record["summary"] == "Check the airline website."
    messages = model.call_args.args[1]
    assert len(messages) == 2
    assert "untrusted" in messages[0]["content"]
    assert "airline.example" in messages[1]["content"]
    assert model.call_args.kwargs["json_mode"] is False

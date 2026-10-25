"""Bounded, DNS-pinned public HTTPS retrieval and inert search/page extraction.

No browser execution, cookies, account logins, proxies, or automatic model actions.
Only explicit requests from the local application call these functions.
"""
from __future__ import annotations

from dataclasses import dataclass
import http.client
import ipaddress
import socket
import ssl
import time
from urllib.parse import parse_qs, quote, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_PAGE_TEXT = 24_000
MAX_QUERY = 1000
FETCH_SECONDS = 20


@dataclass(frozen=True)
class FetchedPage:
    url: str
    body: bytes
    content_type: str


def _is_public_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if not address.is_global or address.is_multicast or address.is_reserved or address.is_unspecified:
        return False
    if isinstance(address, ipaddress.IPv6Address):
        # Transition mechanisms can hide an otherwise blocked IPv4 destination.
        if address.ipv4_mapped or address.sixtofour or address.teredo:
            return False
        if address in ipaddress.ip_network("64:ff9b::/96") or address in ipaddress.ip_network("64:ff9b:1::/48"):
            return False
    return True


def normalize_public_url(url: str) -> str:
    """Validate URL syntax without making DNS requests.

    DNS is checked separately immediately before a pinned connection. Search
    extraction deliberately does not resolve every displayed result.
    """
    if not isinstance(url, str) or len(url) > 4096:
        raise ValueError("Use a public HTTPS URL under 4096 characters.")
    if any(ord(c) < 32 or ord(c) == 127 for c in url) or "\\" in url:
        raise ValueError("URL contains invalid characters.")
    try:
        parsed = urlsplit(url.strip())
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Invalid URL.") from exc
    if parsed.scheme.lower() != "https" or not host or port not in (None, 443):
        raise ValueError("Only public HTTPS URLs on port 443 can be read.")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URLs containing credentials are not allowed.")
    host = host.rstrip(".").lower()
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError("Invalid website hostname.") from exc
    if host in {"localhost", "localhost.localdomain"} or host.endswith(
        (".localhost", ".local", ".internal", ".home", ".lan", ".test", ".invalid")
    ) or "." not in host and ":" not in host:
        raise ValueError("Private or local website addresses are not allowed.")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not _is_public_address(address):
        raise ValueError("Private or reserved IP addresses are not allowed.")
    if address is not None and address.version == 6:
        authority = f"[{host}]"
    else:
        authority = host
    path = quote(parsed.path or "/", safe="/%:@!$&'()*+,;=-._~")
    query = quote(parsed.query, safe="%=&?/:@!$'()*+,;~-._")
    return urlunsplit(("https", authority, path, query, ""))


def resolve_public_addresses(host: str) -> list[str]:
    """Reject a name when any resolved answer is non-public.

    The chosen numeric address is passed directly to connect(), so an attacker
    cannot rebind DNS between validation and the actual HTTPS connection.
    """
    try:
        answers = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError("Could not resolve that public website.") from exc
    addresses = []
    for answer in answers:
        value = answer[4][0]
        try:
            address = ipaddress.ip_address(value)
        except ValueError as exc:
            raise ValueError("Invalid address returned by website DNS.") from exc
        if not _is_public_address(address):
            raise ValueError("Website DNS resolves to a private or reserved address.")
        if value not in addresses:
            addresses.append(value)
    if not addresses:
        raise ValueError("Website DNS returned no usable public address.")
    return addresses


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, hostname: str, numeric_address: str, timeout: float):
        super().__init__(hostname, port=443, timeout=timeout,
                         context=ssl.create_default_context())
        self.numeric_address = numeric_address

    def connect(self):
        # Numeric IP prevents a second hostname lookup. TLS still authenticates
        # the original site, and the HTTP Host header remains the original site.
        connection = socket.create_connection((self.numeric_address, 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(connection, server_hostname=self.host)
        except Exception:
            connection.close()
            raise


def fetch_public_html(url: str, *, max_bytes: int = MAX_BODY_BYTES) -> FetchedPage:
    current = normalize_public_url(url)
    deadline = time.monotonic() + FETCH_SECONDS
    for redirect_count in range(5):
        parsed = urlsplit(current)
        addresses = resolve_public_addresses(parsed.hostname or "")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError("Website request timed out.")
        connection = _PinnedHTTPSConnection(parsed.hostname or "", addresses[0], min(8, remaining))
        response = None
        try:
            target = parsed.path or "/"
            if parsed.query:
                target += "?" + parsed.query
            connection.request("GET", target, headers={
                "User-Agent": "SultanLocalAI/1.0 (personal research; no JavaScript)",
                "Accept": "text/html,text/plain;q=0.9",
                "Accept-Encoding": "identity",
                "Connection": "close",
            })
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader("Location")
                if not location or redirect_count == 4:
                    raise ValueError("Website redirected too many times or without a destination.")
                current = normalize_public_url(urljoin(current, location))
                continue
            if response.status != 200:
                raise ValueError(f"Website returned HTTP {response.status}. Open the source in your browser.")
            content_type = (response.getheader("Content-Type") or "").lower()
            if not any(t in content_type for t in ("text/html", "text/plain", "application/xhtml+xml")):
                raise ValueError("Only HTML or plain-text pages can be read.")
            encoding = (response.getheader("Content-Encoding") or "identity").lower()
            if encoding not in ("", "identity"):
                raise ValueError("Website sent a compressed response; open it in your browser.")
            length = response.getheader("Content-Length")
            if length:
                try:
                    if int(length) > max_bytes:
                        raise ValueError("Website page exceeds the configured reading limit (at most 2 MB).")
                except ValueError:
                    raise ValueError("Website page has an invalid or excessive content length.")
            parts = []
            total = 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ValueError("Website request timed out.")
                if connection.sock:
                    connection.sock.settimeout(min(8, remaining))
                part = response.read(min(65536, max_bytes - total + 1))
                if not part:
                    break
                parts.append(part)
                total += len(part)
                if total > max_bytes:
                    raise ValueError("Website page exceeds the configured reading limit (at most 2 MB).")
            return FetchedPage(current, b"".join(parts), content_type)
        except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
            # Never expose request strings, server headers, or low-level errors.
            raise ValueError("Could not retrieve the website securely. Open it in your browser.") from exc
        finally:
            if response:
                response.close()
            connection.close()
    raise ValueError("Website redirected too many times.")


def extract_search_results(html: bytes | str, *, limit: int = 8) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    results = []
    seen = set()
    for container in soup.select(".result"):
        classes = container.get("class", [])
        if "result--ad" in classes or container.select_one(".badge--ad"):
            continue
        anchor = container.select_one("a.result__a")
        if not anchor:
            continue
        target = anchor.get("href", "")
        if target.startswith("//"):
            target = "https:" + target
        try:
            parsed = urlsplit(target)
            if (parsed.hostname or "").lower() in {"duckduckgo.com", "www.duckduckgo.com", "html.duckduckgo.com"}:
                wrapped = parse_qs(parsed.query).get("uddg", [])
                if not wrapped:
                    continue
                target = wrapped[0]
            target = normalize_public_url(target)
        except (ValueError, TypeError):
            continue
        if target in seen:
            continue
        title = " ".join(anchor.stripped_strings)[:300]
        snippet_node = container.select_one(".result__snippet")
        snippet = " ".join(snippet_node.stripped_strings)[:1200] if snippet_node else ""
        if not title:
            continue
        seen.add(target)
        results.append({"title": title, "url": target, "snippet": snippet})
        if len(results) >= limit:
            break
    return results


def extract_readable_page(page: FetchedPage) -> dict:
    if "text/plain" in page.content_type:
        return {"url": page.url, "title": urlsplit(page.url).hostname,
                "text": page.body.decode("utf-8", errors="replace")[:MAX_PAGE_TEXT]}
    soup = BeautifulSoup(page.body, "html.parser")
    title = soup.title.get_text(" ", strip=True)[:300] if soup.title else urlsplit(page.url).hostname
    for node in soup.select("script,style,noscript,iframe,svg,form,nav,footer,header,aside"):
        node.decompose()
    main = soup.select_one("main,article,[role=main]") or soup.body or soup
    text = "\n".join(line.strip() for line in main.get_text("\n").splitlines() if line.strip())
    return {"url": page.url, "title": title, "text": text[:MAX_PAGE_TEXT]}


def research_search(query: str) -> dict:
    query = " ".join(query.split()).strip()
    if not query or len(query) > MAX_QUERY:
        raise ValueError("Enter a search query of 1 to 1000 characters.")
    search_url = "https://duckduckgo.com/?" + urlencode({"q": query})
    endpoint = "https://html.duckduckgo.com/html/?" + urlencode({"q": query})
    try:
        page = fetch_public_html(endpoint)
        results = extract_search_results(page.body)
        warning = "" if results else (
            "The search engine returned no readable results or blocked automated access. "
            "Open the search link in your browser. No results or prices were invented."
        )
    except ValueError as exc:
        results = []
        warning = "Search unavailable: " + str(exc) + " Use the search link in your browser."
    return {"results": results, "search_url": search_url, "search_query": query, "warning": warning}

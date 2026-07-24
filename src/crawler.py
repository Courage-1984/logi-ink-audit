"""Asynchronous sitemap ingestion and HTTP endpoint crawler."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Iterable
from urllib.parse import urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    "LogiInkAuditBot/1.0 (+https://logi-ink.co.za; technical SEO / GEO / AEO audit)"
)
SITEMAP_CANDIDATES = (
    "/sitemap.xml",
    "/sitemap_index.xml",
    "/sitemap-index.xml",
)


@dataclass
class PageFetch:
    """Result of fetching a single URL."""

    url: str
    final_url: str
    status_code: int
    latency_ms: float
    html: str
    content_type: str
    redirected: bool
    redirect_chain: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and 200 <= self.status_code < 400

    @property
    def soup(self) -> BeautifulSoup | None:
        if not self.html:
            return None
        return BeautifulSoup(self.html, "lxml")


class AsyncCrawler:
    """Discover URLs via sitemap (with homepage fallback) and fetch pages concurrently."""

    def __init__(
        self,
        base_url: str,
        *,
        concurrency: int = 8,
        timeout_seconds: float = 30.0,
        user_agent: str = DEFAULT_USER_AGENT,
        max_pages: int | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.concurrency = max(1, concurrency)
        self.timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self.user_agent = user_agent
        self.max_pages = max_pages
        self._semaphore = asyncio.Semaphore(self.concurrency)

    async def discover_urls(self, session: aiohttp.ClientSession) -> list[str]:
        """Ingest sitemap URL sets; fall back to homepage link discovery."""
        urls: list[str] = []
        for path in SITEMAP_CANDIDATES:
            sitemap_url = urljoin(self.base_url + "/", path.lstrip("/"))
            found = await self._parse_sitemap(session, sitemap_url, depth=0)
            if found:
                urls.extend(found)
                logger.info("Discovered %d URL(s) from %s", len(found), sitemap_url)
                break

        if not urls:
            logger.warning("No sitemap found; discovering links from homepage.")
            urls = await self._discover_from_homepage(session)

        normalised = self._normalise_url_list(urls)
        if self.max_pages is not None:
            normalised = normalised[: self.max_pages]
        return normalised

    async def crawl(self, urls: Iterable[str] | None = None) -> list[PageFetch]:
        """Fetch all target URLs concurrently and return page results."""
        connector = aiohttp.TCPConnector(limit=self.concurrency)
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-GB,en;q=0.9",
        }
        async with aiohttp.ClientSession(
            connector=connector,
            timeout=self.timeout,
            headers=headers,
        ) as session:
            targets = list(urls) if urls is not None else await self.discover_urls(session)
            if not targets:
                logger.error("No URLs to crawl.")
                return []
            logger.info("Crawling %d URL(s) with concurrency=%d", len(targets), self.concurrency)
            tasks = [self._fetch(session, url) for url in targets]
            results = await asyncio.gather(*tasks)
            return list(results)

    async def _fetch(self, session: aiohttp.ClientSession, url: str) -> PageFetch:
        async with self._semaphore:
            started = time.perf_counter()
            redirect_chain: list[str] = []
            try:
                async with session.get(url, allow_redirects=True) as response:
                    body = await response.read()
                    latency_ms = (time.perf_counter() - started) * 1000
                    content_type = response.headers.get("Content-Type", "")
                    html = ""
                    if "html" in content_type.lower() or url.endswith((".html", "/")) or not content_type:
                        try:
                            html = body.decode(response.charset or "utf-8", errors="replace")
                        except Exception:
                            html = body.decode("utf-8", errors="replace")

                    for hist in response.history:
                        redirect_chain.append(str(hist.url))

                    return PageFetch(
                        url=url,
                        final_url=str(response.url),
                        status_code=response.status,
                        latency_ms=round(latency_ms, 2),
                        html=html,
                        content_type=content_type,
                        redirected=bool(response.history),
                        redirect_chain=redirect_chain,
                    )
            except asyncio.TimeoutError:
                latency_ms = (time.perf_counter() - started) * 1000
                return PageFetch(
                    url=url,
                    final_url=url,
                    status_code=0,
                    latency_ms=round(latency_ms, 2),
                    html="",
                    content_type="",
                    redirected=False,
                    error="Request timed out",
                )
            except aiohttp.ClientError as exc:
                latency_ms = (time.perf_counter() - started) * 1000
                return PageFetch(
                    url=url,
                    final_url=url,
                    status_code=0,
                    latency_ms=round(latency_ms, 2),
                    html="",
                    content_type="",
                    redirected=False,
                    error=f"Client error: {exc}",
                )

    async def _parse_sitemap(
        self,
        session: aiohttp.ClientSession,
        sitemap_url: str,
        *,
        depth: int,
    ) -> list[str]:
        if depth > 3:
            return []
        try:
            async with session.get(sitemap_url) as response:
                if response.status >= 400:
                    return []
                text = await response.text(errors="replace")
        except aiohttp.ClientError as exc:
            logger.debug("Failed to fetch sitemap %s: %s", sitemap_url, exc)
            return []

        soup = BeautifulSoup(text, "lxml-xml")
        urls: list[str] = []

        # Sitemap index → recurse into child sitemaps
        for loc in soup.select("sitemap > loc"):
            child = (loc.get_text() or "").strip()
            if child:
                urls.extend(await self._parse_sitemap(session, child, depth=depth + 1))

        for loc in soup.select("url > loc"):
            page = (loc.get_text() or "").strip()
            if page:
                urls.append(page)

        # Plain-text / non-XML fallback: extract same-host http(s) links
        if not urls and "<url" not in text.lower() and "<sitemap" not in text.lower():
            urls.extend(re.findall(r"https?://[^\s<>\"']+", text))

        return urls

    async def _discover_from_homepage(self, session: aiohttp.ClientSession) -> list[str]:
        try:
            async with session.get(self.base_url) as response:
                if response.status >= 400:
                    return [self.base_url]
                html = await response.text(errors="replace")
        except aiohttp.ClientError:
            return [self.base_url]

        soup = BeautifulSoup(html, "lxml")
        found = {self.base_url}
        host = urlparse(self.base_url).netloc
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"].strip()
            if href.startswith(("#", "mailto:", "tel:", "javascript:")):
                continue
            absolute = urljoin(self.base_url + "/", href)
            parsed = urlparse(absolute)
            if parsed.scheme not in ("http", "https"):
                continue
            if parsed.netloc != host:
                continue
            clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/") or self.base_url
            if parsed.path.endswith((".pdf", ".jpg", ".png", ".gif", ".svg", ".zip", ".webp")):
                continue
            found.add(clean)
        return sorted(found)

    def _normalise_url_list(self, urls: Iterable[str]) -> list[str]:
        host = urlparse(self.base_url).netloc
        seen: set[str] = set()
        ordered: list[str] = []
        for raw in urls:
            raw = raw.strip()
            if not raw:
                continue
            parsed = urlparse(raw)
            if parsed.scheme not in ("http", "https"):
                continue
            if parsed.netloc and parsed.netloc != host:
                continue
            # Drop asset / non-HTML paths that sometimes appear in image sitemaps
            path = parsed.path.lower()
            if path.endswith(
                (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".pdf", ".css", ".js", ".ico")
            ):
                continue
            normalised = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            if normalised != self.base_url:
                normalised = normalised.rstrip("/")
            if normalised not in seen:
                seen.add(normalised)
                ordered.append(normalised)
        if self.base_url not in seen:
            ordered.insert(0, self.base_url)
        return ordered

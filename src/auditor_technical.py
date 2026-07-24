"""Technical accessibility and contextual AEO checks for AI overview readiness."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from .crawler import PageFetch

# Landmarks weighted by AI crawlers for layout chunking
REQUIRED_LANDMARKS: tuple[str, ...] = ("main", "nav", "header")
SKIP_HREF_PREFIXES: tuple[str, ...] = ("#", "mailto:", "tel:", "javascript:", "data:")


@dataclass
class TechnicalAuditResult:
    """Per-page accessibility and internal-link density findings."""

    url: str

    html_lang: str
    html_lang_present: bool
    html_lang_en_za: bool

    images_total: int
    missing_alt_count: int
    empty_alt_count: int
    alt_issues_count: int
    alt_coverage_ok: bool

    has_main: bool
    has_nav: bool
    has_header: bool
    landmark_coverage_ok: bool
    landmarks_found: str

    internal_link_count: int
    external_link_count: int
    total_links: int
    internal_link_ratio: float
    link_density_ok: bool
    orphan_risk: bool

    technical_issues: list[str] = field(default_factory=list)
    technical_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "html_lang": self.html_lang,
            "html_lang_present": self.html_lang_present,
            "html_lang_en_za": self.html_lang_en_za,
            "images_total": self.images_total,
            "missing_alt_count": self.missing_alt_count,
            "empty_alt_count": self.empty_alt_count,
            "alt_issues_count": self.alt_issues_count,
            "alt_coverage_ok": self.alt_coverage_ok,
            "has_main": self.has_main,
            "has_nav": self.has_nav,
            "has_header": self.has_header,
            "landmark_coverage_ok": self.landmark_coverage_ok,
            "landmarks_found": self.landmarks_found,
            "internal_link_count": self.internal_link_count,
            "external_link_count": self.external_link_count,
            "total_links": self.total_links,
            "internal_link_ratio": self.internal_link_ratio,
            "link_density_ok": self.link_density_ok,
            "orphan_risk": self.orphan_risk,
            "technical_issues": "; ".join(self.technical_issues),
            "technical_score": self.technical_score,
        }


class TechnicalAuditor:
    """Evaluate accessibility attributes, semantic landmarks, and link density."""

    def __init__(self, base_url: str = "https://logi-ink.co.za") -> None:
        self.base_url = base_url.rstrip("/")
        self.base_host = urlparse(self.base_url).netloc.lower()

    def audit(self, page: PageFetch) -> TechnicalAuditResult:
        issues: list[str] = []
        soup = page.soup

        if page.error or soup is None:
            result = self._empty_result(page.url)
            if page.error:
                issues.append(f"Fetch failed: {page.error}")
            else:
                issues.append("No HTML body to analyse")
            result.technical_issues = issues
            result.technical_score = 0.0
            return result

        html_lang, lang_present, lang_en_za = self._html_lang(soup)
        if not lang_present:
            issues.append("Missing html lang attribute")
        elif not lang_en_za:
            issues.append(f'html lang is "{html_lang}" (expected en-ZA)')

        images_total, missing_alt, empty_alt = self._image_alt_stats(soup)
        alt_issues = missing_alt + empty_alt
        alt_ok = alt_issues == 0
        if missing_alt:
            issues.append(f"{missing_alt} image(s) missing alt attribute")
        if empty_alt:
            issues.append(f"{empty_alt} image(s) with empty alt text")

        has_main = soup.find("main") is not None
        has_nav = soup.find("nav") is not None
        has_header = soup.find("header") is not None
        landmark_ok = has_main and has_nav and has_header
        found = [tag for tag in REQUIRED_LANDMARKS if soup.find(tag)]
        if not landmark_ok:
            missing = [tag for tag in REQUIRED_LANDMARKS if tag not in found]
            issues.append(f"Missing semantic landmarks: {', '.join(missing)}")

        page_url = page.final_url or page.url
        internal, external = self._link_counts(soup, page_url)
        total = internal + external
        ratio = round(internal / total, 3) if total else 0.0
        # Poorly connected pages: few internal links relative to content graph expectations
        link_density_ok = internal >= 3 and (total == 0 or ratio >= 0.5)
        orphan_risk = internal < 2
        if orphan_risk:
            issues.append(
                f"Low internal link density ({internal} internal / {external} external) — orphan risk"
            )
        elif not link_density_ok:
            issues.append(
                f"Weak internal link density (ratio {ratio:.0%}; {internal} internal links)"
            )

        result = TechnicalAuditResult(
            url=page.url,
            html_lang=html_lang,
            html_lang_present=lang_present,
            html_lang_en_za=lang_en_za,
            images_total=images_total,
            missing_alt_count=missing_alt,
            empty_alt_count=empty_alt,
            alt_issues_count=alt_issues,
            alt_coverage_ok=alt_ok,
            has_main=has_main,
            has_nav=has_nav,
            has_header=has_header,
            landmark_coverage_ok=landmark_ok,
            landmarks_found=", ".join(found),
            internal_link_count=internal,
            external_link_count=external,
            total_links=total,
            internal_link_ratio=ratio,
            link_density_ok=link_density_ok,
            orphan_risk=orphan_risk,
            technical_issues=issues,
        )
        result.technical_score = self._score(result)
        return result

    def _empty_result(self, url: str) -> TechnicalAuditResult:
        return TechnicalAuditResult(
            url=url,
            html_lang="",
            html_lang_present=False,
            html_lang_en_za=False,
            images_total=0,
            missing_alt_count=0,
            empty_alt_count=0,
            alt_issues_count=0,
            alt_coverage_ok=False,
            has_main=False,
            has_nav=False,
            has_header=False,
            landmark_coverage_ok=False,
            landmarks_found="",
            internal_link_count=0,
            external_link_count=0,
            total_links=0,
            internal_link_ratio=0.0,
            link_density_ok=False,
            orphan_risk=True,
        )

    @staticmethod
    def _html_lang(soup: BeautifulSoup) -> tuple[str, bool, bool]:
        html_tag = soup.find("html")
        if not isinstance(html_tag, Tag):
            return "", False, False
        lang = str(html_tag.get("lang") or "").strip()
        present = bool(lang)
        en_za = lang.lower().replace("_", "-") == "en-za"
        return lang, present, en_za

    @staticmethod
    def _image_alt_stats(soup: BeautifulSoup) -> tuple[int, int, int]:
        """Return (total images, missing alt attribute, empty alt text)."""
        images = soup.find_all("img")
        missing = 0
        empty = 0
        for img in images:
            if not isinstance(img, Tag):
                continue
            if not img.has_attr("alt"):
                missing += 1
                continue
            if str(img.get("alt") or "").strip() == "":
                empty += 1
        return len(images), missing, empty

    def _link_counts(self, soup: BeautifulSoup, page_url: str) -> tuple[int, int]:
        internal = 0
        external = 0
        seen: set[str] = set()

        for anchor in soup.find_all("a", href=True):
            href = str(anchor["href"]).strip()
            if not href or href.lower().startswith(SKIP_HREF_PREFIXES):
                continue
            absolute = urljoin(page_url, href)
            parsed = urlparse(absolute)
            if parsed.scheme not in ("http", "https"):
                continue
            key = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")
            if key in seen:
                continue
            seen.add(key)
            host = parsed.netloc.lower()
            if host == self.base_host or host.endswith("." + self.base_host):
                internal += 1
            else:
                external += 1

        return internal, external

    @staticmethod
    def _score(result: TechnicalAuditResult) -> float:
        checks = [
            result.html_lang_en_za,
            result.alt_coverage_ok,
            result.has_main,
            result.has_nav,
            result.has_header,
            result.landmark_coverage_ok,
            result.link_density_ok,
            not result.orphan_risk,
        ]
        return round(100.0 * sum(1 for check in checks if check) / len(checks), 1)

"""Technical SEO auditor for status, metadata, headings, Open Graph, and canonicals."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, NavigableString, Tag

from .crawler import PageFetch

BRAND_TOKENS = ("logi-ink", "logi ink", "logiink")
EXPECTED_OG_IMAGE_SUFFIXES = (
    "/assets/images/og-image.png",
    "/assets/images/portfolio/",
)
PREFERRED_BRAND: str = "Logi-Ink"
PREFERRED_HUB_PHRASE: str = "Content Optimisation Hub"
AMERICAN_HUB_PHRASE: str = "Content Optimization Hub"

# Americanised spellings → preferred UK forms (scanned in visible text / metadata only)
AMERICAN_TO_UK: tuple[tuple[str, str], ...] = (
    ("optimization", "optimisation"),
    ("optimize", "optimise"),
    ("optimized", "optimised"),
    ("optimizing", "optimising"),
    ("organization", "organisation"),
    ("organizations", "organisations"),
    ("organize", "organise"),
    ("organized", "organised"),
    ("organizing", "organising"),
    ("center", "centre"),
    ("centers", "centres"),
    ("color", "colour"),
    ("colors", "colours"),
    ("behavior", "behaviour"),
    ("behaviors", "behaviours"),
    ("favor", "favour"),
    ("favorite", "favourite"),
    ("analyze", "analyse"),
    ("analyzing", "analysing"),
    ("analyzed", "analysed"),
)

TITLE_MIN, TITLE_MAX = 30, 60
DESC_MIN, DESC_MAX = 70, 160

SKIP_TERMINOLOGY_TAGS: frozenset[str] = frozenset(
    {"script", "style", "code", "pre", "noscript", "svg", "path", "textarea"}
)


@dataclass
class SeoAuditResult:
    """Per-page technical SEO findings."""

    url: str
    status_code: int
    latency_ms: float
    redirected: bool
    redirect_chain: str
    fetch_error: str | None

    title: str
    title_length: int
    title_present: bool
    title_length_ok: bool
    title_brand_ok: bool

    meta_description: str
    meta_description_length: int
    meta_description_present: bool
    meta_description_length_ok: bool

    h1_count: int
    h1_text: str
    heading_outline: str
    heading_skip_detected: bool
    heading_hierarchy_ok: bool
    missing_alt_count: int
    images_total: int

    og_title: str
    og_description: str
    og_image: str
    og_title_present: bool
    og_description_present: bool
    og_image_present: bool
    og_image_path_ok: bool

    canonical: str
    canonical_present: bool
    canonical_ok: bool

    terminology_issues: list[str] = field(default_factory=list)
    terminology_ok: bool = True

    issues: list[str] = field(default_factory=list)
    score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "status_code": self.status_code,
            "latency_ms": self.latency_ms,
            "redirected": self.redirected,
            "redirect_chain": self.redirect_chain,
            "fetch_error": self.fetch_error or "",
            "title": self.title,
            "title_length": self.title_length,
            "title_present": self.title_present,
            "title_length_ok": self.title_length_ok,
            "title_brand_ok": self.title_brand_ok,
            "meta_description": self.meta_description,
            "meta_description_length": self.meta_description_length,
            "meta_description_present": self.meta_description_present,
            "meta_description_length_ok": self.meta_description_length_ok,
            "h1_count": self.h1_count,
            "h1_text": self.h1_text,
            "heading_outline": self.heading_outline,
            "heading_skip_detected": self.heading_skip_detected,
            "heading_hierarchy_ok": self.heading_hierarchy_ok,
            "missing_alt_count": self.missing_alt_count,
            "images_total": self.images_total,
            "og_title": self.og_title,
            "og_description": self.og_description,
            "og_image": self.og_image,
            "og_title_present": self.og_title_present,
            "og_description_present": self.og_description_present,
            "og_image_present": self.og_image_present,
            "og_image_path_ok": self.og_image_path_ok,
            "canonical": self.canonical,
            "canonical_present": self.canonical_present,
            "canonical_ok": self.canonical_ok,
            "terminology_issues": "; ".join(self.terminology_issues),
            "terminology_ok": self.terminology_ok,
            "seo_issues": "; ".join(self.issues),
            "seo_score": self.score,
        }


class SeoAuditor:
    """Evaluate technical SEO signals on a fetched page."""

    def __init__(self, brand_name: str = "Logi-Ink", base_url: str = "https://logi-ink.co.za") -> None:
        self.brand_name = brand_name
        self.base_url = base_url.rstrip("/")

    def audit(self, page: PageFetch) -> SeoAuditResult:
        issues: list[str] = []
        soup = page.soup

        if page.error or soup is None:
            result = self._empty_result(page, issues)
            if page.error:
                issues.append(f"Fetch failed: {page.error}")
            elif page.status_code == 0:
                issues.append("No response received")
            else:
                issues.append("No HTML body to analyse")
            result.issues = issues
            result.score = self._score(result)
            return result

        if page.status_code >= 400:
            issues.append(f"HTTP {page.status_code}")
        elif page.status_code >= 300:
            issues.append(f"Unexpected status {page.status_code}")

        title = self._title(soup)
        title_present = bool(title)
        title_length = len(title)
        title_length_ok = TITLE_MIN <= title_length <= TITLE_MAX if title_present else False
        title_brand_ok = self._brand_in_text(title) if title_present else False
        if not title_present:
            issues.append("Missing <title>")
        else:
            if not title_length_ok:
                issues.append(f"Title length {title_length} outside {TITLE_MIN}–{TITLE_MAX}")
            if not title_brand_ok:
                issues.append("Title does not reference brand")

        meta_description = self._meta_content(soup, "description")
        meta_present = bool(meta_description)
        meta_length = len(meta_description)
        meta_length_ok = DESC_MIN <= meta_length <= DESC_MAX if meta_present else False
        if not meta_present:
            issues.append("Missing meta description")
        elif not meta_length_ok:
            issues.append(f"Meta description length {meta_length} outside {DESC_MIN}–{DESC_MAX}")

        headings = self._headings(soup)
        h1s = [h for h in headings if h[0] == 1]
        h1_count = len(h1s)
        h1_text = " | ".join(t for _, t in h1s)[:300]
        outline = " > ".join(f"H{level}:{text[:40]}" for level, text in headings[:20])
        skip_detected, hierarchy_ok = self._heading_hierarchy(headings)
        if h1_count == 0:
            issues.append("Missing H1")
            hierarchy_ok = False
        elif h1_count > 1:
            issues.append(f"Multiple H1 tags ({h1_count})")
        if skip_detected:
            issues.append("Heading level skip detected")

        images_total, missing_alt = self._image_alt_stats(soup)
        if missing_alt:
            issues.append(f"{missing_alt} image(s) missing alt text")

        og_title = self._og(soup, "og:title")
        og_description = self._og(soup, "og:description")
        og_image = self._og(soup, "og:image")
        og_title_present = bool(og_title)
        og_description_present = bool(og_description)
        og_image_present = bool(og_image)
        og_image_path_ok = self._og_image_path_ok(og_image, page.final_url or page.url)
        if not og_title_present:
            issues.append("Missing og:title")
        if not og_description_present:
            issues.append("Missing og:description")
        if not og_image_present:
            issues.append("Missing og:image")
        elif not og_image_path_ok:
            issues.append("og:image path does not match expected asset patterns")

        canonical = self._canonical(soup)
        canonical_present = bool(canonical)
        canonical_ok = self._canonical_ok(canonical, page.final_url or page.url) if canonical_present else False
        if not canonical_present:
            issues.append("Missing canonical link")
        elif not canonical_ok:
            issues.append("Canonical does not align with page URL")

        terminology_issues = self._terminology_issues(
            soup,
            title=title,
            meta_description=meta_description,
            og_title=og_title,
            og_description=og_description,
            h1_text=h1_text,
        )
        terminology_ok = not terminology_issues
        if terminology_issues:
            issues.extend(terminology_issues[:5])

        result = SeoAuditResult(
            url=page.url,
            status_code=page.status_code,
            latency_ms=page.latency_ms,
            redirected=page.redirected,
            redirect_chain=" → ".join(page.redirect_chain) if page.redirect_chain else "",
            fetch_error=page.error,
            title=title,
            title_length=title_length,
            title_present=title_present,
            title_length_ok=title_length_ok,
            title_brand_ok=title_brand_ok,
            meta_description=meta_description,
            meta_description_length=meta_length,
            meta_description_present=meta_present,
            meta_description_length_ok=meta_length_ok,
            h1_count=h1_count,
            h1_text=h1_text,
            heading_outline=outline,
            heading_skip_detected=skip_detected,
            heading_hierarchy_ok=hierarchy_ok,
            missing_alt_count=missing_alt,
            images_total=images_total,
            og_title=og_title,
            og_description=og_description,
            og_image=og_image,
            og_title_present=og_title_present,
            og_description_present=og_description_present,
            og_image_present=og_image_present,
            og_image_path_ok=og_image_path_ok,
            canonical=canonical,
            canonical_present=canonical_present,
            canonical_ok=canonical_ok,
            terminology_issues=terminology_issues,
            terminology_ok=terminology_ok,
            issues=issues,
        )
        result.score = self._score(result)
        return result

    def _empty_result(self, page: PageFetch, issues: list[str]) -> SeoAuditResult:
        return SeoAuditResult(
            url=page.url,
            status_code=page.status_code,
            latency_ms=page.latency_ms,
            redirected=page.redirected,
            redirect_chain=" → ".join(page.redirect_chain) if page.redirect_chain else "",
            fetch_error=page.error,
            title="",
            title_length=0,
            title_present=False,
            title_length_ok=False,
            title_brand_ok=False,
            meta_description="",
            meta_description_length=0,
            meta_description_present=False,
            meta_description_length_ok=False,
            h1_count=0,
            h1_text="",
            heading_outline="",
            heading_skip_detected=False,
            heading_hierarchy_ok=False,
            missing_alt_count=0,
            images_total=0,
            og_title="",
            og_description="",
            og_image="",
            og_title_present=False,
            og_description_present=False,
            og_image_present=False,
            og_image_path_ok=False,
            canonical="",
            canonical_present=False,
            canonical_ok=False,
            terminology_issues=[],
            terminology_ok=False,
            issues=issues,
        )

    @staticmethod
    def _title(soup: BeautifulSoup) -> str:
        tag = soup.find("title")
        return tag.get_text(strip=True) if tag else ""

    @staticmethod
    def _meta_content(soup: BeautifulSoup, name: str) -> str:
        tag = soup.find("meta", attrs={"name": name})
        if tag and tag.get("content"):
            return str(tag["content"]).strip()
        return ""

    @staticmethod
    def _og(soup: BeautifulSoup, property_name: str) -> str:
        tag = soup.find("meta", attrs={"property": property_name})
        if tag and tag.get("content"):
            return str(tag["content"]).strip()
        # Some generators use name= instead of property=
        tag = soup.find("meta", attrs={"name": property_name})
        if tag and tag.get("content"):
            return str(tag["content"]).strip()
        return ""

    @staticmethod
    def _canonical(soup: BeautifulSoup) -> str:
        tag = soup.find("link", attrs={"rel": lambda v: v and "canonical" in str(v).lower()})
        if isinstance(tag, Tag) and tag.get("href"):
            return str(tag["href"]).strip()
        return ""

    @staticmethod
    def _headings(soup: BeautifulSoup) -> list[tuple[int, str]]:
        results: list[tuple[int, str]] = []
        for tag in soup.find_all(re.compile(r"^h[1-6]$", re.I)):
            level = int(tag.name[1])
            text = tag.get_text(" ", strip=True)
            results.append((level, text))
        return results

    @staticmethod
    def _heading_hierarchy(headings: list[tuple[int, str]]) -> tuple[bool, bool]:
        """Return (skip_detected, hierarchy_ok)."""
        if not headings:
            return False, False
        skip = False
        prev = headings[0][0]
        if prev != 1:
            # Starting below H1 is a structural concern but not always a skip
            skip = prev > 1
        for level, _ in headings[1:]:
            if level > prev + 1:
                skip = True
            prev = level
        h1_count = sum(1 for level, _ in headings if level == 1)
        ok = (not skip) and h1_count == 1
        return skip, ok

    @staticmethod
    def _image_alt_stats(soup: BeautifulSoup) -> tuple[int, int]:
        images = soup.find_all("img")
        missing = 0
        for img in images:
            if not isinstance(img, Tag):
                continue
            alt = img.get("alt")
            if alt is None or str(alt).strip() == "":
                # Decorative images may intentionally use alt=""; still flag empty/missing for audit
                if alt is None:
                    missing += 1
                elif str(alt).strip() == "" and img.get("role") != "presentation":
                    # Empty alt is valid for decorative; do not count as missing
                    continue
        return len(images), missing

    def _brand_in_text(self, text: str) -> bool:
        lowered = text.lower()
        if self.brand_name.lower() in lowered:
            return True
        return any(token in lowered for token in BRAND_TOKENS)

    def _terminology_issues(
        self,
        soup: BeautifulSoup,
        *,
        title: str,
        meta_description: str,
        og_title: str,
        og_description: str,
        h1_text: str,
    ) -> list[str]:
        """Flag Americanised spellings and brand casing in user-facing copy only."""
        findings: list[str] = []
        samples = [
            ("title", title),
            ("meta description", meta_description),
            ("og:title", og_title),
            ("og:description", og_description),
            ("H1", h1_text),
        ]
        body_text = self._visible_body_text(soup)
        samples.append(("body copy", body_text))

        for label, text in samples:
            if not text:
                continue
            findings.extend(self._american_spelling_hits(text, label))
            findings.extend(self._brand_casing_hits(text, label))

        # De-duplicate whilst preserving order
        seen: set[str] = set()
        unique: list[str] = []
        for item in findings:
            if item not in seen:
                seen.add(item)
                unique.append(item)
        return unique

    @staticmethod
    def _visible_body_text(soup: BeautifulSoup) -> str:
        chunks: list[str] = []
        root = soup.find("main") or soup.find("article") or soup.body or soup
        for element in root.descendants:
            if isinstance(element, NavigableString):
                parent = element.parent
                if parent is None or parent.name in SKIP_TERMINOLOGY_TAGS:
                    continue
                text = str(element).strip()
                if text:
                    chunks.append(text)
        return " ".join(chunks)

    @staticmethod
    def _american_spelling_hits(text: str, label: str) -> list[str]:
        hits: list[str] = []
        lowered = text.lower()
        for american, british in AMERICAN_TO_UK:
            pattern = re.compile(rf"\b{re.escape(american)}\b", re.IGNORECASE)
            if pattern.search(lowered):
                hits.append(
                    f"Americanised spelling in {label}: '{american}' (prefer '{british}')"
                )
        if AMERICAN_HUB_PHRASE.lower() in lowered:
            hits.append(
                f"Americanised hub phrasing in {label}: "
                f"'{AMERICAN_HUB_PHRASE}' (prefer '{PREFERRED_HUB_PHRASE}')"
            )
        return hits

    def _brand_casing_hits(self, text: str, label: str) -> list[str]:
        hits: list[str] = []
        # Flag near-brand tokens that are not exact Logi-Ink casing
        for match in re.finditer(r"\bLogi[\s\-]?Ink\b", text, flags=re.IGNORECASE):
            token = match.group(0)
            if token != PREFERRED_BRAND:
                hits.append(
                    f"Brand casing in {label}: '{token}' (prefer '{PREFERRED_BRAND}')"
                )
        return hits

    def _og_image_path_ok(self, og_image: str, page_url: str) -> bool:
        if not og_image:
            return False
        absolute = urljoin(page_url, og_image)
        path = urlparse(absolute).path.lower()
        if any(path.endswith(sfx.rstrip("/").split("/")[-1]) or sfx.rstrip("/") in path for sfx in EXPECTED_OG_IMAGE_SUFFIXES):
            return True
        # Accept absolute URLs under the site's assets/images tree
        if "/assets/images/" in path and path.endswith((".png", ".jpg", ".jpeg", ".webp")):
            return True
        return False

    def _canonical_ok(self, canonical: str, page_url: str) -> bool:
        absolute = urljoin(page_url, canonical)
        left = urlparse(absolute)
        right = urlparse(page_url)
        left_path = left.path.rstrip("/") or "/"
        right_path = right.path.rstrip("/") or "/"
        return left.netloc == right.netloc and left_path == right_path

    @staticmethod
    def _score(result: SeoAuditResult) -> float:
        checks = [
            200 <= result.status_code < 400,
            result.title_present,
            result.title_length_ok,
            result.title_brand_ok,
            result.meta_description_present,
            result.meta_description_length_ok,
            result.heading_hierarchy_ok,
            result.missing_alt_count == 0,
            result.og_title_present,
            result.og_description_present,
            result.og_image_present,
            result.og_image_path_ok,
            result.canonical_present,
            result.canonical_ok,
            result.terminology_ok,
        ]
        if not checks:
            return 0.0
        return round(100.0 * sum(1 for c in checks if c) / len(checks), 1)

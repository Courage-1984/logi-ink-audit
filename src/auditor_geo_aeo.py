"""GEO and AEO auditor: structured data, SA localisation, semantic HTML, and entity mapping."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from bs4 import BeautifulSoup, Tag

from .crawler import PageFetch

logger = logging.getLogger(__name__)

EXPECTED_SCHEMA_TYPES: tuple[str, ...] = (
    "Organization",
    "LocalBusiness",
    "ProfessionalService",
    "Service",
    "WebSite",
    "WebPage",
    "BreadcrumbList",
    "FAQPage",
    "Offer",
    "Product",
    "Person",
    "ContactPoint",
    "ImageObject",
)

ORG_SCHEMA_TYPES: frozenset[str] = frozenset(
    {"Organization", "LocalBusiness", "ProfessionalService"}
)
SERVICE_PRODUCT_TYPES: frozenset[str] = frozenset({"Service", "Product", "Offer"})

SEMANTIC_TAGS: tuple[str, ...] = (
    "article",
    "section",
    "header",
    "footer",
    "main",
    "aside",
    "nav",
)

# South African localisation expectations for Logi-Ink
REQUIRED_ADDRESS_REGION: str = "Gauteng"
REQUIRED_ADDRESS_LOCALITY: str = "Pretoria"
REQUIRED_ADDRESS_COUNTRY: str = "ZA"
REQUIRED_PRICE_CURRENCY: str = "ZAR"
REQUIRED_HTML_LANG: str = "en-ZA"

DEFINITION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b\w[\w\s-]{2,40}\s+is\s+(?:a|an|the)\b", re.I),
    re.compile(r"\bwhat\s+is\b.{0,40}\?", re.I),
    re.compile(r"\b(?:definition|overview|in\s+short|tl;?dr)\b", re.I),
)
KEY_VALUE_PATTERN: re.Pattern[str] = re.compile(
    r"^(?:name|address|phone|email|hours|price|location|tel|mobile)\s*[:–—-]\s*.+",
    re.I | re.M,
)
PHONE_PATTERN: re.Pattern[str] = re.compile(
    r"(?:\+?\d{1,3}[\s-]?)?(?:\(?0?\d{2,3}\)?[\s-]?)?\d{3}[\s-]?\d{4}",
)
NAP_NAME_HINTS: tuple[str, ...] = ("logi-ink", "logi ink")


@dataclass
class GeoAeoAuditResult:
    """Per-page GEO / AEO findings including South African localisation."""

    url: str

    json_ld_blocks: int
    schema_types: list[str]
    schema_types_str: str
    has_organization: bool
    has_local_business: bool
    has_service: bool
    has_website: bool
    has_breadcrumb: bool
    schema_valid: bool
    schema_parse_errors: list[str]
    json_ld_parse_fail: bool

    # South African localisation signals
    address_region: str
    address_locality: str
    address_country: str
    address_region_ok: bool
    address_locality_ok: bool
    address_country_ok: bool
    price_currency: str
    price_currency_ok: bool
    price_currency_applicable: bool
    html_lang: str
    html_lang_en_za: bool
    local_seo_compliance: bool
    local_seo_status: str
    localisation_gaps: list[str]

    semantic_tags_found: list[str]
    semantic_tags_str: str
    semantic_coverage_ok: bool

    direct_answer_blocks: int
    has_definition_pattern: bool
    has_key_value_pairs: bool
    has_structured_lists: bool
    has_summary_block: bool
    direct_answer_ready: bool

    nap_name_found: bool
    nap_address_found: bool
    nap_phone_found: bool
    nap_complete: bool
    same_as_profiles: list[str]
    same_as_str: str
    has_same_as: bool
    entity_mapping_ok: bool

    geo_issues: list[str] = field(default_factory=list)
    aeo_issues: list[str] = field(default_factory=list)
    geo_score: float = 0.0
    aeo_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "json_ld_blocks": self.json_ld_blocks,
            "schema_types": self.schema_types_str,
            "detected_schema_types": self.schema_types_str,
            "has_organization": self.has_organization,
            "has_local_business": self.has_local_business,
            "has_service": self.has_service,
            "has_website": self.has_website,
            "has_breadcrumb": self.has_breadcrumb,
            "schema_valid": self.schema_valid,
            "schema_parse_errors": "; ".join(self.schema_parse_errors),
            "json_ld_parse_fail": self.json_ld_parse_fail,
            "address_region": self.address_region,
            "address_locality": self.address_locality,
            "address_country": self.address_country,
            "address_region_ok": self.address_region_ok,
            "address_locality_ok": self.address_locality_ok,
            "address_country_ok": self.address_country_ok,
            "price_currency": self.price_currency,
            "price_currency_ok": self.price_currency_ok,
            "price_currency_applicable": self.price_currency_applicable,
            "html_lang": self.html_lang,
            "html_lang_en_za": self.html_lang_en_za,
            "local_seo_compliance": self.local_seo_compliance,
            "local_seo_status": self.local_seo_status,
            "localisation_gaps": "; ".join(self.localisation_gaps),
            "semantic_tags": self.semantic_tags_str,
            "semantic_coverage_ok": self.semantic_coverage_ok,
            "direct_answer_blocks": self.direct_answer_blocks,
            "has_definition_pattern": self.has_definition_pattern,
            "has_key_value_pairs": self.has_key_value_pairs,
            "has_structured_lists": self.has_structured_lists,
            "has_summary_block": self.has_summary_block,
            "direct_answer_ready": self.direct_answer_ready,
            "nap_name_found": self.nap_name_found,
            "nap_address_found": self.nap_address_found,
            "nap_phone_found": self.nap_phone_found,
            "nap_complete": self.nap_complete,
            "same_as_profiles": self.same_as_str,
            "has_same_as": self.has_same_as,
            "entity_mapping_ok": self.entity_mapping_ok,
            "geo_issues": "; ".join(self.geo_issues),
            "aeo_issues": "; ".join(self.aeo_issues),
            "geo_score": self.geo_score,
            "aeo_score": self.aeo_score,
        }


class GeoAeoAuditor:
    """Evaluate Generative Engine Optimisation and Answer Engine Optimisation signals."""

    def audit(self, page: PageFetch) -> GeoAeoAuditResult:
        geo_issues: list[str] = []
        aeo_issues: list[str] = []
        soup = page.soup

        if page.error or soup is None:
            result = self._empty_result(page.url)
            if page.error:
                geo_issues.append(f"Fetch failed: {page.error}")
                aeo_issues.append(f"Fetch failed: {page.error}")
            else:
                geo_issues.append("No HTML body to analyse")
                aeo_issues.append("No HTML body to analyse")
            result.geo_issues = geo_issues
            result.aeo_issues = aeo_issues
            result.local_seo_status = "Fail"
            result.local_seo_compliance = False
            return result

        schemas, parse_errors = self._extract_json_ld(soup)
        json_ld_parse_fail = bool(parse_errors)
        schema_types = sorted(self._collect_types(schemas))
        has_organization = any(t in ORG_SCHEMA_TYPES for t in schema_types)
        has_local_business = "LocalBusiness" in schema_types or "ProfessionalService" in schema_types
        has_service = "Service" in schema_types or "Offer" in schema_types or "Product" in schema_types
        has_website = "WebSite" in schema_types
        has_breadcrumb = "BreadcrumbList" in schema_types
        # Malformed JSON-LD is treated as a Fail even if other blocks parsed
        schema_valid = bool(schemas) and not parse_errors

        if not schemas and not parse_errors:
            geo_issues.append("No JSON-LD structured data found")
        if parse_errors:
            geo_issues.append(
                f"JSON-LD parse Fail: {'; '.join(parse_errors[:3])}"
            )
            logger.warning(
                "Malformed JSON-LD on %s: %s",
                page.url,
                "; ".join(parse_errors[:3]),
            )
        if not has_organization:
            geo_issues.append("Missing Organization / LocalBusiness schema")
        if not has_website:
            geo_issues.append("Missing WebSite schema")
        if not has_breadcrumb:
            geo_issues.append("Missing BreadcrumbList schema")

        localisation = self._validate_sa_localisation(soup, schemas, schema_types)
        localisation_gaps = list(localisation["gaps"])
        for gap in localisation_gaps:
            geo_issues.append(gap)

        semantic_found = [tag for tag in SEMANTIC_TAGS if soup.find(tag)]
        core = {"main", "header", "footer", "section"}
        semantic_ok = core.issubset(set(semantic_found)) or (
            "main" in semantic_found and len(semantic_found) >= 3
        )
        if not semantic_ok:
            missing = sorted(core - set(semantic_found))
            geo_issues.append(f"Limited semantic HTML (missing: {', '.join(missing)})")
            aeo_issues.append("Semantic landmarks insufficient for reliable AI chunking")

        text = soup.get_text("\n", strip=True)
        has_definition = any(pattern.search(text) for pattern in DEFINITION_PATTERNS)
        has_kv = bool(KEY_VALUE_PATTERN.search(text))
        lists = soup.find_all(["ul", "ol"])
        structured_lists = sum(
            1 for lst in lists if len(lst.find_all("li", recursive=False)) >= 3
        )
        has_lists = structured_lists > 0
        has_summary = self._has_summary_block(soup)
        answer_signals = sum([has_definition, has_kv, has_lists, has_summary])
        direct_answer_blocks = answer_signals
        direct_ready = answer_signals >= 2
        if not has_definition:
            aeo_issues.append("No clear definition / direct-answer phrasing detected")
        if not has_lists:
            aeo_issues.append("No structured lists suitable for AI extraction")
        if not has_summary:
            aeo_issues.append("No standalone summary / lead block detected")
        if not direct_ready:
            aeo_issues.append("Page is not yet direct-answer ready")

        same_as = self._collect_same_as(schemas)
        nap_name, nap_address, nap_phone = self._nap_signals(soup, schemas, text)
        nap_complete = nap_name and nap_address and nap_phone
        entity_ok = nap_name and (nap_phone or nap_address) and (bool(same_as) or has_organization)
        if not nap_name:
            geo_issues.append("Brand / NAP name not clearly present")
        if not nap_address:
            geo_issues.append("Address / locality not detected in markup or schema")
        if not nap_phone:
            geo_issues.append("Phone number not detected in markup or schema")
        if not same_as:
            geo_issues.append("No sameAs social / external profile links in schema")

        local_ok = bool(localisation["compliant"])
        result = GeoAeoAuditResult(
            url=page.url,
            json_ld_blocks=len(schemas),
            schema_types=schema_types,
            schema_types_str=", ".join(schema_types) if schema_types else "",
            has_organization=has_organization,
            has_local_business=has_local_business,
            has_service=has_service,
            has_website=has_website,
            has_breadcrumb=has_breadcrumb,
            schema_valid=schema_valid,
            schema_parse_errors=parse_errors,
            json_ld_parse_fail=json_ld_parse_fail,
            address_region=str(localisation["address_region"]),
            address_locality=str(localisation["address_locality"]),
            address_country=str(localisation["address_country"]),
            address_region_ok=bool(localisation["address_region_ok"]),
            address_locality_ok=bool(localisation["address_locality_ok"]),
            address_country_ok=bool(localisation["address_country_ok"]),
            price_currency=str(localisation["price_currency"]),
            price_currency_ok=bool(localisation["price_currency_ok"]),
            price_currency_applicable=bool(localisation["price_currency_applicable"]),
            html_lang=str(localisation["html_lang"]),
            html_lang_en_za=bool(localisation["html_lang_en_za"]),
            local_seo_compliance=local_ok,
            local_seo_status="Pass" if local_ok else "Fail",
            localisation_gaps=localisation_gaps,
            semantic_tags_found=semantic_found,
            semantic_tags_str=", ".join(semantic_found),
            semantic_coverage_ok=semantic_ok,
            direct_answer_blocks=direct_answer_blocks,
            has_definition_pattern=has_definition,
            has_key_value_pairs=has_kv,
            has_structured_lists=has_lists,
            has_summary_block=has_summary,
            direct_answer_ready=direct_ready,
            nap_name_found=nap_name,
            nap_address_found=nap_address,
            nap_phone_found=nap_phone,
            nap_complete=nap_complete,
            same_as_profiles=same_as,
            same_as_str=", ".join(same_as),
            has_same_as=bool(same_as),
            entity_mapping_ok=entity_ok,
            geo_issues=geo_issues,
            aeo_issues=aeo_issues,
        )
        result.geo_score = self._geo_score(result)
        result.aeo_score = self._aeo_score(result)
        return result

    def _empty_result(self, url: str) -> GeoAeoAuditResult:
        return GeoAeoAuditResult(
            url=url,
            json_ld_blocks=0,
            schema_types=[],
            schema_types_str="",
            has_organization=False,
            has_local_business=False,
            has_service=False,
            has_website=False,
            has_breadcrumb=False,
            schema_valid=False,
            schema_parse_errors=[],
            json_ld_parse_fail=False,
            address_region="",
            address_locality="",
            address_country="",
            address_region_ok=False,
            address_locality_ok=False,
            address_country_ok=False,
            price_currency="",
            price_currency_ok=False,
            price_currency_applicable=False,
            html_lang="",
            html_lang_en_za=False,
            local_seo_compliance=False,
            local_seo_status="Fail",
            localisation_gaps=["No HTML body to analyse"],
            semantic_tags_found=[],
            semantic_tags_str="",
            semantic_coverage_ok=False,
            direct_answer_blocks=0,
            has_definition_pattern=False,
            has_key_value_pairs=False,
            has_structured_lists=False,
            has_summary_block=False,
            direct_answer_ready=False,
            nap_name_found=False,
            nap_address_found=False,
            nap_phone_found=False,
            nap_complete=False,
            same_as_profiles=[],
            same_as_str="",
            has_same_as=False,
            entity_mapping_ok=False,
        )

    def _extract_json_ld(self, soup: BeautifulSoup) -> tuple[list[Any], list[str]]:
        """Locate and parse all application/ld+json blocks with graceful failure handling."""
        blocks: list[Any] = []
        errors: list[str] = []
        for script in soup.find_all(
            "script",
            attrs={"type": lambda value: value and "ld+json" in str(value).lower()},
        ):
            raw = script.string or script.get_text() or ""
            raw = raw.strip()
            if not raw:
                continue
            try:
                data = json.loads(raw)
                blocks.append(data)
            except json.JSONDecodeError as exc:
                cleaned = re.sub(r",\s*([}\]])", r"\1", raw)
                try:
                    blocks.append(json.loads(cleaned))
                except json.JSONDecodeError:
                    message = f"Fail — malformed JSON-LD ({exc.msg})"
                    errors.append(message)
                    logger.debug("JSON-LD decode error: %s", exc)
        return blocks, errors

    def _collect_types(self, schemas: list[Any]) -> set[str]:
        found: set[str] = set()

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                type_val = node.get("@type")
                if isinstance(type_val, str):
                    # Strip schema.org URL prefixes if present
                    found.add(type_val.rsplit("/", 1)[-1])
                elif isinstance(type_val, list):
                    for item in type_val:
                        if isinstance(item, str):
                            found.add(item.rsplit("/", 1)[-1])
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        for block in schemas:
            walk(block)
        return found

    def _validate_sa_localisation(
        self,
        soup: BeautifulSoup,
        schemas: list[Any],
        schema_types: list[str],
    ) -> dict[str, Any]:
        """Validate Pretoria / Gauteng / ZA / ZAR / en-ZA localisation signals."""
        gaps: list[str] = []

        html_tag = soup.find("html")
        html_lang = ""
        if isinstance(html_tag, Tag):
            html_lang = str(html_tag.get("lang") or "").strip()
        html_lang_en_za = html_lang.lower().replace("_", "-") == REQUIRED_HTML_LANG.lower()
        if not html_lang:
            gaps.append(f'Missing <html lang="{REQUIRED_HTML_LANG}">')
        elif not html_lang_en_za:
            gaps.append(
                f'html lang is "{html_lang}" (expected {REQUIRED_HTML_LANG})'
            )

        address_fields = self._collect_address_fields(schemas)
        region = address_fields["addressRegion"]
        locality = address_fields["addressLocality"]
        country = address_fields["addressCountry"]

        region_ok = REQUIRED_ADDRESS_REGION.lower() in region.lower() if region else False
        locality_ok = REQUIRED_ADDRESS_LOCALITY.lower() in locality.lower() if locality else False
        country_normalised = country.upper().replace("SOUTH AFRICA", "ZA").strip()
        if country_normalised in {"ZAF", "SOUTH AFRICA"}:
            country_normalised = "ZA"
        country_ok = country_normalised == REQUIRED_ADDRESS_COUNTRY

        org_present = any(t in ORG_SCHEMA_TYPES for t in schema_types)
        if org_present:
            if not region:
                gaps.append("Organisation schema missing addressRegion (expected Gauteng)")
            elif not region_ok:
                gaps.append(
                    f'addressRegion is "{region}" (expected to include {REQUIRED_ADDRESS_REGION})'
                )
            if not locality:
                gaps.append("Organisation schema missing addressLocality (expected Pretoria)")
            elif not locality_ok:
                gaps.append(
                    f'addressLocality is "{locality}" (expected to include {REQUIRED_ADDRESS_LOCALITY})'
                )
            if not country:
                gaps.append("Organisation schema missing addressCountry (expected ZA)")
            elif not country_ok:
                gaps.append(
                    f'addressCountry is "{country}" (expected {REQUIRED_ADDRESS_COUNTRY})'
                )
        else:
            gaps.append("No Organization / LocalBusiness schema for geographic validation")
            region_ok = False
            locality_ok = False
            country_ok = False

        currencies = self._collect_price_currencies(schemas)
        service_product_present = any(t in SERVICE_PRODUCT_TYPES for t in schema_types)
        price_currency = ", ".join(currencies) if currencies else ""
        if service_product_present:
            price_ok = bool(currencies) and all(
                currency.upper() == REQUIRED_PRICE_CURRENCY for currency in currencies
            )
            if not currencies:
                gaps.append(
                    f"Service/Product schema missing priceCurrency (expected {REQUIRED_PRICE_CURRENCY})"
                )
            elif not price_ok:
                gaps.append(
                    f'priceCurrency is "{price_currency}" (expected {REQUIRED_PRICE_CURRENCY})'
                )
            price_applicable = True
        else:
            # Currency check only applies when Service/Product/Offer schemas exist
            price_ok = True
            price_applicable = False

        geo_ok = region_ok and locality_ok and country_ok
        compliant = geo_ok and price_ok and html_lang_en_za

        return {
            "address_region": region,
            "address_locality": locality,
            "address_country": country,
            "address_region_ok": region_ok,
            "address_locality_ok": locality_ok,
            "address_country_ok": country_ok,
            "price_currency": price_currency,
            "price_currency_ok": price_ok,
            "price_currency_applicable": price_applicable,
            "html_lang": html_lang,
            "html_lang_en_za": html_lang_en_za,
            "gaps": gaps,
            "compliant": compliant,
        }

    def _collect_address_fields(self, schemas: list[Any]) -> dict[str, str]:
        """Extract PostalAddress fields from Organization / LocalBusiness graphs."""
        region = ""
        locality = ""
        country = ""

        def as_types(node: dict[str, Any]) -> set[str]:
            type_val = node.get("@type")
            if isinstance(type_val, str):
                return {type_val.rsplit("/", 1)[-1]}
            if isinstance(type_val, list):
                return {str(item).rsplit("/", 1)[-1] for item in type_val}
            return set()

        def read_country(value: Any) -> str:
            if isinstance(value, str):
                return value.strip()
            if isinstance(value, dict):
                return str(value.get("name") or value.get("@id") or "").strip()
            return ""

        def ingest_address(address: Any) -> None:
            nonlocal region, locality, country
            if isinstance(address, list):
                for item in address:
                    ingest_address(item)
                return
            if not isinstance(address, dict):
                return
            if not region and address.get("addressRegion"):
                region = str(address["addressRegion"]).strip()
            if not locality and address.get("addressLocality"):
                locality = str(address["addressLocality"]).strip()
            if not country and address.get("addressCountry") is not None:
                country = read_country(address.get("addressCountry"))

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                types = as_types(node)
                if types & ORG_SCHEMA_TYPES or "PostalAddress" in types:
                    if "address" in node:
                        ingest_address(node.get("address"))
                    ingest_address(node)
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        for block in schemas:
            walk(block)

        return {
            "addressRegion": region,
            "addressLocality": locality,
            "addressCountry": country,
        }

    def _collect_price_currencies(self, schemas: list[Any]) -> list[str]:
        currencies: list[str] = []

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                type_val = node.get("@type")
                types: set[str] = set()
                if isinstance(type_val, str):
                    types.add(type_val.rsplit("/", 1)[-1])
                elif isinstance(type_val, list):
                    types.update(str(item).rsplit("/", 1)[-1] for item in type_val)

                if types & SERVICE_PRODUCT_TYPES or "priceCurrency" in node or "offers" in node:
                    currency = node.get("priceCurrency")
                    if isinstance(currency, str) and currency.strip():
                        currencies.append(currency.strip())
                    offers = node.get("offers")
                    if isinstance(offers, dict):
                        walk(offers)
                    elif isinstance(offers, list):
                        for offer in offers:
                            walk(offer)
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        for block in schemas:
            walk(block)

        seen: set[str] = set()
        ordered: list[str] = []
        for currency in currencies:
            key = currency.upper()
            if key not in seen:
                seen.add(key)
                ordered.append(currency)
        return ordered

    def _collect_same_as(self, schemas: list[Any]) -> list[str]:
        profiles: list[str] = []

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                same = node.get("sameAs")
                if isinstance(same, str):
                    profiles.append(same)
                elif isinstance(same, list):
                    profiles.extend(str(item) for item in same if item)
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        for block in schemas:
            walk(block)

        seen: set[str] = set()
        ordered: list[str] = []
        for profile in profiles:
            if profile not in seen:
                seen.add(profile)
                ordered.append(profile)
        return ordered

    def _nap_signals(
        self,
        soup: BeautifulSoup,
        schemas: list[Any],
        text: str,
    ) -> tuple[bool, bool, bool]:
        lowered = text.lower()
        name_found = any(hint in lowered for hint in NAP_NAME_HINTS)
        address_found = False
        phone_found = bool(PHONE_PATTERN.search(text))

        def walk(node: Any) -> None:
            nonlocal name_found, address_found, phone_found
            if isinstance(node, dict):
                type_val = node.get("@type")
                types = {type_val} if isinstance(type_val, str) else set(type_val or [])
                types = {str(item).rsplit("/", 1)[-1] for item in types}
                if "PostalAddress" in types or node.get("streetAddress") or node.get("addressLocality"):
                    address_found = True
                if node.get("telephone") or node.get("phone"):
                    phone_found = True
                if node.get("name") and any(
                    hint in str(node.get("name")).lower() for hint in NAP_NAME_HINTS
                ):
                    name_found = True
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        for block in schemas:
            walk(block)

        address_tag = soup.find("address")
        if address_tag:
            address_found = True
        locality_hints = ("pretoria", "gauteng", "south africa", "za")
        if any(hint in lowered for hint in locality_hints) and (
            "street" in lowered
            or "suite" in lowered
            or "office" in lowered
            or "address" in lowered
            or address_tag
        ):
            address_found = True
        elif any(hint in lowered for hint in ("pretoria", "centurion", "midrand")):
            address_found = True

        for anchor in soup.find_all("a", href=True):
            href = str(anchor["href"]).lower()
            if href.startswith("tel:"):
                phone_found = True

        return name_found, address_found, phone_found

    @staticmethod
    def _has_summary_block(soup: BeautifulSoup) -> bool:
        """Detect standalone lead / summary blocks suitable for AI overviews."""
        candidates: list[Tag] = []
        for selector in (
            {"name": "p", "attrs": {"class": re.compile(r"(lead|summary|intro|excerpt|dek)", re.I)}},
            {
                "name": "div",
                "attrs": {"class": re.compile(r"(lead|summary|intro|hero-text|excerpt)", re.I)},
            },
            {"name": True, "attrs": {"data-answer": True}},
            {"name": True, "attrs": {"itemprop": re.compile(r"(description|abstract)", re.I)}},
        ):
            candidates.extend(soup.find_all(**selector))

        root = soup.find("main") or soup.find("article") or soup.body
        if root:
            for paragraph in root.find_all("p", limit=5):
                text = paragraph.get_text(" ", strip=True)
                if 80 <= len(text) <= 320:
                    candidates.append(paragraph)
                    break

        for tag in candidates:
            text = tag.get_text(" ", strip=True)
            if 40 <= len(text) <= 400:
                return True
        return False

    @staticmethod
    def _geo_score(result: GeoAeoAuditResult) -> float:
        checks = [
            result.schema_valid,
            result.has_organization,
            result.has_website,
            result.has_breadcrumb,
            result.semantic_coverage_ok,
            result.nap_name_found,
            result.nap_address_found,
            result.nap_phone_found,
            result.has_same_as,
            result.entity_mapping_ok,
            result.local_seo_compliance,
            result.address_region_ok,
            result.address_locality_ok,
            result.address_country_ok,
            result.html_lang_en_za,
        ]
        return round(100.0 * sum(1 for check in checks if check) / len(checks), 1)

    @staticmethod
    def _aeo_score(result: GeoAeoAuditResult) -> float:
        checks = [
            result.has_definition_pattern,
            result.has_key_value_pairs,
            result.has_structured_lists,
            result.has_summary_block,
            result.direct_answer_ready,
            result.semantic_coverage_ok,
            result.schema_valid,
            result.has_service or result.has_organization,
        ]
        return round(100.0 * sum(1 for check in checks if check) / len(checks), 1)

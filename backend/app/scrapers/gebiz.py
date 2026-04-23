from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import AsyncIterator
from urllib.parse import urlparse, parse_qs

from .base import BaseScraper, ScrapedOpportunity
from ..config import settings
from ..models.opportunity import OpportunityStatus, OpportunityType

log = logging.getLogger(__name__)


# GeBIZ uses JSF/PrimeFaces. Each listing row is a div.formColumns_COLUMN-TABLE
# containing an <a href="/ptn/opportunity/directlink.xhtml?docCode=..."> and a
# set of label/value pairs rendered via .form2_ROW-LABEL + .formOutputText_VALUE-DIV.
#
# The "Today's Opportunities" listing only exposes: title, Agency, Published,
# Procurement Category. Closing Date / Status live on the detail page. For a
# daily/4-hourly scrape this is fine: newly listed items are all effectively
# Open. Status transitions are captured by re-visiting detail pages during a
# later enrichment pass (see enrich_detail() — called for items we've seen
# before to detect Closed/Awarded transitions).


class GeBIZScraper(BaseScraper):
    LISTING_URL = (
        "https://www.gebiz.gov.sg/ptn/opportunity/BOListing.xhtml?origin=opportunities"
    )
    DETAIL_URL_TMPL = (
        "https://www.gebiz.gov.sg/ptn/opportunity/directlink.xhtml?docCode={doc}"
    )
    ROW_SELECTOR = "div.formColumns_COLUMN-TABLE"
    TITLE_ANCHOR = "a.commandLink_TITLE-BLUE[href*='directlink']"

    def __init__(self, headless: bool = True, enrich_details: bool = False, enrich_limit: int = 20):
        self.headless = headless
        # Enriching every item visits N detail pages; disabled by default for v1.
        self.enrich_details = enrich_details
        self.enrich_limit = enrich_limit

    async def fetch(self) -> AsyncIterator[ScrapedOpportunity]:
        from playwright.async_api import async_playwright

        log.info("scrape: opening %s", self.LISTING_URL)
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=self.headless)
            ctx = await browser.new_context(
                locale="en-SG",
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
                ),
            )
            page = await ctx.new_page()
            await page.goto(self.LISTING_URL, wait_until="networkidle", timeout=45000)
            await page.wait_for_selector(self.TITLE_ANCHOR, timeout=15000)

            raw_rows = await page.eval_on_selector_all(
                self.ROW_SELECTOR,
                """
                rows => rows
                  .filter(r => r.querySelector("a[href*='directlink']"))
                  .map(r => {
                    const a = r.querySelector("a[href*='directlink']");
                    const labels = [...r.querySelectorAll('.form2_ROW-LABEL label span')].map(e => (e.innerText||'').trim());
                    const values = [...r.querySelectorAll('.formOutputText_VALUE-DIV')].map(e => (e.innerText||'').trim());
                    const pairs = {};
                    for (let i = 0; i < Math.min(labels.length, values.length); i++) pairs[labels[i]] = values[i];
                    return {
                      href: a.getAttribute('href'),
                      title: (a.innerText||'').trim(),
                      pairs,
                    };
                  })
                """,
            )

            items: list[ScrapedOpportunity] = []
            for r in raw_rows:
                item = self._parse_row(r)
                if item:
                    items.append(item)

            log.info("scrape: listing parsed %d items", len(items))

            if self.enrich_details:
                for item in items[: self.enrich_limit]:
                    try:
                        await self._enrich_detail(ctx, item)
                    except Exception:
                        log.exception("enrich failed for %s", item.document_no)

            await browser.close()

            for item in items:
                yield item

    def _parse_row(self, r: dict) -> ScrapedOpportunity | None:
        href: str = r.get("href") or ""
        doc_no = _extract_doc_code(href)
        if not doc_no:
            return None

        pairs: dict[str, str] = r.get("pairs") or {}
        published_at = _parse_dt(pairs.get("Published", ""))

        return ScrapedOpportunity(
            document_no=doc_no,
            description=r.get("title", ""),
            agency=pairs.get("Agency") or None,
            opportunity_type=_guess_type_from_doccode(doc_no),
            published_date=published_at.date() if published_at else None,
            closing_at=None,          # not on listing; filled by enrich_detail when enabled
            status=OpportunityStatus.Open,  # newly listed => Open; changes captured by detail enrich
            procurement_category=pairs.get("Procurement Category") or None,
            contact_person=None,
            award_details=None,
            source_url=f"https://www.gebiz.gov.sg{href}" if href.startswith("/") else href,
        )

    async def _enrich_detail(self, ctx, item: ScrapedOpportunity) -> None:
        """Open detail page and pull closing date / additional status signals."""
        page = await ctx.new_page()
        try:
            await page.goto(self.DETAIL_URL_TMPL.format(doc=item.document_no), wait_until="networkidle", timeout=45000)
            data = await page.evaluate(
                """() => {
                  const labs = [...document.querySelectorAll('.form2_ROW-LABEL label span')].map(e => (e.innerText||'').trim());
                  const vals = [...document.querySelectorAll('.formOutputText_VALUE-DIV')].map(e => (e.innerText||'').trim());
                  const m = {};
                  for (let i=0; i<Math.min(labs.length, vals.length); i++) m[labs[i]] = vals[i];
                  return m;
                }"""
            )
            # Labels vary by opportunity type; match a few common ones loosely.
            for key in ("Closing Date", "Closing Date & Time", "Closing Date and Time"):
                if data.get(key):
                    item.closing_at = _parse_dt(data[key])
                    break
            for key in ("Status", "Tender Status", "Quotation Status"):
                if data.get(key):
                    item.status = _map_status(data[key]) or item.status
                    break
            contact = data.get("Contact Person") or data.get("Enquiry")
            if contact:
                item.contact_person = contact
        finally:
            await page.close()


# ----- helpers ---------------------------------------------------------------


def _extract_doc_code(href: str) -> str | None:
    try:
        q = parse_qs(urlparse(href).query)
        code = (q.get("docCode") or [None])[0]
        return code or None
    except Exception:
        return None


def _guess_type_from_doccode(doc: str) -> OpportunityType | None:
    """
    docCode embeds the procurement kind as a substring before the digits.
    Examples observed:
      MOE000ETQ26000097       -> ETQ -> Quotation
      MOESCHETQ26001694       -> ETQ -> Quotation
      MPA000ETT26000009       -> ETT -> Tender
      DEFNGPP7126100141       -> no known kind -> None
    The token appears immediately before a run of digits, so we split on the
    first digit and scan the upper-case tail for a known marker.
    """
    if not doc:
        return None
    up = doc.upper()
    # Search the kind marker anywhere in the docCode. Longest first so "ETT"
    # and "ETQ" don't collide with a bare "ET" and so "EQUAL" beats a partial.
    for token, opp in (
        ("EQUAL", OpportunityType.Qualification),
        ("EAUC", OpportunityType.Auction),
        ("RFI", OpportunityType.RequestForInformation),
        ("ETT", OpportunityType.Tender),
        ("ETQ", OpportunityType.Quotation),
    ):
        if token in up:
            return opp
    return None


def _map_status(text: str) -> OpportunityStatus | None:
    t = (text or "").strip().lower()
    mapping = {
        "open": OpportunityStatus.Open,
        "closed": OpportunityStatus.Closed,
        "pending award": OpportunityStatus.PendingAward,
        "awarded": OpportunityStatus.Awarded,
        "cancelled": OpportunityStatus.Cancelled,
        "canceled": OpportunityStatus.Cancelled,
        "no award": OpportunityStatus.NoAward,
    }
    return mapping.get(t)


# GeBIZ formats seen: "22 Apr 2026 06:35 PM" and "22 Apr 2026 06:35PM"
_DT_FORMATS = (
    "%d %b %Y %I:%M %p",
    "%d %b %Y %I:%M%p",
    "%d/%m/%Y %H:%M",
    "%Y-%m-%d %H:%M",
)


def _parse_dt(text: str) -> datetime | None:
    s = (text or "").strip()
    if not s:
        return None
    # normalise "06:35PM" -> "06:35 PM" so a single format covers both.
    s_norm = re.sub(r"(\d)(AM|PM)$", r"\1 \2", s, flags=re.I)
    for fmt in _DT_FORMATS:
        try:
            return datetime.strptime(s_norm, fmt)
        except ValueError:
            continue
    log.warning("unparseable datetime: %r", text)
    return None

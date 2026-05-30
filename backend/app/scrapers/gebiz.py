from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import AsyncIterator, Optional
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
    ROW_SELECTOR = "div.row.formColumns_ROW-TABLE"
    TITLE_ANCHOR = "a.commandLink_TITLE-BLUE[href*='directlink']"

    def __init__(self, headless: bool = True, enrich_details: bool = False, enrich_limit: int = 20):
        self.headless = headless
        # Enriching every item visits N detail pages; disabled by default for v1.
        self.enrich_details = enrich_details
        self.enrich_limit = enrich_limit

    async def _parse_visible_rows(self, page) -> list[dict]:
        return await page.eval_on_selector_all(
            self.ROW_SELECTOR,
            """
            rows => rows
              .filter(r => r.querySelector("a[href*='directlink']"))
              .map(r => {
                const a = r.querySelector("a[href*='directlink']");
                const labels = [...r.querySelectorAll('.col-md-7 .form2_ROW-LABEL label span')].map(e => (e.innerText||'').trim());
                const values = [...r.querySelectorAll('.col-md-7 .formOutputText_VALUE-DIV')].map(e => (e.innerText||'').trim());
                const pairs = {};
                for (let i = 0; i < Math.min(labels.length, values.length); i++) pairs[labels[i]] = values[i];
                
                // Robustly parse Closing on / Closed datetime from right column
                const rightCol = r.querySelector('.outputText_LABEL-GRAY')?.closest('.formColumns_COLUMN-TABLE');
                if (rightCol) {
                    const rightText = (rightCol.innerText || '').trim();
                    const lines = rightText.split('\\n').map(l => l.trim()).filter(Boolean);
                    if (lines.length >= 3) {
                        // lines[0] is "Closing on" or "Closed"
                        // lines[1] is e.g. "05 Jun 2026"
                        // lines[2] is e.g. "01:00PM"
                        pairs[lines[0]] = lines[1] + " " + lines[2];
                    }
                }
                
                return {
                  href: a.getAttribute('href'),
                  title: (a.innerText||'').trim(),
                  pairs,
                };
              })
            """,
        )

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
            
            # Click the search "Go" button without keywords to display the Open/Closed tabs list
            log.info("scrape: clicking Go button to fetch all opportunities search page")
            try:
                go_button = page.get_by_role("button", name="Go")
                await go_button.wait_for(state="visible", timeout=10000)
                await go_button.click()
                await page.wait_for_timeout(3000) # Wait for page search results to update
            except Exception as e:
                log.error("Could not click Go button to load search results: %s", e)

            await page.wait_for_selector(self.TITLE_ANCHOR, timeout=15000)

            items: list[ScrapedOpportunity] = []

            # 1. Scrape Open tab (default active tab)
            try:
                log.info("scrape: parsing Open tab")
                raw_rows = await self._parse_visible_rows(page)
                for r in raw_rows:
                    item = self._parse_row(r)
                    if item:
                        item.status = OpportunityStatus.Open
                        items.append(item)
                log.info("scrape: Open tab parsed %d items", len(raw_rows))
            except Exception as e:
                log.exception("Failed to scrape Open tab")

            # 2. Click Closed main tab
            try:
                log.info("scrape: selecting Closed main tab")
                closed_main_tab = page.get_by_text(re.compile(r"Closed \(")).first
                await closed_main_tab.click()
                await page.wait_for_timeout(2000)
            except Exception as e:
                log.error("Could not click Closed main tab: %s", e)
                closed_main_tab = None

            # 3. Scrape Closed sub-tabs
            if closed_main_tab:
                sub_tabs = [
                    ("Closed sub-tab", re.compile(r"Closed \("), 1, OpportunityStatus.Closed), # 2nd occurrence => nth(1)
                    ("Pending Award", re.compile(r"Pending Award \("), 0, OpportunityStatus.PendingAward),
                    ("Awarded", re.compile(r"Awarded \("), 0, OpportunityStatus.Awarded),
                    ("Cancelled", re.compile(r"Cancelled \("), 0, OpportunityStatus.Cancelled),
                    ("No Award", re.compile(r"No Award \("), 0, OpportunityStatus.NoAward),
                ]

                for name, pattern, nth, status in sub_tabs:
                    try:
                        log.info("scrape: selecting sub-tab %s (expect status: %s)", name, status.value)
                        tab_el = page.get_by_text(pattern).nth(nth)
                        await tab_el.wait_for(state="visible", timeout=5000)
                        await tab_el.click()
                        await page.wait_for_timeout(2000)

                        try:
                            await page.wait_for_selector(self.TITLE_ANCHOR, timeout=5000)
                        except Exception:
                            log.info("No items or title anchors found in sub-tab %s", name)
                            continue

                        raw_rows = await self._parse_visible_rows(page)
                        log.info("scrape: sub-tab %s parsed %d items", name, len(raw_rows))
                        for r in raw_rows:
                            item = self._parse_row(r)
                            if item:
                                item.status = status
                                items.append(item)
                    except Exception as e:
                        log.exception("Failed to scrape sub-tab %s", name)

            log.info("scrape: total listing parsed %d items across all tabs", len(items))

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

        closing_dt = _parse_dt(pairs.get("Closing on", "")) or _parse_dt(pairs.get("Closed", "")) or _parse_dt(pairs.get("Closing Date", "")) or None

        return ScrapedOpportunity(
            document_no=doc_no,
            description=r.get("title", ""),
            agency=pairs.get("Agency") or None,
            opportunity_type=_guess_type_from_doccode(doc_no),
            published_date=published_at.date() if published_at else None,
            closing_at=closing_dt,
            status=OpportunityStatus.Open,  # newly listed => Open; changes captured by detail enrich
            procurement_category=pairs.get("Procurement Category") or None,
            contact_person=None,
            award_details=None,
            source_url=f"https://www.gebiz.gov.sg{href}" if href.startswith("/") else href,
        )

    async def enrich_opportunity(self, doc_no: str) -> Optional[ScrapedOpportunity]:
        from playwright.async_api import async_playwright

        log.info("enrich_opportunity: opening detail page for %s", doc_no)
        item = ScrapedOpportunity(
            document_no=doc_no,
            status=OpportunityStatus.Open
        )

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=self.headless)
            ctx = await browser.new_context(
                locale="en-SG",
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
                ),
            )
            try:
                await self._enrich_detail_with_retry(ctx, item)
            except Exception:
                log.exception("enrich_opportunity failed for %s", doc_no)
                return None
            finally:
                await browser.close()

        return item

    async def _enrich_detail(self, ctx, item: ScrapedOpportunity) -> None:
        await self._enrich_detail_with_retry(ctx, item)

    async def _enrich_detail_with_retry(self, ctx, item: ScrapedOpportunity) -> None:
        """Open detail page and pull closing date / additional status signals, retrying if necessary."""
        page = await ctx.new_page()
        max_retries = 3
        url = self.DETAIL_URL_TMPL.format(doc=item.document_no)
        
        for attempt in range(max_retries):
            try:
                await page.goto(url, wait_until="networkidle", timeout=30000)
                # Wait for main content form to verify it loaded successfully
                await page.wait_for_selector(".form2_ROW-LABEL label span", timeout=10000)
                break
            except Exception as e:
                log.warning("Attempt %d to load detail page failed: %s", attempt + 1, e)
                if attempt == max_retries - 1:
                    await page.close()
                    raise e
                await page.wait_for_timeout(2000)

        try:
            # 1. Parse official key-value pairs
            data = await page.evaluate(
                """() => {
                  const labs = [...document.querySelectorAll('.form2_ROW-LABEL label span')].map(e => (e.innerText||'').trim());
                  const vals = [...document.querySelectorAll('.formOutputText_VALUE-DIV')].map(e => (e.innerText||'').trim());
                  const m = {};
                  for (let i=0; i<Math.min(labs.length, vals.length); i++) m[labs[i]] = vals[i];
                  
                  // Parse Closed / Closing on datetime from floated right column on details page
                  const rightCol = document.querySelector('.outputText_LABEL-GRAY')?.closest('.formColumns_COLUMN-TABLE');
                  if (rightCol) {
                      const rightText = (rightCol.innerText || '').trim();
                      const lines = rightText.split('\\n').map(l => l.trim()).filter(Boolean);
                      if (lines.length >= 3) {
                          m[lines[0]] = lines[1] + " " + lines[2];
                      }
                  }
                  return m;
                }"""
            )
            
            # 2. Extract Reference No.
            for key in ("Tender Ref. No.", "Quotation Ref. No.", "Reference No.", "Ref No.", "Ref. No."):
                if data.get(key):
                    item.reference_no = data[key]
                    break

            # 3. Extract Closing date and time
            for key in ("Closing Date", "Closing Date & Time", "Closing Date and Time", "Closing on", "Closed"):
                if data.get(key):
                    item.closing_at = _parse_dt(data[key]) or item.closing_at
                    break

            # 4. Extract Status
            for key in ("Status", "Tender Status", "Quotation Status"):
                if data.get(key):
                    item.status = _map_status(data[key]) or item.status
                    break

            contact = data.get("Contact Person") or data.get("Enquiry")
            if contact:
                item.contact_person = contact

            # 5. Parse respondents list and bids if not Open
            if item.status != OpportunityStatus.Open:
                respondents_data = []
                award_details = None

                # Look for a tab element matching 'Respondents ('
                respondents_tab = page.get_by_text(re.compile(r"Respondents \("))
                if await respondents_tab.count() > 0:
                    log.info("Detail enrich: clicking Respondents tab")
                    try:
                        await respondents_tab.first.click()
                        await page.wait_for_timeout(2000) # Wait for AJAX load
                        
                        respondents_data = await page.evaluate(
                            """() => {
                              const list = [];
                              const tables = [...document.querySelectorAll('table')];
                              for (const table of tables) {
                                  const headers = [...table.querySelectorAll('th')].map(h => (h.innerText||'').trim().toLowerCase());
                                  const nameIdx = headers.findIndex(h => h.includes('supplier') || h.includes('name of') || h.includes('respondent') || h.includes('tenderer') || h.includes('company'));
                                  const priceIdx = headers.findIndex(h => h.includes('amount') || h.includes('price') || h.includes('offer') || h.includes('evaluated') || h.includes('value'));
                                  
                                  if (nameIdx !== -1) {
                                      const rows = [...table.querySelectorAll('tbody tr')];
                                      for (const row of rows) {
                                          const cells = [...row.querySelectorAll('td')].map(c => (c.innerText||'').trim());
                                          if (cells.length > nameIdx && cells[nameIdx]) {
                                              const supplierName = cells[nameIdx];
                                              let amount = null;
                                              if (priceIdx !== -1 && cells.length > priceIdx) {
                                                  const cleanPrice = cells[priceIdx].replace(/[^0-9.]/g, '');
                                                  if (cleanPrice) amount = parseFloat(cleanPrice);
                                              }
                                              list.push({
                                                  supplier_name: supplierName,
                                                  amount: amount,
                                                  is_awarded: false
                                              });
                                          }
                                      }
                                  }
                              }
                              return list;
                            }"""
                        )
                        log.info("Detail enrich: parsed %d respondents", len(respondents_data))
                    except Exception as e:
                        log.warning("Failed to click or parse Respondents tab: %s", e)

                # Look for a tab element matching 'Award ('
                award_tab = page.get_by_text(re.compile(r"Award \("))
                if await award_tab.count() > 0:
                    log.info("Detail enrich: clicking Award tab")
                    try:
                        await award_tab.first.click()
                        await page.wait_for_timeout(2000) # Wait for AJAX load
                        
                        award_details = await page.evaluate(
                            """() => {
                              let supplier = null;
                              let amount = null;
                              let date = null;

                              // 1. Try to find the "Awarded to" label and extract the supplier name next to/below it
                              const allElems = [...document.querySelectorAll('*')];
                              for (const el of allElems) {
                                  const txt = (el.innerText || '').trim();
                                  if (txt === 'Awarded to') {
                                      const parent = el.parentElement;
                                      if (parent) {
                                          const lines = parent.innerText.split('\\n').map(l => l.trim()).filter(Boolean);
                                          const idx = lines.findIndex(l => l === 'Awarded to');
                                          if (idx !== -1 && lines.length > idx + 1) {
                                              supplier = lines[idx + 1];
                                              if (lines.length > idx + 2 && lines[idx + 2].toLowerCase().includes('value')) {
                                                  const valLine = lines[idx + 2];
                                                  const cleanVal = valLine.replace(/[^0-9.]/g, '');
                                                  if (cleanVal) amount = parseFloat(cleanVal);
                                              }
                                          }
                                      }
                                      break;
                                  }
                              }

                              // 2. Fallback: Check standard key-value inputs/labels
                              if (!supplier) {
                                  const labs = [...document.querySelectorAll('.form2_ROW-LABEL label span')].map(e => (e.innerText||'').trim().toLowerCase());
                                  const vals = [...document.querySelectorAll('.formOutputText_VALUE-DIV')].map(e => (e.innerText||'').trim());
                                  for (let i = 0; i < Math.min(labs.length, vals.length); i++) {
                                      const l = labs[i];
                                      const v = vals[i];
                                      if (l.includes('awarded supplier') || l.includes('awardee') || l.includes('awarded to')) {
                                          supplier = v;
                                      }
                                      if (l.includes('award amount') || l.includes('awarded amount') || l.includes('award value') || l.includes('total awarded value')) {
                                          const cleanVal = v.replace(/[^0-9.]/g, '');
                                          if (cleanVal) amount = parseFloat(cleanVal);
                                      }
                                      if (l.includes('awarded date')) {
                                          date = v;
                                      }
                                  }
                              }

                              // 3. Fallback: Parse from any tables inside the Award tab
                              if (!supplier) {
                                  const tables = [...document.querySelectorAll('table')];
                                  for (const table of tables) {
                                      const headers = [...table.querySelectorAll('th')].map(h => (h.innerText||'').trim().toLowerCase());
                                      const nameIdx = headers.findIndex(h => h.includes('supplier') || h.includes('name of') || h.includes('awardee') || h.includes('awarded to'));
                                      const priceIdx = headers.findIndex(h => h.includes('amount') || h.includes('price') || h.includes('value'));
                                      if (nameIdx !== -1) {
                                          const rows = [...table.querySelectorAll('tbody tr')];
                                          if (rows.length > 0) {
                                              const cells = [...rows[0].querySelectorAll('td')].map(c => (c.innerText||'').trim());
                                              if (cells.length > nameIdx) {
                                                  supplier = cells[nameIdx];
                                                  if (priceIdx !== -1 && cells.length > priceIdx) {
                                                      const cleanVal = cells[priceIdx].replace(/[^0-9.]/g, '');
                                                      if (cleanVal) amount = parseFloat(cleanVal);
                                                  }
                                              }
                                          }
                                      }
                                  }
                              }

                              // 4. Try to parse Awarded Date if not found
                              if (!date) {
                                  const dateEl = [...document.querySelectorAll('*')].find(el => (el.innerText || '').trim().includes('Awarded Date'));
                                  if (dateEl && dateEl.parentElement) {
                                      const lines = dateEl.parentElement.innerText.split('\\n').map(l => l.trim()).filter(Boolean);
                                      const idx = lines.findIndex(l => l.includes('Awarded Date'));
                                      if (idx !== -1 && lines.length > idx + 1) {
                                          date = lines[idx + 1];
                                      }
                                  }
                              }

                              return { supplier_name: supplier, amount: amount, awarded_date: date };
                            }"""
                        )
                        log.info("Detail enrich: parsed award details %s", award_details)
                    except Exception as e:
                        log.warning("Failed to click or parse Award tab: %s", e)

                # Cross-reference award details and respondents
                if award_details and award_details.get("supplier_name"):
                    awarded_supplier = award_details["supplier_name"]
                    award_amount = award_details.get("amount")
                    
                    item.award_details = {
                        "supplier_name": awarded_supplier,
                        "amount": award_amount,
                        "awarded_date": award_details.get("awarded_date") or datetime.now().date().isoformat()
                    }
                    
                    # Mark awarded in respondents list
                    matched = False
                    for resp in respondents_data:
                        if resp["supplier_name"].lower() == awarded_supplier.lower():
                            resp["is_awarded"] = True
                            matched = True
                            if award_amount and not resp.get("amount"):
                                resp["amount"] = award_amount
                    
                    # If the awarded supplier is somehow not in the respondents list, add them!
                    if not matched:
                        respondents_data.append({
                            "supplier_name": awarded_supplier,
                            "amount": award_amount,
                            "is_awarded": True
                        })
                elif award_details and (award_details.get("amount") or award_details.get("awarded_date")):
                    item.award_details = {
                        "supplier_name": None,
                        "amount": award_details.get("amount"),
                        "awarded_date": award_details.get("awarded_date")
                    }

                item.respondents = respondents_data
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

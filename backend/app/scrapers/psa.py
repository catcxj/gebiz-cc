from __future__ import annotations

import logging
import re
from datetime import datetime, date
from typing import AsyncIterator, Optional

from .base import BaseScraper, ScrapedOpportunity
from ..models.opportunity import OpportunityStatus, OpportunityType
from ..database import SessionLocal
from ..models import Opportunity

log = logging.getLogger(__name__)


class PSAScraper(BaseScraper):
    LISTING_URL = "https://www.singaporepsa.com/resources/tender-notices/"

    def __init__(self, headless: bool = True):
        self.headless = headless

    async def fetch(self) -> AsyncIterator[ScrapedOpportunity]:
        from playwright.async_api import async_playwright

        log.info("scrape: opening PSA listing %s", self.LISTING_URL)
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

            # Extract rows from table bodies
            rows = await page.eval_on_selector_all(
                "table tbody tr",
                """
                rows => rows.map(r => {
                    const tds = [...r.querySelectorAll('td')].map(td => (td.innerText || '').trim());
                    const a = r.querySelector('td a');
                    const container = r.closest('.container');
                    const dateHeader = container ? container.querySelector('.title-5') : null;
                    const dateText = dateHeader ? (dateHeader.innerText || '') : '';
                    return {
                        no: tds[0] || '',
                        type: tds[1] || '',
                        desc: tds[2] || '',
                        href: a ? a.getAttribute('href') : '',
                        dateText: dateText
                    };
                })
                """
            )

            await browser.close()

        log.info("scrape: found %d raw tenders on PSA listing", len(rows))

        for r in rows:
            tender_type = r.get("type", "")
            # Filter type=CONSTRUCTION
            if "CONSTRUCTION" in tender_type.upper():
                detail_url = r.get("href", "")
                if detail_url and not detail_url.startswith("http"):
                    detail_url = "https://www.singaporepsa.com" + detail_url

                # Extrapolate document_no from href slug as temporary key
                doc_no = detail_url.split("/")[-2] if "/" in detail_url else detail_url
                
                published_date_val = _parse_published_date(r.get("dateText"))

                yield ScrapedOpportunity(
                    document_no=doc_no,
                    description=r.get("desc", ""),
                    agency="PSA",
                    opportunity_type=OpportunityType.Tender,
                    published_date=published_date_val,
                    status=OpportunityStatus.Open,
                    procurement_category=tender_type,
                    source_url=detail_url
                )

    async def enrich_opportunity(self, doc_no: str) -> Optional[ScrapedOpportunity]:
        from playwright.async_api import async_playwright

        # Load opportunity from DB to retrieve source_url
        db = SessionLocal()
        try:
            opp = db.query(Opportunity).filter(Opportunity.document_no == doc_no).first()
            if not opp or not opp.source_url:
                log.error("enrich_opportunity: Cannot enrich PSA opportunity %s: source_url not found in DB", doc_no)
                return None
            detail_url = opp.source_url
            published_date_val = opp.published_date
            proc_cat = opp.procurement_category
        finally:
            db.close()

        log.info("enrich_opportunity: opening PSA detail page for %s (%s)", doc_no, detail_url)
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
            
            try:
                await page.goto(detail_url, wait_until="networkidle", timeout=30000)
                
                details = await page.evaluate(
                    """() => {
                        const docText = document.querySelector('.tempt-9-content.document')?.innerText || '';
                        const refMatch = docText.match(/REFERENCE NUMBER\\s*(?:-|–|—|\\s)\\s*([A-Za-z0-9/_-]+)/i);
                        const reference_no = refMatch ? refMatch[1] : '';
                        
                        const asideTable = document.querySelector('.tempt-9-aside table');
                        const asideData = {};
                        if (asideTable) {
                            const rows = asideTable.querySelectorAll('tr');
                            for (const r of rows) {
                                const tds = [...r.querySelectorAll('td')].map(td => (td.innerText || '').trim());
                                if (tds.length >= 2) {
                                    asideData[tds[0].toLowerCase()] = tds[1];
                                }
                            }
                        }
                        
                        const descHeader = [...document.querySelectorAll('h5')].find(h5 => h5.innerText.includes('Tender Description'));
                        let description = '';
                        if (descHeader && descHeader.nextElementSibling) {
                            description = descHeader.nextElementSibling.innerText.trim();
                        }
                        
                        return {
                            reference_no,
                            description,
                            asideData
                        };
                    }"""
                )
            except Exception as e:
                log.exception("enrich_opportunity: Failed to load/parse PSA detail page: %s", e)
                await browser.close()
                return None
            
            await browser.close()

        # Normalize keys and values
        norm_aside = {}
        for k, v in details.get("asideData", {}).items():
            norm_k = re.sub(r'\s+', ' ', k).strip()
            norm_aside[norm_k] = re.sub(r'\s+', ' ', v).strip()

        status_raw = norm_aside.get("status", "Open")
        closing_raw = norm_aside.get("closing date / time", "")
        contact_raw = norm_aside.get("tender contact information", "")

        # Extract doc/ref code
        ref_no = details.get("reference_no") or doc_no

        closing_dt = _parse_dt(closing_raw)

        return ScrapedOpportunity(
            document_no=ref_no,
            reference_no=ref_no,
            description=details.get("description") or opp.description,
            agency="PSA",
            opportunity_type=OpportunityType.Tender,
            published_date=published_date_val,
            closing_at=closing_dt,
            status=_map_status(status_raw),
            procurement_category=proc_cat,
            contact_person=contact_raw,
            source_url=detail_url
        )


# ----- Helpers -----

def _parse_published_date(text: str) -> Optional[date]:
    if not text:
        return None
    m = re.search(r'TENDER PUBLICATION DATE:\s*([\w\s]+)', text, re.I)
    if m:
        try:
            return datetime.strptime(m.group(1).strip(), "%d %B %Y").date()
        except ValueError:
            pass
    return None


_DT_FORMATS = (
    "%d %b %Y %I:%M %p",
    "%d %b %Y %I:%M%p",
    "%d/%m/%Y %H:%M",
    "%Y-%m-%d %H:%M",
)


def _parse_dt(text: str) -> Optional[datetime]:
    s = (text or "").strip()
    if not s:
        return None
    s_norm = re.sub(r"(\d)(AM|PM)$", r"\1 \2", s, flags=re.I)
    for fmt in _DT_FORMATS:
        try:
            return datetime.strptime(s_norm, fmt)
        except ValueError:
            continue
    log.warning("unparseable datetime: %r", text)
    return None


def _map_status(text: str) -> OpportunityStatus:
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
    return mapping.get(t, OpportunityStatus.Open)

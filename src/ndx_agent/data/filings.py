"""SEC EDGAR filings for constituents."""
from __future__ import annotations

import re

import httpx

from .. import config
from ..cache import throttle, ttl_cache
from ._util import safe


def _get(url: str) -> httpx.Response:
    throttle("edgar", 0.15)  # SEC fair-access limit is 10 req/s
    r = httpx.get(url, headers={"User-Agent": config.SEC_USER_AGENT}, timeout=40, follow_redirects=True)
    r.raise_for_status()
    return r


@ttl_cache(24 * 3600)
def _cik_map() -> dict:
    data = _get("https://www.sec.gov/files/company_tickers.json").json()
    return {v["ticker"].upper(): int(v["cik_str"]) for v in data.values()}


@ttl_cache(3600)
def _submissions(cik: int) -> dict:
    return _get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json").json()


@safe
def get_recent_filings(ticker: str, forms: str = "10-K,10-Q,8-K", limit: int = 8) -> dict:
    """Recent SEC filings (10-K, 10-Q, 8-K by default) with direct document URLs."""
    cik = _cik_map().get(ticker.upper())
    if cik is None:
        return {"error": f"no CIK found for {ticker}", "source_unavailable": True}
    wanted = {f.strip() for f in forms.split(",")}
    rec = _submissions(cik)["filings"]["recent"]
    out = []
    for i, form in enumerate(rec["form"]):
        if form in wanted:
            acc = rec["accessionNumber"][i]
            out.append({
                "form": form,
                "filed": rec["filingDate"][i],
                "description": rec["primaryDocDescription"][i],
                "items": rec.get("items", [""] * len(rec["form"]))[i],
                "url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{rec['primaryDocument'][i]}",
            })
            if len(out) >= limit:
                break
    return {"ticker": ticker.upper(), "cik": cik, "filings": out}


@safe
def get_filing_excerpt(url: str, max_chars: int = 4000, start_at: str = "") -> dict:
    """Plain-text excerpt of an SEC filing. Use `start_at` (e.g. 'Management' or 'Risk Factors') to jump to a section."""
    if not url.startswith("https://www.sec.gov/Archives/"):
        return {"error": "only sec.gov/Archives URLs are allowed"}
    html = _get(url).text
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"&#?\w+;", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    pos = 0
    if start_at:
        matches = [m.start() for m in re.finditer(re.escape(start_at), text, flags=re.I)]
        pos = matches[1] if len(matches) > 1 else (matches[0] if matches else 0)  # skip table-of-contents hit
    max_chars = min(max_chars, 8000)
    return {"url": url, "offset": pos, "total_chars": len(text), "excerpt": text[pos:pos + max_chars]}

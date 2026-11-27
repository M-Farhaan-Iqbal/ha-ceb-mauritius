"""Planned power outages, scraped from the CEB website.

The MoKouran API blocks outage endpoints, but the public page
https://ceb.mu/customer-corner/power-outage-information embeds a JavaScript
variable `arDistrictLocations = { "<district>": "<html table>", ... }`. Each
table has rows of: Date (French) | Locality | Streets. We fetch the raw HTML,
pull that object, and parse the rows. This is a scrape: it breaks if CEB changes
the page. Dates are French, e.g. "Le samedi 28 novembre 2026 de 08:30:00 a 12:00:00".
"""
from __future__ import annotations

import html
import json
import logging
import re
import unicodedata

try:
    from .const import OUTAGE_URL
except ImportError:  # running the self-check standalone
    OUTAGE_URL = "https://ceb.mu/customer-corner/power-outage-information"

_LOGGER = logging.getLogger(__name__)

_FR_MONTHS = {
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
    "juillet": 7, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11,
    "decembre": 12,
}
_VAR_RE = re.compile(r"arDistrictLocations\s*=\s*(\{.*?\})\s*;", re.S)
_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_CELL_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_DATE_RE = re.compile(
    r"(\d{1,2})\s+([A-Za-zéûà]+)\s+(\d{4}).*?(\d{1,2}:\d{2}).*?[àa]\s*(\d{1,2}:\d{2})"
)


def _deaccent(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn"
    )


def _text(cell: str) -> str:
    return re.sub(r"\s+", " ", _TAG_RE.sub("", html.unescape(cell))).strip()


def _parse_when(raw: str) -> tuple[str | None, str | None, str | None]:
    """('YYYY-MM-DD', 'HH:MM', 'HH:MM') from a French date string, any part None if unmatched."""
    m = _DATE_RE.search(raw)
    if not m:
        return None, None, None
    day, month_word, year, start, end = m.groups()
    month = _FR_MONTHS.get(_deaccent(month_word).lower())
    if not month:
        return None, start, end
    return f"{int(year):04d}-{month:02d}-{int(day):02d}", start, end


def parse(page_html: str) -> list[dict]:
    """All planned outages on the page: [{district,date,start,end,locality,streets,raw}]."""
    m = _VAR_RE.search(page_html)
    if not m:
        _LOGGER.warning("CEB outage page: arDistrictLocations not found (page changed?)")
        return []
    try:
        districts = json.loads(m.group(1))
    except ValueError:
        _LOGGER.warning("CEB outage page: arDistrictLocations is not valid JSON")
        return []
    out: list[dict] = []
    for district, table in districts.items():
        for tr in _ROW_RE.findall(table or ""):
            cells = [_text(c) for c in _CELL_RE.findall(tr)]
            if len(cells) < 3 or cells[0].lower() == "date" or not any(cells):
                continue
            date, start, end = _parse_when(cells[0])
            out.append(
                {
                    "district": district,
                    "date": date,
                    "start": start,
                    "end": end,
                    "locality": cells[1],
                    "streets": cells[2],
                    "raw": cells[0],
                }
            )
    return out


async def fetch_outages(session) -> list[dict]:
    """Fetch and parse the CEB planned-outage page."""
    import aiohttp

    async with session.get(OUTAGE_URL, timeout=aiohttp.ClientTimeout(total=30)) as r:
        r.raise_for_status()
        return parse(await r.text())


def filter_outages(
    rows: list[dict], district: str | None, locality: str | None
) -> list[dict]:
    """Keep rows for the district (if set) whose locality/streets contain the keyword (if set)."""
    res = rows
    if district:
        res = [r for r in res if r["district"] == district]
    if locality:
        key = _deaccent(locality).lower()
        res = [
            r
            for r in res
            if key in _deaccent(f"{r['locality']} {r['streets']}").lower()
        ]
    return res


def demo() -> None:
    sample = (
        'x; arDistrictLocations = {"rivieredurempart":"<table><tr><th>Date</th>'
        "<th>Locality</th><th>Streets</th></tr><tr><td>Le samedi 28 novembre 2026 "
        "de 08:30:00 &agrave; 12:00:00</td><td>GOODLANDS</td><td>Bank Road &amp; Royal Road</td>"
        '</tr></table>","moka":"<table></table>"}; var y'
    )
    rows = parse(sample)
    assert len(rows) == 1, rows
    r = rows[0]
    assert r["district"] == "rivieredurempart"
    assert r["date"] == "2026-11-28" and r["start"] == "08:30" and r["end"] == "12:00", r
    assert r["locality"] == "GOODLANDS" and "Royal Road" in r["streets"]
    assert len(filter_outages(rows, "moka", None)) == 0
    assert len(filter_outages(rows, "rivieredurempart", "goodlands")) == 1
    assert len(filter_outages(rows, "rivieredurempart", "pereybere")) == 0
    print("outages.demo OK:", r)


if __name__ == "__main__":
    demo()

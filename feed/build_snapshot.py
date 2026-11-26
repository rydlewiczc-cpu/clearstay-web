#!/usr/bin/env python3
"""Clearstay Live Briefings — Zero-Server Global Static Snapshot Builder ($0/mo).

Pure Python 3 standard-library script (zero pip dependencies) that aggregates public,
zero-user-tracking global feeds into ONE static `snapshot-v1.json` file:

  1. FX Rates: Open ER-API (`open.er-api.com/v6/latest/USD`) with ECB Daily XML fallback
  2. Security & Travel Advisories: US State Department RSS (`travel.state.gov`)
  3. Severe Weather & Maritime Disasters: UN/EU GDACS Global RSS (`gdacs.org`)
  4. Health & Outbreak Notices: WHO Disease Outbreak News API (`who.int`)
  5. Custom Emergency Broadcasts: `feed/emergency_bulletins.json`

Every Clearstay iPhone that explicitly opts in downloads this exact same static file
and filters it 100% locally on-device — zero GPS, country, or device ID ever leaves the phone.

Usage:
  python3 feed/build_snapshot.py --out feed/dist/snapshot-v1.json
  python3 feed/build_snapshot.py --test-offline --out /tmp/test-snapshot-v1.json
"""

from __future__ import annotations

import argparse
import email.utils
import gzip
import html
import json
import math
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
MAX_SNAPSHOT_BYTES = 2_000_000
HTTP_TIMEOUT_SECONDS = 20
USER_AGENT = "Clearstay-StaticFeedBuilder/1.0 (+https://clearstay.app)"

OPEN_ER_API_URL = "https://open.er-api.com/v6/latest/USD"
ECB_DAILY_XML_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
STATE_DEPT_RSS_URL = "https://travel.state.gov/_res/rss/TAsTWs.xml"
GDACS_RSS_URL = "https://www.gdacs.org/xml/rss.xml"
WHO_DON_URL = "https://www.who.int/api/news/diseaseoutbreaknews?$top=20&$orderby=PublicationDate%20desc"

# Common country name -> ISO 3166-1 alpha-3 normalization table for RSS/API feeds.
COUNTRY_NAME_TO_ISO3: dict[str, str] = {
    "afghanistan": "AFG", "albania": "ALB", "algeria": "DZA", "andorra": "AND",
    "angola": "AGO", "antigua and barbuda": "ATG", "argentina": "ARG", "armenia": "ARM",
    "australia": "AUS", "austria": "AUT", "azerbaijan": "AZE", "bahamas": "BHS",
    "the bahamas": "BHS", "bahrain": "BHR", "bangladesh": "BGD", "barbados": "BRB",
    "belarus": "BLR", "belgium": "BEL", "belize": "BLZ", "benin": "BEN",
    "bermuda": "BMU", "bhutan": "BTN", "bolivia": "BOL", "bosnia and herzegovina": "BIH",
    "botswana": "BWA", "brazil": "BRA", "british virgin islands": "VGB", "brunei": "BRN",
    "bulgaria": "BGR", "burkina faso": "BFA", "burma": "MMR", "myanmar": "MMR",
    "burundi": "BDI", "cabo verde": "CPV", "cape verde": "CPV", "cambodia": "KHM",
    "cameroon": "CMR", "canada": "CAN", "cayman islands": "CYM",
    "central african republic": "CAF", "chad": "TCD", "chile": "CHL", "china": "CHN",
    "colombia": "COL", "comoros": "COM", "democratic republic of the congo": "COD",
    "republic of the congo": "COG", "costa rica": "CRI", "cote d'ivoire": "CIV",
    "ivory coast": "CIV", "croatia": "HRV", "cuba": "CUB", "curacao": "CUW",
    "cyprus": "CYP", "czech republic": "CZE", "czechia": "CZE", "denmark": "DNK",
    "djibouti": "DJI", "dominica": "DMA", "dominican republic": "DOM", "ecuador": "ECU",
    "egypt": "EGY", "el salvador": "SLV", "equatorial guinea": "GNQ", "eritrea": "ERI",
    "estonia": "EST", "eswatini": "SWZ", "ethiopia": "ETH", "fiji": "FJI",
    "finland": "FIN", "france": "FRA", "french polynesia": "PYF", "gabon": "GAB",
    "gambia": "GMB", "the gambia": "GMB", "georgia": "GEO", "germany": "DEU",
    "ghana": "GHA", "gibraltar": "GIB", "greece": "GRC", "grenada": "GRD",
    "guatemala": "GTM", "guinea": "GIN", "guinea-bissau": "GNB", "guyana": "GUY",
    "haiti": "HTI", "honduras": "HND", "hong kong": "HKG", "hungary": "HUN",
    "iceland": "ISL", "india": "IND", "indonesia": "IDN", "iran": "IRN", "iraq": "IRQ",
    "ireland": "IRL", "israel": "ISR", "israel, the west bank and gaza": "ISR",
    "italy": "ITA", "jamaica": "JAM", "japan": "JPN", "jordan": "JOR",
    "kazakhstan": "KAZ", "kenya": "KEN", "kiribati": "KIR", "kosovo": "XKX",
    "kuwait": "KWT", "kyrgyzstan": "KGZ", "laos": "LAO", "latvia": "LVA",
    "lebanon": "LBN", "lesotho": "LSO", "liberia": "LBR", "libya": "LBY",
    "liechtenstein": "LIE", "lithuania": "LTU", "luxembourg": "LUX", "macau": "MAC",
    "madagascar": "MDG", "malawi": "MWI", "malaysia": "MYS", "maldives": "MDV",
    "mali": "MLI", "malta": "MLT", "marshall islands": "MHL", "mauritania": "MRT",
    "mauritius": "MUS", "mexico": "MEX", "micronesia": "FSM", "moldova": "MDA",
    "monaco": "MCO", "mongolia": "MNG", "montenegro": "MNE", "morocco": "MAR",
    "mozambique": "MOZ", "namibia": "NAM", "nepal": "NPL", "netherlands": "NLD",
    "new caledonia": "NCL", "new zealand": "NZL", "nicaragua": "NIC", "niger": "NER",
    "nigeria": "NGA", "north korea": "PRK", "north macedonia": "MKD", "norway": "NOR",
    "oman": "OMN", "pakistan": "PAK", "palau": "PLW", "panama": "PAN",
    "papua new guinea": "PNG", "paraguay": "PRY", "peru": "PER", "philippines": "PHL",
    "poland": "POL", "portugal": "PRT", "qatar": "QAT", "romania": "ROU",
    "russia": "RUS", "rwanda": "RWA", "saint kitts and nevis": "KNA",
    "saint lucia": "LCA", "saint vincent and the grenadines": "VCT", "samoa": "WSM",
    "san marino": "SMR", "saudi arabia": "SAU", "senegal": "SEN", "serbia": "SRB",
    "seychelles": "SYC", "sierra leone": "SLE", "singapore": "SGP", "slovakia": "SVK",
    "slovenia": "SVN", "solomon islands": "SLB", "somalia": "SOM", "south africa": "ZAF",
    "south korea": "KOR", "republic of korea": "KOR", "south sudan": "SSD",
    "spain": "ESP", "sri lanka": "LKA", "sudan": "SDN", "suriname": "SUR",
    "sweden": "SWE", "switzerland": "CHE", "syria": "SYR", "taiwan": "TWN",
    "tajikistan": "TJK", "tanzania": "TZA", "thailand": "THA", "timor-leste": "TLS",
    "togo": "TGO", "tonga": "TON", "trinidad and tobago": "TTO", "tunisia": "TUN",
    "turkey": "TUR", "turkiye": "TUR", "turkmenistan": "TKM",
    "turks and caicos islands": "TCA", "uganda": "UGA", "ukraine": "UKR",
    "united arab emirates": "ARE", "united kingdom": "GBR", "united states": "USA",
    "uruguay": "URY", "uzbekistan": "UZB", "vanuatu": "VUT", "venezuela": "VEN",
    "vietnam": "VNM", "viet nam": "VNM", "yemen": "YEM", "zambia": "ZMB",
    "zimbabwe": "ZWE",
}


def now_utc_millis() -> int:
    return int(time.time() * 1000)


def today_iso_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def sanitize_https_url(raw: str | None) -> str | None:
    if not raw or not isinstance(raw, str):
        return None
    trimmed = raw.strip()
    if not trimmed or len(trimmed) > 512:
        return None
    if not trimmed.lower().startswith("https://"):
        return None
    if any(ch.isspace() for ch in trimmed):
        return None
    return trimmed


def strip_html(raw: str | None, max_len: int = 420) -> str:
    if not raw:
        return ""
    cleaned = re.sub(r"<[^>]+>", " ", raw)
    cleaned = html.unescape(cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) > max_len:
        cleaned = cleaned[: max_len - 1].rstrip() + "…"
    return cleaned


def parse_rfc_or_iso_millis(raw: str | None, fallback: int) -> int:
    if not raw or not isinstance(raw, str):
        return fallback
    s = raw.strip()
    if not s:
        return fallback
    # Try ISO 8601 first
    try:
        iso = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except ValueError:
        pass
    # Try RFC 2822 (RSS pubDate)
    try:
        dt = email.utils.parsedate_to_datetime(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except (TypeError, ValueError):
        return fallback


def infer_country_isos(text: str) -> list[str]:
    lower = text.lower()
    found: list[str] = []
    seen: set[str] = set()
    # Match longest country names first so "South Sudan" doesn't collide with "Sudan"
    for name in sorted(COUNTRY_NAME_TO_ISO3.keys(), key=len, reverse=True):
        if len(name) < 4:
            continue
        if re.search(rf"(?<![a-z]){re.escape(name)}(?![a-z])", lower):
            iso = COUNTRY_NAME_TO_ISO3[name]
            if iso not in seen:
                seen.add(iso)
                found.append(iso)
                if len(found) >= 6:
                    break
    return found


def http_get_bytes(url: str) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json, application/xml, text/xml, */*",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
        data = resp.read(MAX_SNAPSHOT_BYTES + 1)
        if len(data) > MAX_SNAPSHOT_BYTES:
            raise ValueError(f"Response from {url} exceeded {MAX_SNAPSHOT_BYTES} bytes")
        return data


# MARK: - 1. FX Parsers

def parse_open_er_api(data: bytes) -> dict[str, Any] | None:
    obj = json.loads(data.decode("utf-8"))
    raw_rates = obj.get("rates")
    if not isinstance(raw_rates, dict):
        return None
    rates: dict[str, float] = {"USD": 1.0}
    for k, v in raw_rates.items():
        code = str(k).strip().upper()
        if len(code) != 3 or not code.isalpha():
            continue
        if isinstance(v, (int, float)) and math.isfinite(v) and 0 < float(v) < 1e9:
            rates[code] = round(float(v), 6)
    if len(rates) < 20:
        return None
    as_of = today_iso_utc()
    unix_ts = obj.get("time_last_update_unix")
    if isinstance(unix_ts, (int, float)) and unix_ts > 0:
        as_of = datetime.fromtimestamp(float(unix_ts), tz=timezone.utc).strftime("%Y-%m-%d")
    return {
        "baseCurrency": "USD",
        "sourceLabel": "Open Exchange Rates (Daily)",
        "asOfDateIso": as_of,
        "rates": dict(sorted(rates.items())),
    }


def parse_ecb_daily_xml(data: bytes) -> dict[str, Any] | None:
    root = ET.fromstring(data)
    as_of = today_iso_utc()
    eur_rates: dict[str, float] = {"EUR": 1.0}
    for elem in root.iter():
        tag = elem.tag.split("}")[-1]
        if tag != "Cube":
            continue
        if "time" in elem.attrib and re.fullmatch(r"\d{4}-\d{2}-\d{2}", elem.attrib["time"]):
            as_of = elem.attrib["time"]
        cur = elem.attrib.get("currency", "").strip().upper()
        rate_str = elem.attrib.get("rate", "").strip()
        if len(cur) == 3 and cur.isalpha() and rate_str:
            try:
                val = float(rate_str)
                if math.isfinite(val) and val > 0:
                    eur_rates[cur] = val
            except ValueError:
                pass
    usd_per_eur = eur_rates.get("USD")
    if not usd_per_eur or usd_per_eur <= 0:
        return None
    usd_rates = {code: round(val / usd_per_eur, 6) for code, val in eur_rates.items()}
    usd_rates["USD"] = 1.0
    return {
        "baseCurrency": "USD",
        "sourceLabel": "European Central Bank (ECB)",
        "asOfDateIso": as_of,
        "rates": dict(sorted(usd_rates.items())),
    }


# MARK: - 2. US State Department Travel Advisories RSS Parser

def parse_state_dept_advisories_rss(data: bytes, now_ms: int) -> dict[str, dict[str, Any]]:
    root = ET.fromstring(data)
    advisories: dict[str, dict[str, Any]] = {}
    for item in root.findall(".//item"):
        title = strip_html(item.findtext("title"), max_len=160)
        desc = strip_html(item.findtext("description"), max_len=360)
        link = sanitize_https_url(item.findtext("link"))
        pub_ms = parse_rfc_or_iso_millis(item.findtext("pubDate"), now_ms)
        if not title:
            continue
        # Typical title: "Spain - Level 2: Exercise Increased Caution"
        lvl_match = re.search(r"Level\s+([1-4])\s*:\s*(.+)$", title, re.IGNORECASE)
        if not lvl_match:
            continue
        risk_level = int(lvl_match.group(1))
        risk_label = lvl_match.group(2).strip()
        country_part = title[: lvl_match.start()].strip(" -–—:")
        iso3 = COUNTRY_NAME_TO_ISO3.get(country_part.lower())
        if not iso3:
            inferred = infer_country_isos(country_part)
            iso3 = inferred[0] if inferred else None
        if not iso3:
            continue
        summary = desc if desc else f"US State Dept Travel Advisory: Level {risk_level} — {risk_label}."
        updated_iso = datetime.fromtimestamp(pub_ms / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d")
        advisories[iso3] = {
            "riskLevel": risk_level,
            "headline": risk_label,
            "securitySummary": summary,
            "healthSummary": None,
            "weatherSummary": None,
            "updatedDateIso": updated_iso,
            "sourceLabel": "US State Dept",
        }
    return dict(sorted(advisories.items()))


# MARK: - 3. UN/EU GDACS Disasters RSS Parser

def parse_gdacs_rss(data: bytes, now_ms: int) -> list[dict[str, Any]]:
    root = ET.fromstring(data)
    alerts: list[dict[str, Any]] = []
    seen: set[str] = set()
    event_map = {"TC": "cyclone", "EQ": "earthquake", "FL": "flood", "VO": "volcano", "DR": "drought", "WF": "wildfire"}

    for item in root.findall(".//item"):
        children: dict[str, str] = {}
        for child in item:
            local = child.tag.split("}")[-1].lower()
            children[local] = (child.text or "").strip()

        level = children.get("alertlevel", "").lower()
        if level == "green" or not level:
            continue
        severity = "critical" if level == "red" else ("high" if level == "orange" else "advisory")

        title = strip_html(children.get("title"), max_len=160)
        if not title:
            continue
        event_code = children.get("eventtype", "").upper()
        event_type = event_map.get(event_code, "storm")
        event_id = children.get("eventid") or f"idx-{len(alerts)}"
        alert_id = f"gdacs-{event_code.lower() or 'ev'}-{event_id}"
        if alert_id in seen:
            continue
        seen.add(alert_id)

        summary = strip_html(children.get("description"), max_len=360) or title
        country_name = strip_html(children.get("country"), max_len=120) or "Affected Region"
        iso_set: list[str] = []
        raw_iso3 = children.get("iso3", "").upper()
        for token in re.split(r"[,;/\s]+", raw_iso3):
            if len(token) == 3 and token.isalpha() and token not in iso_set:
                iso_set.append(token)
        if not iso_set:
            iso_set = infer_country_isos(f"{country_name} {title}")

        pub_ms = parse_rfc_or_iso_millis(children.get("pubdate"), now_ms)
        alerts.append({
            "id": alert_id,
            "title": title,
            "eventType": event_type,
            "severity": severity,
            "countryIsos": iso_set,
            "summary": summary,
            "issuedAtUtcMillis": pub_ms,
            "sourceLabel": "GDACS",
            "sourceUrl": sanitize_https_url(children.get("link")),
        })
        if len(alerts) >= 40:
            break

    sev_rank = {"critical": 4, "high": 3, "advisory": 2, "info": 1}
    alerts.sort(key=lambda a: (sev_rank.get(a["severity"], 0), a["issuedAtUtcMillis"]), reverse=True)
    return alerts


# MARK: - 4. WHO Disease Outbreak News Parser

def parse_who_outbreaks_json(data: bytes, now_ms: int) -> list[dict[str, Any]]:
    obj = json.loads(data.decode("utf-8"))
    items = obj.get("value")
    if not isinstance(items, list):
        return []
    notices: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in items[:20]:
        if not isinstance(row, dict):
            continue
        title = strip_html(row.get("Title") or row.get("OverrideTitle"), max_len=160)
        if not title:
            continue
        raw_id = str(row.get("DonId") or row.get("UrlName") or f"who-{len(notices)}").strip()
        notice_id = f"who-{raw_id}"
        if notice_id in seen:
            continue
        seen.add(notice_id)

        summary = strip_html(row.get("Summary") or row.get("Overview"), max_len=360) or title
        pub_ms = parse_rfc_or_iso_millis(row.get("PublicationDate"), now_ms)
        pub_date_iso = datetime.fromtimestamp(pub_ms / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d")
        url_name = str(row.get("UrlName") or "").strip()
        source_url = sanitize_https_url(f"https://www.who.int/emergencies/disease-outbreak-news/item/{url_name}") if url_name else "https://www.who.int/emergencies/disease-outbreak-news"

        lower_title = title.lower()
        severity = "high" if any(k in lower_title for k in ("ebola", "marburg", "mers", "avian", "h5n1", "cholera", "mpox", "yellow fever")) else "advisory"
        isos = infer_country_isos(f"{title} {summary}")
        notices.append({
            "id": notice_id,
            "title": title,
            "summary": summary,
            "countryIsos": isos,
            "severity": severity,
            "publishedDateIso": pub_date_iso,
            "sourceLabel": "WHO",
            "sourceUrl": source_url,
        })
    return notices


# MARK: - 5. Custom Emergency Bulletins Loader

def load_emergency_bulletins(path: Path, now_ms: int) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    entries = raw.get("bulletins", []) if isinstance(raw, dict) else []
    valid_severities = {"info", "advisory", "high", "critical"}
    valid_categories = {"security", "weather", "health", "maritime", "general"}
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        bid = str(entry.get("id", "")).strip()
        title = strip_html(entry.get("title"), max_len=160)
        summary = strip_html(entry.get("summary"), max_len=420)
        if not bid or not title or not summary or bid in seen:
            continue
        expires = entry.get("expiresAtUtcMillis")
        if isinstance(expires, (int, float)) and expires > 0 and int(expires) < now_ms:
            continue
        seen.add(bid)
        sev = str(entry.get("severity", "advisory")).strip().lower()
        cat = str(entry.get("category", "general")).strip().lower()
        isos = sorted({
            str(x).strip().upper()
            for x in (entry.get("countryIsos") or [])
            if isinstance(x, str) and len(x.strip()) == 3 and x.strip().isalpha()
        })
        region = strip_html(entry.get("regionLabel"), max_len=80) or ("Global" if not isos else ", ".join(isos[:3]))
        out.append({
            "id": bid,
            "title": title,
            "summary": summary,
            "severity": sev if sev in valid_severities else "advisory",
            "category": cat if cat in valid_categories else "general",
            "regionLabel": region,
            "countryIsos": isos,
            "publishedAtUtcMillis": int(entry.get("publishedAtUtcMillis") or now_ms),
            "expiresAtUtcMillis": int(expires) if isinstance(expires, (int, float)) and expires > 0 else None,
            "sourceLabel": strip_html(entry.get("sourceLabel"), max_len=64) or "Clearstay Broadcast",
            "sourceUrl": sanitize_https_url(entry.get("sourceUrl")),
        })
    return out


# MARK: - Offline Deterministic Test Fixtures

def build_offline_test_snapshot(bulletins_path: Path) -> dict[str, Any]:
    now_ms = 1_795_600_000_000
    ecb_fixture = b"""<?xml version="1.0" encoding="UTF-8"?>
    <gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01" xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref"><Cube><Cube time='2026-11-26'>
      <Cube currency='USD' rate='1.0800'/>
      <Cube currency='GBP' rate='0.8424'/>
      <Cube currency='JPY' rate='162.00'/>
      <Cube currency='CHF' rate='0.9504'/>
      <Cube currency='AUD' rate='1.6524'/>
    </Cube></Cube></gesmes:Envelope>"""
    state_fixture = b"""<rss><channel>
      <item>
        <title>Spain - Level 2: Exercise Increased Caution</title>
        <description>Exercise increased caution in Spain due to terrorism and civil unrest.</description>
        <link>https://travel.state.gov/content/travel/en/traveladvisories/traveladvisories/spain-travel-advisory.html</link>
        <pubDate>Wed, 25 Nov 2026 12:00:00 GMT</pubDate>
      </item>
      <item>
        <title>United Arab Emirates - Level 2: Exercise Increased Caution</title>
        <description>Exercise increased caution due to regional tensions.</description>
        <link>https://travel.state.gov/content/travel/en/traveladvisories/traveladvisories/united-arab-emirates-travel-advisory.html</link>
        <pubDate>Wed, 25 Nov 2026 12:00:00 GMT</pubDate>
      </item>
    </channel></rss>"""
    gdacs_fixture = b"""<rss xmlns:gdacs="http://www.gdacs.org"><channel>
      <item>
        <title>Orange alert for Tropical Cyclone in Philippines</title>
        <description>Severe maritime winds and coastal flooding expected across Luzon.</description>
        <link>https://www.gdacs.org/report.aspx?eventid=4201</link>
        <gdacs:eventtype>TC</gdacs:eventtype>
        <gdacs:eventid>4201</gdacs:eventid>
        <gdacs:alertlevel>Orange</gdacs:alertlevel>
        <gdacs:iso3>PHL</gdacs:iso3>
        <gdacs:country>Philippines</gdacs:country>
      </item>
    </channel></rss>"""
    who_fixture = json.dumps({
        "value": [{
            "DonId": "2026-DON500",
            "Title": "Dengue - Global situation in Brazil",
            "Summary": "WHO surveillance advisory for travelers visiting endemic regions.",
            "PublicationDate": "2026-11-24T10:00:00Z",
            "UrlName": "2026-DON500",
        }]
    }).encode("utf-8")

    return {
        "schemaVersion": SCHEMA_VERSION,
        "snapshotId": "test-2026-11-26T00Z",
        "generatedAtUtcMillis": now_ms,
        "fx": parse_ecb_daily_xml(ecb_fixture),
        "bulletins": load_emergency_bulletins(bulletins_path, now_ms),
        "countryAdvisories": parse_state_dept_advisories_rss(state_fixture, now_ms),
        "disasters": parse_gdacs_rss(gdacs_fixture, now_ms),
        "healthNotices": parse_who_outbreaks_json(who_fixture, now_ms),
    }


def build_live_snapshot(bulletins_path: Path, previous: dict[str, Any] | None) -> dict[str, Any]:
    now_ms = now_utc_millis()
    snapshot_id = datetime.fromtimestamp(now_ms / 1000.0, tz=timezone.utc).strftime("%Y-%m-%dT%H%MZ")
    prev = previous if isinstance(previous, dict) else {}

    # 1. FX (Open ER-API primary -> ECB Daily XML fallback -> previous cache)
    fx = None
    try:
        fx = parse_open_er_api(http_get_bytes(OPEN_ER_API_URL))
    except Exception as exc:
        print(f"[warn] Open ER-API fetch failed: {exc}", file=sys.stderr)
    if fx is None:
        try:
            fx = parse_ecb_daily_xml(http_get_bytes(ECB_DAILY_XML_URL))
        except Exception as exc:
            print(f"[warn] ECB XML fetch failed: {exc}", file=sys.stderr)
    if fx is None:
        fx = prev.get("fx")

    # 2. US State Dept Travel Advisories (None = fetch/parse failed -> fallback; {} = valid empty)
    advisories: dict[str, Any] | None = None
    try:
        advisories = parse_state_dept_advisories_rss(http_get_bytes(STATE_DEPT_RSS_URL), now_ms)
    except Exception as exc:
        print(f"[warn] State Dept RSS fetch failed: {exc}", file=sys.stderr)
    if advisories is None:
        advisories = prev.get("countryAdvisories") if isinstance(prev.get("countryAdvisories"), dict) else {}

    # 3. GDACS Global Disasters (None = fetch/parse failed -> fallback; [] = valid empty, clears expired hazards!)
    disasters: list[dict[str, Any]] | None = None
    try:
        disasters = parse_gdacs_rss(http_get_bytes(GDACS_RSS_URL), now_ms)
    except Exception as exc:
        print(f"[warn] GDACS RSS fetch failed: {exc}", file=sys.stderr)
    if disasters is None:
        disasters = prev.get("disasters") if isinstance(prev.get("disasters"), list) else []

    # 4. WHO Disease Outbreak News (None = fetch/parse failed -> fallback; [] = valid empty)
    health: list[dict[str, Any]] | None = None
    try:
        health = parse_who_outbreaks_json(http_get_bytes(WHO_DON_URL), now_ms)
    except Exception as exc:
        print(f"[warn] WHO DON API fetch failed: {exc}", file=sys.stderr)
    if health is None:
        health = prev.get("healthNotices") if isinstance(prev.get("healthNotices"), list) else []

    # 5. Custom Emergency Bulletins
    bulletins = load_emergency_bulletins(bulletins_path, now_ms)

    return {
        "schemaVersion": SCHEMA_VERSION,
        "snapshotId": snapshot_id,
        "generatedAtUtcMillis": now_ms,
        "fx": fx,
        "bulletins": bulletins,
        "countryAdvisories": advisories,
        "disasters": disasters,
        "healthNotices": health,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Clearstay global static Live Briefings snapshot.")
    parser.add_argument("--bulletins", type=Path, default=Path(__file__).resolve().parent / "emergency_bulletins.json")
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "dist" / "snapshot-v1.json")
    parser.add_argument("--previous", type=Path, default=None)
    parser.add_argument("--test-offline", action="store_true", help="Build deterministic offline fixture snapshot.")
    args = parser.parse_args()

    previous: dict[str, Any] | None = None
    prev_path = args.previous or (args.out if args.out.exists() else None)
    if not args.test_offline and prev_path and prev_path.exists():
        try:
            previous = json.loads(prev_path.read_text(encoding="utf-8"))
        except Exception:
            previous = None

    snapshot = (
        build_offline_test_snapshot(args.bulletins)
        if args.test_offline
        else build_live_snapshot(args.bulletins, previous)
    )

    encoded = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_SNAPSHOT_BYTES:
        raise SystemExit(f"ERROR: snapshot-v1.json ({len(encoded)} bytes) exceeds {MAX_SNAPSHOT_BYTES} byte cap")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(encoded)
    gz_path = Path(str(args.out) + ".gz")
    gz_path.write_bytes(gzip.compress(encoded, compresslevel=9))

    fx_count = len((snapshot.get("fx") or {}).get("rates") or {})
    print(
        f"Built {args.out} ({len(encoded):,} B raw, {gz_path.stat().st_size:,} B gzip): "
        f"{fx_count} FX rates, {len(snapshot['countryAdvisories'])} advisories, "
        f"{len(snapshot['disasters'])} GDACS alerts, {len(snapshot['healthNotices'])} WHO notices, "
        f"{len(snapshot['bulletins'])} custom bulletins."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

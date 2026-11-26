#!/usr/bin/env python3
"""Updates feed/emergency_bulletins.json from workflow_dispatch environment variables."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path


def main() -> int:
    path = Path("feed/emergency_bulletins.json")
    doc = json.loads(path.read_text(encoding="utf-8"))
    bulletins = list(doc.get("bulletins") or [])
    action = os.environ["INPUT_ACTION"].strip()
    now_ms = int(time.time() * 1000)

    if action == "clear_all":
        bulletins = []
    elif action == "remove_by_id":
        target = os.environ.get("INPUT_ALERT_ID", "").strip()
        if not target:
            raise SystemExit("alert_id is required for remove_by_id")
        bulletins = [b for b in bulletins if b.get("id") != target]
    elif action == "publish":
        title = os.environ.get("INPUT_TITLE", "").strip()
        summary = os.environ.get("INPUT_SUMMARY", "").strip()
        if not title or not summary:
            raise SystemExit("Both title and summary are required to publish an alert.")
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:32] or "alert"
        bid = os.environ.get("INPUT_ALERT_ID", "").strip() or f"{slug}-{int(time.time())}"
        raw_isos = os.environ.get("INPUT_COUNTRY_ISOS", "").strip()
        isos = sorted({
            tok.strip().upper()
            for tok in re.split(r"[,;\s]+", raw_isos)
            if len(tok.strip()) == 3 and tok.strip().isalpha()
        })
        try:
            hours = max(1, min(720, int(os.environ.get("INPUT_EXPIRES_HOURS", "48").strip() or "48")))
        except ValueError:
            hours = 48
        url = os.environ.get("INPUT_SOURCE_URL", "").strip()
        if url and not url.lower().startswith("https://"):
            raise SystemExit("source_url must start with https://")
        region = os.environ.get("INPUT_REGION_LABEL", "").strip() or ("Global" if not isos else ", ".join(isos[:3]))

        bulletins = [
            b for b in bulletins
            if b.get("id") != bid and (not b.get("expiresAtUtcMillis") or int(b["expiresAtUtcMillis"]) >= now_ms)
        ]
        bulletins.insert(0, {
            "id": bid,
            "title": title[:160],
            "summary": summary[:400],
            "severity": os.environ.get("INPUT_SEVERITY", "high").strip(),
            "category": os.environ.get("INPUT_CATEGORY", "security").strip(),
            "regionLabel": region[:80],
            "countryIsos": isos,
            "publishedAtUtcMillis": now_ms,
            "expiresAtUtcMillis": now_ms + hours * 3600 * 1000,
            "sourceLabel": "Clearstay Broadcast",
            "sourceUrl": url or None,
        })
    else:
        raise SystemExit(f"Unsupported action: {action}")

    doc["bulletins"] = bulletins
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Updated feed/emergency_bulletins.json (active bulletins: {len(bulletins)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

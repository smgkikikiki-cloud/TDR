"""Turn one price-feed run's stored exceptions into a short human notice.

The scheduled price feed already runs every 12 hours and already records,
for every claim whose grade name does not resolve to any canonical
MarketTrim, a ``PRICE_IDENTITY`` exception (see
``vehreg.pricefeed_writer.exception_rows`` / ``tools.pricefeed_write``).
That is the real, positive signal that a trim lineup may have changed --
a news article or OEM page named a grade this catalog does not know. This
script does not invent any new detection: it only decides whether this
run's already-computed exceptions are worth telling a person about, and
writes the message.

Only ``PRICE_IDENTITY`` rows are surfaced here. ``PRICE_CONFLICT`` rows
(two sources disagreeing on an amount) are a different, already-visible
kind of unresolved work and are left out on purpose so this notice stays
about identity drift -- new/renamed/discontinued trims -- not every kind
of thing the feed could not settle.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional


def build_notice(exceptions_path: Path) -> Optional[str]:
    payload = json.loads(exceptions_path.read_text(encoding="utf-8"))
    rows = [row for row in payload.get("exceptions", []) if row.get("kind") == "PRICE_IDENTITY"]
    if not rows:
        return None

    lines = [
        f"Price feed run `{payload.get('batch_ref', '')}` found {len(rows)} grade "
        "name(s) that did not match any canonical MarketTrim.",
        "",
        "This can mean a trim was added, renamed, or discontinued -- or it can be a "
        "one-off wording the matcher does not know yet. Check each source below and "
        "either add/retire the MarketTrim it needs, or teach the matcher the wording.",
        "",
    ]
    for row in rows:
        identity = row.get("source_identity") or {}
        candidates = identity.get("trim_candidates") or []
        urls = identity.get("urls") or []
        lines.append(f"- {row.get('reason') or 'unresolved'}")
        if candidates:
            lines.append(f"  closest existing candidates: {', '.join(candidates)}")
        for url in urls:
            lines.append(f"  {url}")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("exceptions_file", type=Path)
    args = parser.parse_args(argv)

    notice = build_notice(args.exceptions_file)
    if notice is None:
        return 1  # nothing worth notifying about this run
    print(notice)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

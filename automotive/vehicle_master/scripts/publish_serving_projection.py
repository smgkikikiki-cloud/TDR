#!/usr/bin/env python3
"""Build/apply one Phase-E canonical serving projection.

Dry-run is the default. `--apply` calls the service-role-only transactional RPC
created by migration_v14_serving_projection.sql.
"""

from __future__ import annotations

import argparse
from datetime import date
import json
import os
from pathlib import Path
import sys
from urllib import error, request

# Allow execution from the imported Vehicle Master directory without package
# installation, matching the rest of the repo's CLI/test workflow.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vehreg.serving_projection import build_model_serving_projection  # noqa: E402


def apply_projection(payload: dict) -> dict:
    base = (os.environ.get("NEXT_PUBLIC_SUPABASE_URL") or "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or ""
    if not base or not key:
        raise RuntimeError(
            "--apply requires NEXT_PUBLIC_SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY"
        )
    body = json.dumps({"p_projection": payload}, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        f"{base}/rest/v1/rpc/apply_vehicle_serving_projection",
        data=body,
        method="POST",
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with request.urlopen(req, timeout=30) as response:
            raw = response.read().decode("utf-8")
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Supabase projection RPC failed: HTTP {exc.code}: {detail}") from exc
    return json.loads(raw) if raw else {}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("model_id", help="canonical model ID")
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--as-of")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()

    when = date.fromisoformat(args.as_of) if args.as_of else None
    payload = build_model_serving_projection(args.model_id, year=args.year, as_of=when)
    if not args.apply:
        print(json.dumps(
            payload,
            ensure_ascii=False,
            indent=None if args.compact else 2,
            separators=(",", ":") if args.compact else None,
        ))
        return 0

    result = apply_projection(payload)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

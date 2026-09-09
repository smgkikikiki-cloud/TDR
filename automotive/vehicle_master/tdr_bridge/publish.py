"""Publish a prepared canonical vehicle release through the Supabase RPC."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def _clean_env_value(value: str | None, *names: str) -> str:
    """Accept either a bare secret value or a copied NAME=value assignment."""
    cleaned = (value or "").strip()
    if "=" in cleaned:
        prefix, remainder = cleaned.split("=", 1)
        if prefix.strip() in names:
            cleaned = remainder.strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {"'", '"'}:
        cleaned = cleaned[1:-1].strip()
    return cleaned


def publish(release: dict, *, url: str, service_key: str) -> dict:
    endpoint = url.rstrip("/") + "/rest/v1/rpc/publish_vehicle_release"
    headers = {
        "apikey": service_key,
        "content-type": "application/json",
        "accept": "application/json",
    }
    # Legacy service_role keys are JWTs and may be used as Bearer credentials.
    # Modern sb_secret_* keys are API keys, not JWTs, so they belong only in apikey.
    if service_key.startswith("eyJ"):
        headers["authorization"] = f"Bearer {service_key}"
    request = Request(
        endpoint,
        data=json.dumps({"release": release}, ensure_ascii=False,
                        separators=(",", ":")).encode(),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=120) as response:
            body = response.read().decode()
    except HTTPError as exc:
        body = exc.read().decode(errors="replace")
        raise RuntimeError(f"publish failed ({exc.code}): {body}") from exc
    return json.loads(body) if body else {}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release", type=Path)
    parser.add_argument("--publish", action="store_true",
                        help="call Supabase; without this flag only validate and print")
    args = parser.parse_args(argv)
    release = json.loads(args.release.read_text(encoding="utf-8"))
    expected = release.get("counts", {})
    for key in ("brands", "models", "generations", "market_trims", "price_ledger", "spec_facts"):
        if expected.get(key) != len(release.get(key, [])):
            raise SystemExit(f"count mismatch for {key}")
    if not args.publish:
        print(json.dumps({"validated": True, "release_id": release["release_id"],
                          "counts": expected}, ensure_ascii=False))
        return 0
    url = _clean_env_value(
        os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL"),
        "SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_URL",
    )
    key = _clean_env_value(
        os.environ.get("SUPABASE_SECRET_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
        "SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY",
    )
    if not url or not key:
        raise SystemExit(
            "SUPABASE_URL/NEXT_PUBLIC_SUPABASE_URL and "
            "SUPABASE_SECRET_KEY/SUPABASE_SERVICE_ROLE_KEY are required"
        )
    print(json.dumps(publish(release, url=url, service_key=key), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

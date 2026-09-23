"""Build, publish and verify the release for one exact revision.

    python -m tools.publish_canonical --revision "$(git rev-parse HEAD)"

Every automated writer calls this after it pushes, and waits for it. The
alternative -- push to main and trust that some other workflow notices --
is not a publish path, it is a hope: nothing fails if the other workflow
never fires, the writer reports success anyway, and the data sits
committed but unserved.

It also refuses to succeed on the wrong state. The release is built from
the revision it was given and verified against what Supabase is actually
serving afterwards, so a stale pre-rebase tree cannot be published and
called done.
"""

from __future__ import annotations

import argparse
from datetime import date
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]


def _env() -> tuple[str, str]:
    url = (os.environ.get("SUPABASE_URL") or "").strip().rstrip("/")
    key = (os.environ.get("SUPABASE_SECRET_KEY")
           or os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    if not url or not key:
        raise SystemExit("SUPABASE_URL and SUPABASE_SECRET_KEY/SERVICE_ROLE_KEY are required")
    return url, key


def _get(path: str):
    url, key = _env()
    headers = {"apikey": key, "accept": "application/json"}
    if key.startswith("eyJ"):
        headers["authorization"] = f"Bearer {key}"
    try:
        with urlopen(Request(f"{url}/rest/v1/{path}", headers=headers), timeout=60) as response:
            body = response.read().decode()
    except HTTPError as exc:
        raise RuntimeError(f"Supabase read failed ({exc.code}): "
                           f"{exc.read().decode(errors='replace')[:400]}") from exc
    return json.loads(body) if body else None


def _revision_ordinal(revision: str) -> str | None:
    """How far along git history ``revision`` sits, as a monotonic proxy
    for commit order the publish RPC uses to refuse activating a release
    older than what is already serving (migration_v44).

    Requires a full clone (``fetch-depth: 0``); a shallow one undercounts
    and would produce a WRONG, too-low ordinal for a genuinely later
    commit, so this returns ``None`` -- no ordinal, no guard, degrade to
    the pre-v44 behavior -- rather than pass a number that could reject a
    legitimate publish.
    """
    try:
        shallow = subprocess.run(
            ["git", "rev-parse", "--is-shallow-repository"],
            cwd=REPO_ROOT, check=True, capture_output=True, text=True,
        ).stdout.strip()
        if shallow == "true":
            return None
        return subprocess.run(
            ["git", "rev-list", "--count", revision],
            cwd=REPO_ROOT, check=True, capture_output=True, text=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, OSError):
        return None


def build(revision: str, as_of: str, out: Path) -> dict:
    ordinal = _revision_ordinal(revision)
    command = [
        sys.executable, "-m", "tdr_bridge.release_enriched",
        "--inventory", "integration_data/tdr_2026-09-09.json",
        "--overrides", "integration_data/crosswalk_overrides.json",
        "--revision", revision, "--as-of", as_of, "--out", str(out),
    ]
    if ordinal is not None:
        command += ["--revision-ordinal", ordinal]
    subprocess.run(command, cwd=REPO_ROOT, check=True, capture_output=True, text=True)
    return json.loads(out.read_text(encoding="utf-8"))


def publish(release_file: Path):
    subprocess.run([
        sys.executable, "-m", "tdr_bridge.publish", str(release_file), "--publish",
    ], cwd=REPO_ROOT, check=True, capture_output=True, text=True)


def verify_serving(release_id: str) -> dict:
    """Confirm Supabase is serving the release we just published -- not
    just that a row for it exists.

    Publishing without reading back is how a writer ends up reporting a
    success that never reached anybody. A release row existing is not
    enough either: a release_id that was once ACTIVE and has since been
    SUPERSEDED by something newer still has a row (and, if nothing raced
    it, still a non-empty projection from whatever the active release
    happens to be) -- an exact-publish check that only asked those two
    questions would call that a success. It is not: this call is asking
    whether *this* release_id is the one currently serving.
    """
    rows = _get(f"canonical_vehicle_releases?select=release_id,status,activated_at"
                f"&release_id=eq.{release_id}") or []
    if not rows:
        raise SystemExit(f"published {release_id} but Supabase has no such release")
    row = rows[0]
    state = _get("canonical_vehicle_state?select=active_release_id&scope=eq.vehicle_catalog") or []
    active_release_id = state[0].get("active_release_id") if state else None
    if row.get("status") != "ACTIVE" or active_release_id != release_id:
        raise SystemExit(
            f"published {release_id} but it is not the active release "
            f"(status={row.get('status')!r}, active_release_id={active_release_id!r})"
        )
    trims = _get("current_market_trims?select=canonical_id&limit=1") or []
    if not trims:
        raise SystemExit(f"release {release_id} is present but the serving projection is empty")
    return {"release_id": row["release_id"], "status": row.get("status"),
            "activated_at": row.get("activated_at")}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True,
                        help="the exact commit whose tree is being published")
    parser.add_argument("--as-of", default=date.today().isoformat())
    parser.add_argument("--out", type=Path, default=Path("/tmp/vehicle-release.json"))
    parser.add_argument("--dry-run", action="store_true",
                        help="build and validate without publishing")
    args = parser.parse_args(argv)

    release = build(args.revision, args.as_of, args.out)
    release_id = str(release["release_id"])
    if args.dry_run:
        print(json.dumps({"release_id": release_id, "published": False,
                          "counts": release.get("counts", {})}, ensure_ascii=False))
        return 0

    publish(args.out)
    serving = verify_serving(release_id)
    print(json.dumps({**serving, "published": True, "revision": args.revision,
                      "counts": release.get("counts", {})}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

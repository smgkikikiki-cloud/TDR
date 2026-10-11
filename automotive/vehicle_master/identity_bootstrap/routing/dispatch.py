"""The pre-activation dispatch boundary: a pure projection. It reads decisions and returns NEW records; it never mutates a decision, an identity or a write plan."""
from __future__ import annotations

from identity_bootstrap.market_activity import load_policy as load_activity_policy

from .signals import load_policy as load_routing_policy

CURRENT = "CURRENT_DISCOVERY"
LANES = ("CURRENT_DISCOVERY", "HISTORICAL_INACTIVE", "ACTIVITY_UNCLASSIFIED", "OWNER_REVIEW", "NOT_DISPATCHED")


def project(decision: dict, activity_state: str | None, review: dict | None = None, activity_policy: dict | None = None, routing_policy: dict | None = None) -> dict:
    """Lane for one decision. Only a CREATE_IDENTITY is ever dispatched. Precedence: mandatory owner review, then the market-activity lane
    (ACTIVE / DECLINING / REACTIVATED -> CURRENT_DISCOVERY; INACTIVE_INFERRED -> HISTORICAL_INACTIVE; UNKNOWN or anything else -> ACTIVITY_UNCLASSIFIED)."""
    ap, rp = activity_policy or load_activity_policy(), routing_policy or load_routing_policy()
    gid = decision["subject"]["entity_id"]
    base = {"external_id": gid, "bootstrap_outcome": decision["outcome"], "activity_state": activity_state, "review_flags": list((review or {}).get("flags", ()))}
    if decision["outcome"] != "CREATE_IDENTITY":
        return {**base, "lane": rp["lanes"]["not_dispatched"], "why": "not a CREATE_IDENTITY decision"}
    if (review or {}).get("mandatory_owner_review"):
        return {**base, "lane": rp["lanes"]["owner_review"], "why": "mandatory owner review: " + ", ".join(base["review_flags"])}
    lane = ap["lanes"].get(activity_state or "", ap["lanes"]["UNKNOWN"])
    return {**base, "lane": lane, "why": f"market-activity state {activity_state or 'UNKNOWN'}"}


def dispatch_all(decisions: list[dict], activity: dict[str, str], reviews: dict[str, dict]) -> list[dict]:
    ap, rp = load_activity_policy(), load_routing_policy()
    return [project(d, activity.get(d["subject"]["entity_id"]), reviews.get(d["subject"]["entity_id"]), ap, rp) for d in decisions]


def current_dispatch(dispatched: list[dict]) -> list[dict]:
    """The only output a current-market activation may consume."""
    return [r for r in dispatched if r["lane"] == CURRENT]

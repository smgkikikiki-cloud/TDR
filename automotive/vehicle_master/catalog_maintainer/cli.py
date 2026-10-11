"""CLI: python -m automotive.vehicle_master.catalog_maintainer.cli simulate ..."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from .simulator import simulate
from .replay import replay
from .retail_reconcile import reconcile_retail_lineup
from .offline_runner import FakeClock, OfflineFakeProvider, OfflineRunner, SQLiteJobStore
from .validation import validate_fixture, validate_policy


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="catalog-maintainer")
    sub = parser.add_subparsers(dest="command", required=True)
    sim = sub.add_parser("simulate", help="run deterministic offline fixture planning")
    sim.add_argument("--fixture", required=True)
    sim.add_argument("--out", required=True)
    sim.add_argument("--budget", type=int, default=None)
    rep = sub.add_parser("replay", help="replay recorded local evidence without network/provider access")
    rep.add_argument("--fixture", required=True)
    rep.add_argument("--documents", required=True, nargs="+")
    rep.add_argument("--out", required=True)
    retail = sub.add_parser("retail-reconcile", help="validate and diff a recorded Thai retail lineup offline")
    retail.add_argument("--fixture", required=True)
    retail.add_argument("--document", required=True)
    retail.add_argument("--policy", default=str(Path(__file__).parent / "contract" / "policy.yaml"))
    retail.add_argument("--out", required=True)
    offline_plan = sub.add_parser("offline-plan", help="plan local jobs into a durable SQLite journal")
    offline_plan.add_argument("--fixture", required=True)
    offline_plan.add_argument("--db", required=True)
    offline_plan.add_argument("--now-epoch", required=True, type=int)
    offline_plan.add_argument("--policy", default=str(Path(__file__).parent / "contract" / "policy.yaml"))
    offline_plan.add_argument("--out")
    offline_step = sub.add_parser("offline-step", help="execute one explicitly acknowledged local MOCK step")
    offline_step.add_argument("--db", required=True)
    offline_step.add_argument("--responses", required=True, help="local canned response JSON; no provider/network")
    offline_step.add_argument("--now-epoch", required=True, type=int)
    offline_step.add_argument("--policy", default=str(Path(__file__).parent / "contract" / "policy.yaml"))
    offline_step.add_argument("--confirm-mock-only", action="store_true", required=True)
    offline_step.add_argument("--out")
    offline_report = sub.add_parser("offline-report", help="export durable local journal state")
    offline_report.add_argument("--db", required=True)
    offline_report.add_argument("--out")
    args = parser.parse_args(argv)
    if args.command == "simulate":
        result = simulate(args.fixture, args.out, budget=args.budget)
        print(f"MOCK: {result['summary']['planned_items']} planned items; 0 HTTP, 0 paid calls/tokens, 0 writes")
        return 0
    if args.command == "replay":
        result = replay(args.fixture, args.documents, args.out)
        print(f"REPLAY: {result['accepted_candidates']} accepted candidates; 0 HTTP, 0 paid calls/tokens, 0 writes")
        return 0
    if args.command == "retail-reconcile":
        snapshot = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
        document = json.loads(Path(args.document).read_text(encoding="utf-8"))
        policy = json.loads(Path(args.policy).read_text(encoding="utf-8"))
        validate_fixture(snapshot)
        validate_policy(policy)
        result = reconcile_retail_lineup(snapshot, document, policy=policy)
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        print(f"RETAIL REPLAY: {len(result['outcomes'])} outcomes; 0 HTTP, 0 paid calls/tokens, 0 writes")
        return 0
    if args.command in {"offline-plan","offline-step"}:
        policy = json.loads(Path(args.policy).read_text(encoding="utf-8"))
        validate_policy(policy)
        clock = FakeClock(args.now_epoch)
        store = SQLiteJobStore(args.db)
        try:
            if args.command == "offline-plan":
                snapshot = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
                runner = OfflineRunner(store,policy,clock,OfflineFakeProvider(clock=clock))
                result = runner.enqueue_plan(snapshot)
            else:
                responses = json.loads(Path(args.responses).read_text(encoding="utf-8"))
                provider = OfflineFakeProvider(responses.get("responses"),default=responses.get("default"),
                                               clock=clock)
                runner = OfflineRunner(store,policy,clock,provider)
                runner.arm_one_manual_mock_step()
                step_result = runner.run_one_manual_step()
                result = {"step_result":step_result,"provider_fake_calls":provider.calls,
                          "runner_report":runner.report()}
            rendered = json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+"\n"
            if args.out:
                Path(args.out).parent.mkdir(parents=True,exist_ok=True)
                Path(args.out).write_text(rendered,encoding="utf-8")
            print(rendered,end="")
        finally:
            store.close()
        return 0
    if args.command == "offline-report":
        store = SQLiteJobStore(args.db)
        try: rendered=json.dumps(store.report(),ensure_ascii=False,sort_keys=True,indent=2)+"\n"
        finally: store.close()
        if args.out:
            Path(args.out).parent.mkdir(parents=True,exist_ok=True)
            Path(args.out).write_text(rendered,encoding="utf-8")
        print(rendered,end="")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

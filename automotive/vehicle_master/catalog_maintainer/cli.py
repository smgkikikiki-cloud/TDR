"""CLI: python -m automotive.vehicle_master.catalog_maintainer.cli simulate ..."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from .simulator import simulate
from .replay import replay
from .retail_reconcile import reconcile_retail_lineup
from .offline_runner import FakeClock, OfflineFakeProvider, OfflineRunner, SQLiteJobStore, build_offline_plan
from .acquisition import (ContentAddressedEvidenceStore, DeterministicFakeHTTPTransport,
                          OfflineSourceAcquisitionAdapter, load_source_registry)
from .validation import validate_fixture, validate_policy
from .shadow_snapshot import write_shadow_report
from .ai_extraction import run_mock_extraction


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
    acquire = sub.add_parser("offline-acquire", help="replay a prerecorded source response; no live HTTP client exists")
    acquire.add_argument("--fixture", required=True)
    acquire.add_argument("--target-key", required=True)
    acquire.add_argument("--source-id", required=True)
    acquire.add_argument("--url", required=True)
    acquire.add_argument("--responses", required=True)
    acquire.add_argument("--store", required=True)
    acquire.add_argument("--now-epoch", required=True, type=int)
    acquire.add_argument("--policy", default=str(Path(__file__).parent / "contract" / "policy.yaml"))
    acquire.add_argument("--registry", default=str(Path(__file__).parent / "contract" / "source_registry.json"))
    acquire.add_argument("--confirm-prerecorded-only", action="store_true", required=True)
    acquire.add_argument("--out")
    shadow = sub.add_parser("shadow-report", help="build a read-only report from a versioned local Vehicle Master export")
    shadow.add_argument("--snapshot", required=True, help="local normalized export JSON; no database connection is available")
    shadow.add_argument("--policy", default=str(Path(__file__).parent / "contract" / "policy.yaml"))
    shadow.add_argument("--out", required=True)
    ai = sub.add_parser("extract-mock", help="validate a recorded structured extraction; no AI/network client exists")
    ai.add_argument("--fixture", required=True, help="local normalized snapshot")
    ai.add_argument("--documents", required=True, nargs="+", help="local source documents")
    ai.add_argument("--responses", required=True, help="recorded MOCK cassette JSON")
    ai.add_argument("--cache", required=True, help="local content-addressed response cache")
    ai.add_argument("--out", required=True)
    ai.add_argument("--confirm-mock-only", action="store_true", required=True)
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
    if args.command == "offline-acquire":
        snapshot=json.loads(Path(args.fixture).read_text(encoding="utf-8"))
        policy=json.loads(Path(args.policy).read_text(encoding="utf-8"))
        validate_fixture(snapshot); validate_policy(policy)
        planned=build_offline_plan(snapshot,policy,now=args.now_epoch)
        task=next((row for row in planned["tasks"] if row["target_key"]==args.target_key),None)
        if task is None:
            parser.error("target key is not an eligible task in this fixture snapshot")
        clock=FakeClock(args.now_epoch)
        store=ContentAddressedEvidenceStore(args.store)
        try:
            transport=DeterministicFakeHTTPTransport.from_manifest(args.responses)
            adapter=OfflineSourceAcquisitionAdapter(load_source_registry(args.registry),transport,store,policy,clock)
            result=adapter.acquire(task,source_id=args.source_id,url=args.url,snapshot=snapshot)
            result["fake_transport_requests"]=len(transport.calls)
            result["fixture_only_mode"]=True
            rendered=json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+"\n"
            if args.out:
                Path(args.out).parent.mkdir(parents=True,exist_ok=True)
                Path(args.out).write_text(rendered,encoding="utf-8")
            print(rendered,end="")
        finally:
            store.close()
        return 0
    if args.command == "shadow-report":
        report = write_shadow_report(Path(args.snapshot), Path(args.policy), Path(args.out),
                                     repository_root=Path(__file__).resolve().parents[3])
        print(f"SHADOW: {report['coverage']['eligible_current_models']} eligible, "
              f"{report['coverage']['retail_audit_only_models']} audit-only, "
              f"{report['gaps']['real_or_researchable']} researchable gaps; 0 external/paid/Production/writes")
        return 0
    if args.command == "extract-mock":
        result = run_mock_extraction(args.fixture, args.documents, args.responses,
                                     args.cache, args.out, confirm_mock_only=args.confirm_mock_only)
        print(f"AI MOCK: {result['accepted_ai_mock_candidates']} validated proposals; "
              f"cache {result['cache_hits']} hit/{result['cache_misses']} miss; "
              "0 HTTP, 0 paid calls/tokens/spend, 0 Production access/writes")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

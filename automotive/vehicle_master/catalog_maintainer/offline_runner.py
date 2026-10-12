"""Deterministic, local-only research planning and one-step MOCK execution.

SQLite is used only as a local durable job journal. This module has no network,
provider, Production database, background worker, or canonical writer adapter.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3
from typing import Any

from .gap_inventory import gaps_for_model
from .planner import plan
from .validation import validate_fixture, validate_policy

QUEUES = ("RETAIL_AUDIT", "SPEC_ENRICH")
TERMINAL_STATES = {
    "COMPLETED", "SOURCE_EXHAUSTED", "BUDGET_EXHAUSTED", "SOURCE_BROKEN",
    "IDENTITY_AMBIGUOUS", "CONFLICT",
}
ACTIVE_STATES = {"QUEUED", "LEASED", "RETRY_WAIT"}
ALL_STATES = TERMINAL_STATES | ACTIVE_STATES


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def validate_runner_report(report: dict) -> None:
    required={"jobs","job_counts_by_state","planning_dispositions","events","daily_usage",
              "external_http_calls","paid_model_calls","paid_tokens","paid_spend_thb",
              "production_database_accesses","production_writes","background_workers_started",
              "canonical_writes"}
    if not isinstance(report,dict) or required-set(report):
        raise ValueError("offline runner report is missing required contract sections")
    for key in ("external_http_calls","paid_model_calls","paid_tokens","paid_spend_thb",
                "production_database_accesses","production_writes","background_workers_started",
                "canonical_writes"):
        if report[key] != 0:
            raise ValueError(f"offline runner report escaped zero boundary: {key}")
    if not isinstance(report["jobs"], list) or not isinstance(report["events"], list):
        raise ValueError("offline runner report jobs/events must be arrays")
    if any(job.get("status") not in ALL_STATES or job.get("queue") not in QUEUES
           or not isinstance(job.get("idempotency_key"), str)
           or len(job["idempotency_key"]) != 64
           or any(c not in "0123456789abcdef" for c in job["idempotency_key"])
           or type(job.get("attempt_count")) is not int or type(job.get("max_attempts")) is not int
           or job["attempt_count"] < 0 or job["max_attempts"] < 1
           or not isinstance(job.get("payload"), dict) or not isinstance(job.get("checkpoint"), dict)
           for job in report["jobs"]):
        raise ValueError("offline runner report contains invalid job")
    expected = {state: sum(job["status"] == state for job in report["jobs"])
                for state in sorted(ALL_STATES)}
    if report["job_counts_by_state"] != expected:
        raise ValueError("offline runner report job state counts do not match jobs")
    for usage in report["daily_usage"]:
        if (not isinstance(usage.get("day"), str)
                or any(type(usage.get(k)) is not int or usage[k] < 0 for k in
                       ("offline_requests", "reported_tokens", "elapsed_seconds"))
                or type(usage.get("reported_spend_thb")) not in {int, float}
                or not math.isfinite(usage["reported_spend_thb"]) or usage["reported_spend_thb"] < 0):
            raise ValueError("offline runner report contains invalid daily usage")


def validate_offline_plan(result: dict) -> None:
    required = {"tasks", "dispositions", "planner_summary"}
    if not isinstance(result, dict) or required - result.keys():
        raise ValueError("offline plan is missing required contract sections")
    keys = set()
    for task in result["tasks"]:
        if (not isinstance(task, dict) or task.get("queue") not in QUEUES
                or not isinstance(task.get("idempotency_key"), str)
                or len(task["idempotency_key"]) != 64
                or any(c not in "0123456789abcdef" for c in task["idempotency_key"])
                or not isinstance(task.get("target_key"), str) or not isinstance(task.get("payload"), dict)):
            raise ValueError("offline plan contains an invalid task")
        if task["idempotency_key"] in keys:
            raise ValueError("offline plan contains duplicate idempotency keys")
        keys.add(task["idempotency_key"])
    for disposition in result["dispositions"]:
        if (not isinstance(disposition, dict) or not isinstance(disposition.get("idempotency_key"), str)
                or len(disposition["idempotency_key"]) != 64
                or disposition.get("status") not in ALL_STATES):
            raise ValueError("offline plan contains an invalid disposition")
    summary = result["planner_summary"]
    if any(summary.get(flag) is not True for flag in ("snapshot_checked", "cached_evidence_checked")):
        raise ValueError("offline plan must record snapshot and cache checks")
    for flag in ("external_http_calls", "paid_model_calls", "paid_tokens", "paid_spend_thb", "production_writes"):
        if summary.get(flag) != 0:
            raise ValueError(f"offline plan escaped zero boundary: {flag}")
    if summary.get("retrieval_planned", 0) + summary.get("cached_replays_planned", 0) != len(result["tasks"]):
        raise ValueError("offline plan task totals do not match summary")


def _hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _retail_generation_job_key(snapshot: dict, item: dict, generation_id: str) -> str:
    """Stable identity for one model/generation lineup audit, independent of sibling generations."""
    model=next(m for m in snapshot["models"] if m["id"]==item["model_id"])
    trims=sorted((t for t in snapshot["trims"] if t.get("model_id")==item["model_id"]
                  and t.get("generation_id")==generation_id and not t.get("deleted_at")),key=lambda t:t["id"])
    owner=next((s for s in snapshot.get("current_retail_sets",[]) if s.get("model_id")==item["model_id"]),None)
    lineup_evidence=model.get("lineup_evidence")
    if not isinstance(lineup_evidence,dict) or lineup_evidence.get("generation_id")!=generation_id:
        lineup_evidence=None
    identity={"contract":"retail-generation-job-v1","model_id":model["id"],
        "model_status":model.get("status"),"generation_id":generation_id,
        "trims":[{key:t.get(key) for key in ("id","status","powertrain","variant_id","revision",
                 "admin_retired","owner_retired","model_year","facelift_id")} for t in trims],
        "owner_set":({"revision":owner.get("revision"),"trim_ids":sorted(tid for tid in owner.get("trim_ids",[])
                       if any(t["id"]==tid for t in trims))} if owner else None),
        "lineup_evidence":lineup_evidence}
    return _hash(identity)


def utc_day(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).date().isoformat()


@dataclass
class FakeClock:
    """Integer-second clock for reproducible tests and fixture replays."""
    epoch: int

    def now(self) -> int:
        return self.epoch

    def advance(self, seconds: int) -> None:
        if type(seconds) is not int or seconds < 0:
            raise ValueError("fake clock advances must be nonnegative integer seconds")
        self.epoch += seconds


class SQLiteJobStore:
    """Local durable journal. Paths must be local SQLite files or :memory:."""
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:" and "://" in self.path:
            raise ValueError("job store must be a local SQLite path")
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA busy_timeout=5000")
        if self.path != ":memory:":
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
        self._initialize()

    def _initialize(self) -> None:
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS jobs (
          idempotency_key TEXT PRIMARY KEY,
          queue TEXT NOT NULL CHECK(queue IN ('RETAIL_AUDIT','SPEC_ENRICH')),
          target_key TEXT NOT NULL,
          payload_json TEXT NOT NULL,
          priority REAL NOT NULL,
          schedule_seq INTEGER NOT NULL,
          status TEXT NOT NULL CHECK(status IN
            ('QUEUED','LEASED','RETRY_WAIT','COMPLETED','SOURCE_EXHAUSTED','BUDGET_EXHAUSTED',
             'SOURCE_BROKEN','IDENTITY_AMBIGUOUS','CONFLICT')),
          attempt_count INTEGER NOT NULL DEFAULT 0,
          max_attempts INTEGER NOT NULL,
          created_at INTEGER NOT NULL,
          updated_at INTEGER NOT NULL,
          not_before INTEGER NOT NULL,
          lease_owner TEXT,
          lease_until INTEGER,
          checkpoint_json TEXT NOT NULL DEFAULT '{}',
          failure_code TEXT,
          result_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS jobs_ready_idx
          ON jobs(status, not_before, queue, priority DESC, created_at, idempotency_key);
        CREATE TABLE IF NOT EXISTS runner_state (
          singleton INTEGER PRIMARY KEY CHECK(singleton=1),
          manual_pause INTEGER NOT NULL,
          kill_engaged INTEGER NOT NULL,
          schedule_cursor INTEGER NOT NULL DEFAULT 0,
          schedule_seq INTEGER NOT NULL DEFAULT 0
        );
        INSERT OR IGNORE INTO runner_state(singleton,manual_pause,kill_engaged,schedule_cursor,schedule_seq)
          VALUES(1,1,1,0,0);
        CREATE TABLE IF NOT EXISTS daily_usage (
          day TEXT PRIMARY KEY,
          offline_requests INTEGER NOT NULL DEFAULT 0,
          reported_tokens INTEGER NOT NULL DEFAULT 0,
          reported_spend_thb REAL NOT NULL DEFAULT 0,
          elapsed_seconds INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS negative_cache (
          target_key TEXT PRIMARY KEY,
          state TEXT NOT NULL CHECK(state IN ('SOURCE_EXHAUSTED','SOURCE_BROKEN')),
          expires_at INTEGER NOT NULL,
          source_hash TEXT,
          updated_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS evidence_cache (
          target_key TEXT NOT NULL,
          content_sha256 TEXT NOT NULL,
          result_json TEXT NOT NULL,
          recorded_at INTEGER NOT NULL,
          PRIMARY KEY(target_key, content_sha256)
        );
        CREATE TABLE IF NOT EXISTS job_contexts (
          idempotency_key TEXT PRIMARY KEY REFERENCES jobs(idempotency_key) ON DELETE CASCADE,
          snapshot_json TEXT NOT NULL,
          updated_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS planning_dispositions (
          disposition_key TEXT PRIMARY KEY,
          status TEXT NOT NULL,
          reason TEXT NOT NULL,
          detail_json TEXT NOT NULL,
          updated_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS runner_events (
          event_id INTEGER PRIMARY KEY AUTOINCREMENT,
          at INTEGER NOT NULL,
          idempotency_key TEXT,
          event_type TEXT NOT NULL,
          detail_json TEXT NOT NULL
        );
        """)

    def close(self) -> None:
        self.db.close()

    def _tx(self):
        return _Transaction(self.db)

    def controls(self) -> dict:
        row = self.db.execute("SELECT manual_pause,kill_engaged FROM runner_state WHERE singleton=1").fetchone()
        return {"manual_pause": bool(row["manual_pause"]), "kill_engaged": bool(row["kill_engaged"])}

    def set_controls(self, *, manual_pause: bool | None = None,
                     kill_engaged: bool | None = None, at: int, reason: str) -> None:
        current = self.controls()
        pause = current["manual_pause"] if manual_pause is None else bool(manual_pause)
        kill = current["kill_engaged"] if kill_engaged is None else bool(kill_engaged)
        with self._tx():
            self.db.execute("UPDATE runner_state SET manual_pause=?,kill_engaged=? WHERE singleton=1",
                            (int(pause), int(kill)))
            self.event(at, None, "CONTROL_CHANGE", {"manual_pause": pause, "kill_engaged": kill, "reason": reason})

    def event(self, at: int, key: str | None, event_type: str, detail: dict) -> None:
        self.db.execute("INSERT INTO runner_events(at,idempotency_key,event_type,detail_json) VALUES(?,?,?,?)",
                        (at, key, event_type, _json(detail)))

    def record_disposition(self, disposition: dict, *, at: int) -> None:
        with self._tx():
            self.db.execute("""INSERT INTO planning_dispositions(disposition_key,status,reason,detail_json,updated_at)
              VALUES(?,?,?,?,?) ON CONFLICT(disposition_key) DO UPDATE SET status=excluded.status,
              reason=excluded.reason,detail_json=excluded.detail_json,updated_at=excluded.updated_at""",
              (disposition["idempotency_key"],disposition["status"],disposition["reason"],_json(disposition),at))
            self.event(at, disposition["idempotency_key"], "PLANNING_DISPOSITION", disposition)

    def bind_job_snapshot(self, key: str, snapshot: dict, *, at: int) -> None:
        validate_fixture(snapshot)
        with self._tx():
            self.db.execute("""INSERT INTO job_contexts(idempotency_key,snapshot_json,updated_at)
              VALUES(?,?,?) ON CONFLICT(idempotency_key) DO UPDATE SET
              snapshot_json=excluded.snapshot_json,updated_at=excluded.updated_at""",
              (key,_json(snapshot),at))
            row=self.db.execute("SELECT * FROM jobs WHERE idempotency_key=?",(key,)).fetchone()
            if row and row["status"]=="COMPLETED":
                job=self._job_dict(row)
                payload=job["payload"]
                if isinstance(payload.get("model_id"),str) and isinstance(payload.get("field_group"),str):
                    result=json.loads(row["result_json"])
                    reason=_document_scope_error(snapshot,job,result.get("source_document"),
                                                 result.get("source_hash"))
                    if reason:
                        if result.get("source_hash"):
                            self.db.execute("DELETE FROM evidence_cache WHERE target_key=? AND content_sha256=?",
                                            (row["target_key"],result["source_hash"]))
                        self.db.execute("""UPDATE jobs SET status='QUEUED',updated_at=?,not_before=?,
                          lease_owner=NULL,lease_until=NULL,result_json='{}',
                          failure_code='LEGACY_COMPLETION_SCOPE_REJECTED' WHERE idempotency_key=?""",
                          (at,at,key))
                        self.event(at,key,"LEGACY_COMPLETION_REQUEUED",{"reason":reason})

    def job_snapshot(self, key: str) -> dict | None:
        row=self.db.execute("SELECT snapshot_json FROM job_contexts WHERE idempotency_key=?",(key,)).fetchone()
        return json.loads(row["snapshot_json"]) if row else None

    def cached_hashes(self) -> dict[str, set[str]]:
        result: dict[str, set[str]] = {}
        for row in self.db.execute("SELECT target_key,content_sha256 FROM evidence_cache ORDER BY target_key,content_sha256"):
            result.setdefault(row["target_key"], set()).add(row["content_sha256"])
        return result

    def cached_evidence(self) -> list[dict]:
        return [{**json.loads(r["result_json"]), "target_key": r["target_key"],
                 "content_sha256": r["content_sha256"]}
                for r in self.db.execute("SELECT * FROM evidence_cache ORDER BY target_key,content_sha256")]

    def negative_cache_rows(self, now: int) -> dict[str, dict]:
        return {r["target_key"]: dict(r) for r in self.db.execute(
            "SELECT * FROM negative_cache ORDER BY target_key")}

    def record_evidence(self, *, target_key: str, content_sha256: str, result: dict, at: int) -> bool:
        document = result.get("source_document") if isinstance(result,dict) else None
        if not isinstance(document,dict):
            raise ValueError("evidence cache requires a validated SourceDocument")
        from .replay import _valid_document
        _valid_document(document)
        actual = hashlib.sha256(document["content"].encode("utf-8")).hexdigest()
        if content_sha256 != actual or document.get("content_sha256") != actual:
            raise ValueError("evidence content hash must match validated SourceDocument bytes")
        with self._tx():
            cursor = self.db.execute(
                "INSERT OR IGNORE INTO evidence_cache(target_key,content_sha256,result_json,recorded_at) VALUES(?,?,?,?)",
                (target_key, content_sha256, _json(result), at))
            inserted = cursor.rowcount == 1
            self.event(at, None, "EVIDENCE_CACHED" if inserted else "UNCHANGED_DOCUMENT_HASH",
                       {"target_key": target_key, "content_sha256": content_sha256})
            return inserted

    def finish_with_evidence(self, key: str, *, owner: str, now: int, result: dict,
                             source_document: dict | None = None, content_sha256: str | None = None) -> None:
        # Completion and cache insertion share one SQLite transaction. Evidence
        # is admitted through the established replay document contract.
        if source_document is not None:
            from .replay import _valid_document
            _valid_document(source_document)
            actual = hashlib.sha256(source_document["content"].encode("utf-8")).hexdigest()
            if content_sha256 != actual or source_document["content_sha256"] != actual:
                raise ValueError("source document hash does not match validated content")
        with self._tx():
            row = self.db.execute("SELECT * FROM jobs WHERE idempotency_key=?", (key,)).fetchone()
            if not row or row["status"] != "LEASED" or row["lease_owner"] != owner or row["lease_until"] <= now:
                raise ValueError("completion rejected: lease is missing, stale, or owned by another worker")
            payload=json.loads(row["payload_json"])
            if isinstance(payload.get("model_id"),str) and isinstance(payload.get("field_group"),str):
                context=self.db.execute("SELECT snapshot_json FROM job_contexts WHERE idempotency_key=?",(key,)).fetchone()
                if not context:
                    raise ValueError("completion rejected: normalized job snapshot is missing")
                reason=_document_scope_error(json.loads(context["snapshot_json"]),self._job_dict(row),
                                             source_document,content_sha256)
                if reason:
                    raise ValueError("completion rejected: "+reason)
            if source_document is not None:
                self.db.execute("INSERT OR IGNORE INTO evidence_cache(target_key,content_sha256,result_json,recorded_at) VALUES(?,?,?,?)",
                    (row["target_key"], actual, _json({"source_document": source_document}), now))
            self.db.execute("UPDATE jobs SET status='COMPLETED',updated_at=?,not_before=?,lease_owner=NULL,lease_until=NULL,result_json=?,failure_code=NULL WHERE idempotency_key=?",
                             (now, now, _json(result), key))
            self.event(now, key, "JOB_COMPLETED", result)
            if source_document is not None:
                self.event(now, key, "EVIDENCE_CACHED", {"target_key": row["target_key"], "content_sha256": actual})

    def renew_lease(self, key: str, *, owner: str, now: int, lease_seconds: int) -> int:
        until = now + lease_seconds
        with self._tx():
            cur = self.db.execute("UPDATE jobs SET lease_until=?,updated_at=? WHERE idempotency_key=? AND status='LEASED' AND lease_owner=? AND lease_until>?",
                                  (until, now, key, owner, now))
            if cur.rowcount != 1:
                raise ValueError("lease renewal rejected: lease is missing, stale, or owned by another worker")
            self.event(now, key, "LEASE_RENEWED", {"owner": owner, "lease_until": until})
        return until

    def enqueue(self, job: dict, *, at: int, max_attempts: int) -> bool:
        if job.get("queue") not in QUEUES or job.get("status", "QUEUED") not in ALL_STATES:
            raise ValueError("invalid queue or job state")
        if not job.get("idempotency_key") or not job.get("target_key"):
            raise ValueError("jobs need stable idempotency and target keys")
        key=job["idempotency_key"]
        if len(key)!=64 or any(c not in "0123456789abcdef" for c in key):
            raise ValueError("idempotency key must be a lowercase SHA-256")
        if type(max_attempts) is not int or max_attempts < 1:
            raise ValueError("max_attempts must be a positive integer")
        if not math.isfinite(float(job.get("priority",0))):
            raise ValueError("job priority must be finite")
        payload = dict(job.get("payload", {}))
        status = job.get("status", "QUEUED")
        with self._tx():
            existing = self.db.execute("SELECT queue,target_key,payload_json FROM jobs WHERE idempotency_key=?",
                                       (job["idempotency_key"],)).fetchone()
            if existing:
                if (existing["queue"] != job["queue"] or existing["target_key"] != job["target_key"]
                        or existing["payload_json"] != _json(payload)):
                    raise ValueError("idempotency key reused for different work")
                return False
            state = self.db.execute("SELECT schedule_seq FROM runner_state WHERE singleton=1").fetchone()
            seq = int(state["schedule_seq"])
            self.db.execute("UPDATE runner_state SET schedule_seq=? WHERE singleton=1", (seq + 1,))
            self.db.execute("""
              INSERT INTO jobs(idempotency_key,queue,target_key,payload_json,priority,schedule_seq,status,
                max_attempts,created_at,updated_at,not_before,result_json)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            """, (job["idempotency_key"], job["queue"], job["target_key"], _json(payload),
                  float(job.get("priority", 0)), seq, status, max_attempts, at, at,
                  int(job.get("not_before", at)), _json(job.get("result", {}))))
            self.event(at, job["idempotency_key"], "JOB_ENQUEUED", {"queue": job["queue"], "status": status})
            return True

    def list_jobs(self) -> list[dict]:
        rows = self.db.execute("SELECT * FROM jobs ORDER BY schedule_seq,idempotency_key")
        return [self._job_dict(r) for r in rows]

    @staticmethod
    def _job_dict(row: sqlite3.Row) -> dict:
        return {
            "idempotency_key": row["idempotency_key"], "queue": row["queue"],
            "target_key": row["target_key"], "payload": json.loads(row["payload_json"]),
            "priority": row["priority"], "schedule_seq": row["schedule_seq"], "status": row["status"],
            "attempt_count": row["attempt_count"], "max_attempts": row["max_attempts"],
            "created_at": row["created_at"], "updated_at": row["updated_at"],
            "not_before": row["not_before"], "lease_owner": row["lease_owner"],
            "lease_until": row["lease_until"], "checkpoint": json.loads(row["checkpoint_json"]),
            "failure_code": row["failure_code"], "result": json.loads(row["result_json"]),
        }

    def add_negative_cache(self, target_key: str, state: str, *, expires_at: int,
                           source_hash: str | None, at: int) -> None:
        if state not in {"SOURCE_EXHAUSTED", "SOURCE_BROKEN"}:
            raise ValueError("negative cache accepts only exhausted/broken-source states")
        with self._tx():
            self.db.execute("""INSERT INTO negative_cache(target_key,state,expires_at,source_hash,updated_at)
              VALUES(?,?,?,?,?) ON CONFLICT(target_key) DO UPDATE SET state=excluded.state,
              expires_at=excluded.expires_at,source_hash=excluded.source_hash,updated_at=excluded.updated_at""",
              (target_key, state, expires_at, source_hash, at))

    def usage(self, day: str) -> dict:
        row = self.db.execute("SELECT * FROM daily_usage WHERE day=?", (day,)).fetchone()
        if not row:
            return {"day": day, "offline_requests": 0, "reported_tokens": 0,
                    "reported_spend_thb": 0.0, "elapsed_seconds": 0}
        return dict(row)

    def add_usage(self, day: str, *, requests: int, tokens: int, spend: float, elapsed: int) -> None:
        self.db.execute("""INSERT INTO daily_usage(day,offline_requests,reported_tokens,reported_spend_thb,elapsed_seconds)
          VALUES(?,?,?,?,?) ON CONFLICT(day) DO UPDATE SET
          offline_requests=offline_requests+excluded.offline_requests,
          reported_tokens=reported_tokens+excluded.reported_tokens,
          reported_spend_thb=reported_spend_thb+excluded.reported_spend_thb,
          elapsed_seconds=elapsed_seconds+excluded.elapsed_seconds""", (day, requests, tokens, spend, elapsed))

    def recover_stale_leases(self, now: int) -> int:
        with self._tx():
            return self._recover_stale_in_tx(now)

    def claim_next(self, *, now: int, owner: str, lease_seconds: int,
                   cycle_size: int, spec_slots: int,
                   audit_cycle_size: int | None = None, audit_slots: int = 0) -> dict | None:
        with self._tx():
            self._recover_stale_in_tx(now)
            ready = list(self.db.execute(
                "SELECT * FROM jobs WHERE status IN ('QUEUED','RETRY_WAIT') AND not_before<=? "
                "ORDER BY queue,priority DESC,created_at,idempotency_key", (now,)))
            if not ready:
                return None
            state = self.db.execute("SELECT schedule_cursor FROM runner_state WHERE singleton=1").fetchone()
            cursor = int(state["schedule_cursor"])
            audit_cycle_size = audit_cycle_size or cycle_size
            # Each queue has an independent service deadline. At every slot,
            # serve the guarantee with the greatest fraction of its window used.
            events = list(self.db.execute("SELECT detail_json FROM runner_events WHERE event_type='JOB_LEASED'"))
            leased = [json.loads(e["detail_json"]) for e in events]
            def urgency(queue: str, window: int, quota: int) -> float:
                if quota <= 0:
                    return 0.0
                start = cursor - cursor % window
                used = sum(1 for e in leased if e.get("schedule_cursor", -1) >= start
                           and e.get("schedule_cursor", -1) < start + window and e.get("queue") == queue)
                remaining = window - (cursor - start)
                needed = max(0, quota - used)
                return needed / max(1, remaining)
            spec_urgency = urgency("SPEC_ENRICH", cycle_size, spec_slots)
            audit_urgency = urgency("RETAIL_AUDIT", audit_cycle_size, audit_slots)
            preferred = "SPEC_ENRICH" if spec_urgency > audit_urgency and spec_urgency > 0 else "RETAIL_AUDIT"
            chosen = next((r for r in ready if r["queue"] == preferred), ready[0])
            until = now + lease_seconds
            self.db.execute("""UPDATE jobs SET status='LEASED',attempt_count=attempt_count+1,
              lease_owner=?,lease_until=?,updated_at=? WHERE idempotency_key=?""",
              (owner, until, now, chosen["idempotency_key"]))
            self.db.execute("UPDATE runner_state SET schedule_cursor=? WHERE singleton=1", (cursor + 1,))
            self.event(now, chosen["idempotency_key"], "JOB_LEASED",
                       {"owner": owner, "lease_until": until, "queue": chosen["queue"],
                        "slot": cursor % cycle_size, "schedule_cursor": cursor})
            row = self.db.execute("SELECT * FROM jobs WHERE idempotency_key=?", (chosen["idempotency_key"],)).fetchone()
            return self._job_dict(row)

    def _recover_stale_in_tx(self, now: int) -> int:
        rows = list(self.db.execute("SELECT * FROM jobs WHERE status='LEASED' AND lease_until<=? ORDER BY schedule_seq", (now,)))
        for row in rows:
            status = "SOURCE_BROKEN" if row["attempt_count"] >= row["max_attempts"] else "QUEUED"
            failure = "LEASE_EXPIRED_MAX_ATTEMPTS" if status == "SOURCE_BROKEN" else "LEASE_EXPIRED"
            self.db.execute("""UPDATE jobs SET status=?,lease_owner=NULL,lease_until=NULL,updated_at=?,
              not_before=?,failure_code=? WHERE idempotency_key=?""",
              (status, now, now, failure, row["idempotency_key"]))
            self.event(now, row["idempotency_key"], "STALE_LEASE_RECOVERED",
                       {"status": status, "attempt_count": row["attempt_count"]})
        return len(rows)

    def checkpoint(self, key: str, *, owner: str, checkpoint: dict, now: int) -> None:
        with self._tx():
            cur = self.db.execute("""UPDATE jobs SET checkpoint_json=?,updated_at=?
              WHERE idempotency_key=? AND status='LEASED' AND lease_owner=? AND lease_until>?""",
              (_json(checkpoint), now, key, owner, now))
            if cur.rowcount != 1:
                raise ValueError("checkpoint rejected: lease is missing, stale, or owned by another worker")
            self.event(now, key, "CHECKPOINT_SAVED", checkpoint)

    def finish(self, key: str, *, owner: str, status: str, now: int,
               result: dict, failure_code: str | None = None, retry_at: int | None = None) -> None:
        if status not in TERMINAL_STATES | {"RETRY_WAIT"}:
            raise ValueError("invalid completion state")
        with self._tx():
            row = self.db.execute("SELECT * FROM jobs WHERE idempotency_key=?", (key,)).fetchone()
            if not row or row["status"] != "LEASED" or row["lease_owner"] != owner or row["lease_until"] <= now:
                raise ValueError("completion rejected: lease is missing, stale, or owned by another worker")
            if status == "COMPLETED":
                payload=json.loads(row["payload_json"])
                if isinstance(payload.get("model_id"),str) and isinstance(payload.get("field_group"),str):
                    raise ValueError("scoped research completion requires finish_with_evidence")
            self.db.execute("""UPDATE jobs SET status=?,updated_at=?,not_before=?,lease_owner=NULL,lease_until=NULL,
              result_json=?,failure_code=? WHERE idempotency_key=?""",
              (status, now, retry_at if retry_at is not None else now, _json(result), failure_code, key))
            self.event(now, key, "JOB_"+status, {"failure_code": failure_code, **result})

    def report(self) -> dict:
        jobs = self.list_jobs()
        states = {state: sum(j["status"] == state for j in jobs) for state in sorted(ALL_STATES)}
        events = [{"at": r["at"], "idempotency_key": r["idempotency_key"], "event_type": r["event_type"],
                   "detail": json.loads(r["detail_json"])}
                  for r in self.db.execute("SELECT * FROM runner_events ORDER BY event_id")]
        dispositions = [json.loads(r["detail_json"]) for r in self.db.execute(
            "SELECT detail_json FROM planning_dispositions ORDER BY disposition_key")]
        usage = [dict(r) for r in self.db.execute("SELECT * FROM daily_usage ORDER BY day")]
        report = {
            "jobs": jobs, "job_counts_by_state": states, "planning_dispositions": dispositions,
            "events": events, "daily_usage": usage,
            "external_http_calls": 0, "paid_model_calls": 0, "paid_tokens": 0,
            "paid_spend_thb": 0, "production_database_accesses": 0, "production_writes": 0,
            "background_workers_started": 0, "canonical_writes": 0,
        }
        validate_runner_report(report)
        return report


class _Transaction:
    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def __enter__(self):
        self.db.execute("BEGIN IMMEDIATE")
        return self

    def __exit__(self, exc_type, exc, tb):
        self.db.execute("ROLLBACK" if exc_type else "COMMIT")
        return False


def build_offline_plan(snapshot: dict, policy: dict, *, now: int,
                       cached_documents: list[dict] | None = None,
                       known_hashes: dict[str, set[str]] | None = None,
                       negative_cache: dict[str, dict] | None = None) -> dict:
    """Check snapshot then local cached documents; only then plan retrieval."""
    validate_policy(policy)
    validate_fixture(snapshot)
    policy_revision = _hash({key: policy[key] for key in ("priority_policy", "queue_policy", "research", "runner")})
    ranked = plan(snapshot, policy)
    cached_documents = cached_documents or []
    known_hashes = known_hashes or {}
    negative_cache = negative_cache or {}
    tasks: list[dict] = []
    dispositions: list[dict] = []
    unresolved = {"GENERATION_UNRESOLVED","COMPLETE_LINEUP_HAS_UNRESOLVED_IDENTITIES",
                  "INVALID_OWNER_RETAIL_SET","OWNER_SET_CONFLICT_REVIEW_REQUIRED",
                  "SOURCE_LINEUP_STATUS_CONFLICT"}
    for decision in ranked["decisions"]:
        if unresolved.intersection(decision["reason_codes"]):
            key=_hash({"contract":"offline-disposition-v1","model_id":decision["model_id"],
                       "reason_codes":decision["reason_codes"]})
            dispositions.append({"idempotency_key":key,"target_key":"IDENTITY:"+decision["model_id"],
                "queue":"RETAIL_AUDIT","status":"IDENTITY_AMBIGUOUS","reason":"SNAPSHOT_IDENTITY_REVIEW",
                "reason_codes":decision["reason_codes"]})
        if decision["eligibility"] == "ELIGIBLE_ENRICH":
            eligible=tuple(sorted(row["trim_id"] for row in decision["trim_decisions"]
                                   if row["decision"] == "ELIGIBLE_ENRICH"))
            for finding in gaps_for_model(snapshot,eligible)["dispositions"]:
                if finding["state"] == "CONFLICT":
                    key=_hash({"contract":"offline-disposition-v1","model_id":decision["model_id"],
                               "trim_id":finding["trim_id"],"field_key":finding["field_key"],
                               "state":finding["state"]})
                    dispositions.append({"idempotency_key":key,
                        "target_key":f"SPEC_ENRICH:{decision['model_id']}:{finding['trim_id']}:{finding['field_key']}",
                        "queue":"SPEC_ENRICH","status":"CONFLICT","reason":"SNAPSHOT_FACT_CONFLICT",
                        "trim_id":finding["trim_id"],"field_key":finding["field_key"]})
    for queue in QUEUES:
        for item in ranked["queues"][queue]:
            groups = item.get("field_groups") or ["RETAIL_LINEUP"]
            scoped_items=[item]
            if queue=="RETAIL_AUDIT" and not item.get("generation_ids"):
                key=_hash({"contract":"offline-disposition-v1","model_id":item["model_id"],
                           "reason":"RETAIL_GENERATION_SCOPE_UNRESOLVED"})
                dispositions.append({"idempotency_key":key,"target_key":f"IDENTITY:{item['model_id']}",
                    "queue":"RETAIL_AUDIT","status":"IDENTITY_AMBIGUOUS",
                    "reason":"RETAIL_GENERATION_SCOPE_UNRESOLVED"})
                continue
            if queue=="RETAIL_AUDIT" and item.get("generation_ids"):
                scoped_items=[]
                for generation_id in sorted(item["generation_ids"]):
                    scoped={**item,"generation_ids":[generation_id],
                            "job_key":_retail_generation_job_key(snapshot,item,generation_id)}
                    scoped_items.append(scoped)
            for scoped_item in scoped_items:
              for group in groups:
                field_subset = scoped_item["field_plan"].get(group, {}) if queue == "SPEC_ENRICH" else {}
                generations=scoped_item.get("generation_ids",[])
                suffix=(f":{generations[0]}" if queue=="RETAIL_AUDIT" and len(generations)==1 else "")
                target_key = f"{queue}:{scoped_item['model_id']}{suffix}:{group}"
                negative = negative_cache.get(target_key)
                cooldown_epoch = int(negative["expires_at"]) if negative and int(negative["expires_at"]) <= now else 0
                key = _hash({"contract":"offline-job-v1","base_job_key":scoped_item["job_key"],
                             "group":group,"cooldown_epoch":cooldown_epoch,
                             "policy_revision":policy_revision})
                if negative and int(negative["expires_at"]) > now:
                    dispositions.append({"idempotency_key":key,"target_key":target_key,"queue":queue,
                                         "status":negative["state"],"reason":"NEGATIVE_CACHE_ACTIVE",
                                         "expires_at":negative["expires_at"]})
                    continue
                cache = next((doc for doc in sorted(cached_documents,
                    key=lambda d:(d.get("content_sha256",""),d.get("document_id","")))
                    if _cache_covers(snapshot,doc,scoped_item["model_id"],generations,group,field_subset)),None)
                if cache and cache.get("content_sha256") in known_hashes.get(target_key,set()):
                    dispositions.append({"idempotency_key":key,"target_key":target_key,"queue":queue,
                                         "status":"COMPLETED","reason":"UNCHANGED_DOCUMENT_HASH",
                                         "source_hash":cache["content_sha256"]})
                    continue
                source_action = "REPLAY_CACHED" if cache else "PLAN_RETRIEVAL"
                tasks.append({
                    "idempotency_key":key,"target_key":target_key,"queue":queue,
                    "priority":float(scoped_item["score"]),
                    "payload":{"model_id":scoped_item["model_id"],"generation_ids":generations,
                               "field_group":group,"field_plan":field_subset,
                               "planner_job_key":scoped_item["job_key"],"snapshot_checked":True,
                               "cached_evidence_checked":True,"source_action":source_action,
                               "cached_document":cache,"document_first":True,
                               "policy_revision":policy_revision},
                })
    result = {"tasks":tasks,"dispositions":dispositions,
            "planner_summary":{"snapshot_checked":True,"cached_evidence_checked":True,
                               "retrieval_planned":sum(t["payload"]["source_action"]=="PLAN_RETRIEVAL" for t in tasks),
                               "cached_replays_planned":sum(t["payload"]["source_action"]=="REPLAY_CACHED" for t in tasks),
                               "negative_cache_suppressed":sum(d["reason"]=="NEGATIVE_CACHE_ACTIVE" for d in dispositions),
                               "unchanged_hash_suppressed":sum(d["reason"]=="UNCHANGED_DOCUMENT_HASH" for d in dispositions),
                               "external_http_calls":0,"paid_model_calls":0,"paid_tokens":0,
                               "paid_spend_thb":0,"production_writes":0}}
    validate_offline_plan(result)
    return result


def _cache_covers(snapshot: dict, cache_record: dict, model_id: str, generation_ids: list[str],
                  group: str, field_subset: dict) -> bool:
    """Only replay-admitted content with exact target coverage can serve cache."""
    from .registry_adapter import load_registry, resolve_key
    from .replay import validate_cached_source_document
    document = cache_record.get("source_document") if isinstance(cache_record,dict) else None
    digest = cache_record.get("content_sha256") if isinstance(cache_record,dict) else None
    if not isinstance(document,dict) or document.get("model_id") != model_id:
        return False
    if document.get("generation_id") not in generation_ids or document.get("market") != "TH":
        return False
    if not isinstance(digest,str) or digest != document.get("content_sha256"):
        return False
    try:
        validated = validate_cached_source_document(snapshot,document)
    except Exception:
        return False
    if group == "RETAIL_LINEUP":
        # Retail completeness attestations cover one generation at a time.
        # A model-level task spanning generations cannot be satisfied by an
        # existential match against just one of them.
        if len(generation_ids) != 1:
            return False
        return validated["retail_lineup_validated"] is True
    registry=load_registry()
    required={(trim, resolve_key(field,registry) or field)
              for field, trims in field_subset.get("trim_ids_by_field",{}).items()
              for trim in trims}
    covered={(row["trim_id"],row["field_key"]) for row in validated["accepted_claims"]
             if row["model_id"] == model_id and row["generation_id"] in generation_ids}
    # Some normalized gap aliases are intentionally shorter than the pinned
    # canonical registry key (for example `aeb` -> `safety.aeb`).
    covered |= {(trim, alias) for trim, canonical in list(covered)
                for alias, target in registry["aliases"].items() if target == canonical}
    covered |= {(trim, canonical.rsplit(".",1)[-1]) for trim, canonical in list(covered)}
    return bool(required) and required.issubset(covered)


def _document_scope_error(snapshot: dict, job: dict, document: dict | None,
                          source_hash: str | None) -> str | None:
    """Validate successful evidence against the leased normalized task scope."""
    payload=job.get("payload",{})
    # Hand-built journal jobs without a normalized research scope remain useful
    # for runner mechanics tests; planner-produced retrieval tasks are strict.
    if not isinstance(payload.get("model_id"),str) or not isinstance(payload.get("field_group"),str):
        if source_hash is not None and document is None:
            return "SOURCE_HASH_WITHOUT_SOURCE_DOCUMENT"
        return None
    if not isinstance(document,dict):
        return "COMPLETED_WITHOUT_SOURCE_DOCUMENT"
    if document.get("model_id") != payload["model_id"]:
        return "EVIDENCE_MODEL_MISMATCH"
    generations=payload.get("generation_ids")
    if not isinstance(generations,list) or document.get("generation_id") not in generations:
        return "EVIDENCE_GENERATION_MISMATCH"
    try:
        from .replay import validate_cached_source_document
        validated=validate_cached_source_document(snapshot,document)
    except Exception:
        return "EVIDENCE_DOCUMENT_INVALID"
    if source_hash is None or source_hash != document.get("content_sha256"):
        return "EVIDENCE_HASH_MISMATCH"
    if payload["field_group"] == "RETAIL_LINEUP":
        # Chunk 3 lineup evidence is generation-scoped. Until the planner emits
        # one retail task per generation, fail closed for multi-generation jobs.
        if len(generations) != 1:
            return "EVIDENCE_MULTI_GENERATION_LINEUP_SCOPE_UNSUPPORTED"
        if document.get("source_kind") != "RETAIL_LINEUP" or validated.get("retail_lineup_validated") is not True:
            return "EVIDENCE_LINEUP_SCOPE_INVALID"
        return None
    field_plan=payload.get("field_plan",{})
    required={(trim,field) for field,trims in field_plan.get("trim_ids_by_field",{}).items() for trim in trims}
    if not required:
        return "EVIDENCE_REQUEST_SCOPE_EMPTY"
    from .registry_adapter import load_registry,resolve_key
    registry=load_registry()
    required={(trim,resolve_key(field,registry) or field) for trim,field in required}
    claims={(row["trim_id"],row["field_key"]) for row in validated["accepted_claims"]
            if row["model_id"]==payload["model_id"] and row["generation_id"]==document["generation_id"]}
    claims |= {(trim,alias) for trim,canonical in list(claims)
               for alias,target in registry["aliases"].items() if target==canonical}
    claims |= {(trim,canonical.rsplit(".",1)[-1]) for trim,canonical in list(claims)}
    if not required.issubset(claims):
        return "EVIDENCE_TRIM_OR_FIELD_SCOPE_INCOMPLETE"
    return None


class OfflineFakeProvider:
    """Canned in-memory responses only; intentionally exposes no transport API."""
    offline_only = True
    paid = False
    external_calls = 0

    def __init__(self, responses: dict[str, dict] | None = None, *, default: dict | None = None,
                 clock: FakeClock | None = None):
        self.responses = responses or {}
        self.default = default or {"state":"SOURCE_EXHAUSTED","reason":"NO_LOCAL_MOCK_EVIDENCE"}
        self.clock = clock
        self.calls: list[dict] = []

    def retrieve(self, job: dict, checkpoint: dict, save_checkpoint, renew_lease) -> dict:
        self.calls.append({"idempotency_key":job["idempotency_key"],"attempt":job["attempt_count"],
                           "checkpoint":checkpoint})
        scripted = self.responses.get(job["idempotency_key"],
                   self.responses.get(job["target_key"],self.default))
        if isinstance(scripted,list):
            index=min(max(0,job["attempt_count"]-1),len(scripted)-1)
            scripted=scripted[index]
        response = dict(scripted)
        if "checkpoint" in response:
            save_checkpoint(response["checkpoint"])
        elapsed = int(response.get("elapsed_seconds",0))
        if self.clock and elapsed:
            # Simulate deterministic progress and renew before the current
            # lease expires; interruption remains recoverable at checkpoints.
            lease = max(1, int(job.get("lease_until", self.clock.now()) - self.clock.now()))
            remaining = elapsed
            while remaining:
                step = min(remaining, max(1, lease // 2))
                self.clock.advance(step)
                remaining -= step
                if remaining:
                    renew_lease()
        if response.get("interrupt_after_checkpoint"):
            raise WorkerInterrupted("fixture interruption after checkpoint")
        return response


class WorkerInterrupted(RuntimeError):
    """Deterministic crash injected by a local fixture provider."""


class OfflineRunner:
    def __init__(self, store: SQLiteJobStore, policy: dict, clock: FakeClock,
                 provider: OfflineFakeProvider):
        validate_policy(policy)
        if not isinstance(provider, OfflineFakeProvider) or provider.offline_only is not True or provider.paid is not False:
            raise ValueError("offline runner accepts only OfflineFakeProvider")
        if provider.clock is not clock:
            raise ValueError("fake provider and runner must share the measured fake clock")
        self.store, self.policy, self.clock, self.provider = store, policy, clock, provider

    def enqueue_plan(self, snapshot: dict, *, cached_documents: list[dict] | None = None) -> dict:
        now = self.clock.now()
        plan_doc = build_offline_plan(snapshot,self.policy,now=now,
            cached_documents=cached_documents if cached_documents is not None else self.store.cached_evidence(),
            known_hashes=self.store.cached_hashes(),negative_cache=self.store.negative_cache_rows(now))
        max_attempts = 1 + self.policy["runner"]["maximum_retries_per_job"]
        inserted=0
        for task in plan_doc["tasks"]:
            inserted += self.store.enqueue(task,at=now,max_attempts=max_attempts)
            self.store.bind_job_snapshot(task["idempotency_key"],snapshot,at=now)
        for disposition in plan_doc["dispositions"]:
            self.store.record_disposition(disposition,at=now)
        plan_doc["enqueued_count"] = inserted
        plan_doc["deduplicated_count"] = len(plan_doc["tasks"])-inserted
        return plan_doc

    def arm_one_manual_mock_step(self) -> None:
        cfg=self.policy["runner"]
        if cfg.get("manual_mock_steps_allowed") is not True or cfg.get("background_execution") is not False:
            raise ValueError("manual MOCK step is disabled by policy")
        self.store.set_controls(manual_pause=False,kill_engaged=False,at=self.clock.now(),
                                reason="EXPLICIT_ONE_SHOT_OFFLINE_MOCK_ACK")

    def pause(self) -> None:
        self.store.set_controls(manual_pause=True,at=self.clock.now(),reason="MANUAL_PAUSE")

    def kill(self) -> None:
        self.store.set_controls(manual_pause=True,kill_engaged=True,at=self.clock.now(),reason="KILL_SWITCH")

    def run_one_manual_step(self, *, owner: str="offline-mock-worker") -> dict:
        """Execute at most one canned local response; re-engage both switches after."""
        controls=self.store.controls()
        if controls["kill_engaged"]:
            return {"status":"BLOCKED","reason":"KILL_SWITCH_ENGAGED"}
        if controls["manual_pause"]:
            return {"status":"BLOCKED","reason":"MANUAL_PAUSE"}
        try:
            return self._run_one(owner)
        finally:
            self.store.set_controls(manual_pause=True,kill_engaged=True,at=self.clock.now(),
                                    reason="ONE_SHOT_COMPLETE_FAIL_CLOSED")

    def _run_one(self, owner: str) -> dict:
        now=self.clock.now()
        self.store.recover_stale_leases(now)
        job=self._claim_with_budget(now,owner)
        if job and job.get("daily_quota_deferred"):
            return {"status":"DAILY_QUOTA_DEFERRED","reason":job["daily_quota_deferred"]}
        if job is None:
            return {"status":"IDLE","reason":"NO_READY_JOBS"}
        if job.get("budget_exhausted"):
            return {"status":"BUDGET_EXHAUSTED","reason":"DAILY_BUDGET_ALREADY_EXHAUSTED"}
        started=self.clock.now()
        try:
            response=self.provider.retrieve(
                job,job["checkpoint"],
                lambda checkpoint:self.store.checkpoint(job["idempotency_key"],owner=owner,
                                                        checkpoint=checkpoint,now=self.clock.now()),
                lambda:self.store.renew_lease(job["idempotency_key"],owner=owner,now=self.clock.now(),
                                               lease_seconds=self.policy["runner"]["lease_seconds"]))
        except WorkerInterrupted:
            elapsed=max(0,self.clock.now()-started)
            self.store.add_usage(utc_day(started),requests=1,tokens=0,spend=0,elapsed=elapsed)
            self.store.event(self.clock.now(),job["idempotency_key"],"WORKER_INTERRUPTED",
                             {"checkpoint":job["checkpoint"],"elapsed_seconds":elapsed,"offline_requests":1})
            raise
        elapsed=max(0,self.clock.now()-started)
        usage=self.store.usage(utc_day(started))
        try:
            reported_tokens=response.get("usage_tokens",0)
            reported_spend=float(response.get("usage_spend_thb",0))
            if type(reported_tokens) is not int or reported_tokens < 0 or not math.isfinite(reported_spend) or reported_spend < 0:
                raise ValueError("invalid simulated usage")
        except (TypeError,ValueError,OverflowError):
            reported_tokens=0
            reported_spend=0
            response={"state":"BUDGET_EXHAUSTED","reason":"INVALID_MEASURED_USAGE"}
        self.store.add_usage(utc_day(started),requests=1,tokens=reported_tokens,
                             spend=reported_spend,elapsed=elapsed)
        cfg=self.policy["runner"]
        if (reported_tokens > cfg["max_tokens_per_day"] or reported_spend > cfg["max_spend_thb_per_day"]
                or usage["elapsed_seconds"]+elapsed > cfg["max_elapsed_seconds_per_day"]):
            self.store.finish(job["idempotency_key"],owner=owner,status="BUDGET_EXHAUSTED",
                now=self.clock.now(),result={"reason":"MEASURED_USAGE_EXCEEDED_POLICY",
                "offline_requests":1,"reported_tokens":reported_tokens,
                "reported_spend_thb":reported_spend,"elapsed_seconds":elapsed},
                failure_code="MEASURED_USAGE_EXCEEDED_POLICY")
            return {"status":"BUDGET_EXHAUSTED","job_key":job["idempotency_key"]}
        return self._apply_response(job,owner,response,elapsed)

    def _claim_with_budget(self, now: int, owner: str) -> dict | None:
        cfg=self.policy["runner"]
        usage=self.store.usage(utc_day(now))
        if (usage["offline_requests"] >= cfg["max_offline_requests_per_day"]
                or usage["elapsed_seconds"] >= cfg["max_elapsed_seconds_per_day"]):
            reason = "DAILY_REQUEST_QUOTA" if usage["offline_requests"] >= cfg["max_offline_requests_per_day"] else "DAILY_ELAPSED_QUOTA"
            self.store.event(now,None,"DAILY_QUOTA_DEFERRED",{"reason":reason,"day":utc_day(now)})
            return {"daily_quota_deferred":reason}
        queue=self.policy["queue_policy"]
        return self.store.claim_next(now=now,owner=owner,lease_seconds=cfg["lease_seconds"],
                                    cycle_size=queue["cycle_size"],
                                    spec_slots=queue["spec_enrich_slots_per_cycle"],
                                    audit_cycle_size=queue["audit_anti_starvation_cycle_size"],
                                    audit_slots=queue["audit_anti_starvation_slots_per_cycle"])

    def _apply_response(self, job: dict, owner: str, response: dict, elapsed: int) -> dict:
        state=response.get("state")
        if state not in TERMINAL_STATES | {"RETRY"}:
            state="SOURCE_BROKEN"
            response={"state":state,"reason":"INVALID_FAKE_PROVIDER_RESPONSE"}
        now=self.clock.now()
        source_document=response.get("source_document")
        source_hash=response.get("source_hash")
        if source_hash is not None and (not isinstance(source_hash,str) or len(source_hash)!=64
                or any(c not in "0123456789abcdef" for c in source_hash)):
            state="SOURCE_BROKEN"
            response={"state":state,"reason":"INVALID_SOURCE_HASH"}
            source_document=None
        if state == "COMPLETED":
            payload=job.get("payload",{})
            if isinstance(payload.get("model_id"),str) and isinstance(payload.get("field_group"),str):
                snapshot=self.store.job_snapshot(job["idempotency_key"])
                reason=("JOB_SNAPSHOT_CONTEXT_MISSING" if snapshot is None else
                        _document_scope_error(snapshot,job,source_document,source_hash))
                if reason:
                    return self._reject_evidence_completion(job,owner,reason,elapsed)
            elif source_hash is not None and not isinstance(source_document,dict):
                state="SOURCE_BROKEN"
                response={"state":state,"reason":"SOURCE_HASH_WITHOUT_SOURCE_DOCUMENT"}
        attempts=job["attempt_count"]
        retryable=state=="RETRY" or (state=="SOURCE_BROKEN" and response.get("retryable") is True)
        if retryable and attempts < job["max_attempts"]:
            retry_at=now+self.policy["runner"]["retry_cooldown_seconds"]
            self.store.finish(job["idempotency_key"],owner=owner,status="RETRY_WAIT",now=now,
                result={**response,"elapsed_seconds":elapsed},failure_code=response.get("reason","RETRYABLE"),
                retry_at=retry_at)
            return {"status":"RETRY_WAIT","job_key":job["idempotency_key"],"retry_at":retry_at}
        final_state="SOURCE_BROKEN" if state=="RETRY" else state
        result={k:v for k,v in response.items() if k!="interrupt_after_checkpoint"}
        result["elapsed_seconds"]=elapsed
        if final_state == "COMPLETED":
            try:
                self.store.finish_with_evidence(job["idempotency_key"],owner=owner,now=now,result=result,
                    source_document=source_document,content_sha256=source_hash)
            except Exception as exc:
                self.store.finish(job["idempotency_key"],owner=owner,status="SOURCE_BROKEN",now=now,
                    result={"reason":"EVIDENCE_CACHE_COMMIT_FAILED","error_type":type(exc).__name__},
                    failure_code="EVIDENCE_CACHE_COMMIT_FAILED")
                return {"status":"SOURCE_BROKEN","job_key":job["idempotency_key"]}
        else:
            self.store.finish(job["idempotency_key"],owner=owner,status=final_state,now=now,result=result,
                              failure_code=response.get("reason"))
        if final_state in {"SOURCE_EXHAUSTED","SOURCE_BROKEN"}:
            days=self.policy["research"]["negative_cache_days"]
            self.store.add_negative_cache(job["target_key"],final_state,
                expires_at=now+int(days)*86400,source_hash=response.get("source_hash"),at=now)
        return {"status":final_state,"job_key":job["idempotency_key"]}

    def _reject_evidence_completion(self, job: dict, owner: str, reason: str, elapsed: int) -> dict:
        now=self.clock.now()
        if job["attempt_count"] < job["max_attempts"]:
            retry_at=now+self.policy["runner"]["retry_cooldown_seconds"]
            self.store.finish(job["idempotency_key"],owner=owner,status="RETRY_WAIT",now=now,
                result={"reason":reason,"elapsed_seconds":elapsed,"evidence_rejected":True},
                failure_code=reason,retry_at=retry_at)
            return {"status":"RETRY_WAIT","reason":reason,"job_key":job["idempotency_key"],"retry_at":retry_at}
        self.store.finish(job["idempotency_key"],owner=owner,status="SOURCE_BROKEN",now=now,
            result={"reason":reason,"elapsed_seconds":elapsed,"evidence_rejected":True},failure_code=reason)
        return {"status":"SOURCE_BROKEN","reason":reason,"job_key":job["idempotency_key"]}

    def report(self) -> dict:
        return self.store.report()

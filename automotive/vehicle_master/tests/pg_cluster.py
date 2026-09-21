"""A throwaway Postgres cluster, and the production schema inside it.

A migration is a claim about what Postgres will do to rows that already
exist. Whether a constraint can be dropped and re-added while violating
rows are still in the table, whether a backfill's join finds anything,
whether the whole thing is re-runnable -- Postgres answers those or
nothing does, so the migration tests start a real server and apply the
real files.

``apply_production_schema`` replays the repository's entire migration
chain in order, which is what production is: not a hand-written
approximation of it that can quietly drift from the files being tested.
"""

from __future__ import annotations

import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import time

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SUPABASE = REPO_ROOT / "supabase"

PG_BIN = next((p for p in (
    Path("/usr/lib/postgresql/16/bin"),
    Path("/usr/lib/postgresql/15/bin"),
    Path("/usr/lib/postgresql/14/bin"),
) if (p / "initdb").is_file()), None)

PG_USER = "postgres"
#: Postgres refuses to run as root, and CI here often is root. When that is
#: the case every command is dropped to the postgres account instead of the
#: test being skipped -- a migration test that silently skips is a migration
#: test that proves nothing.
AS_POSTGRES = os.geteuid() == 0


def _run_as_root(command: list[str]) -> None:
    subprocess.run(command, check=True, capture_output=True, timeout=60)


def _run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    if AS_POSTGRES:
        command = ["su", PG_USER, "-s", "/bin/sh", "-c",
                   " ".join(shlex.quote(part) for part in command)]
    return subprocess.run(command, capture_output=True, text=True, timeout=300, **kwargs)


class Cluster:
    """A throwaway Postgres cluster on a unix socket in a temp directory."""

    def __init__(self) -> None:
        # Deliberately not pytest's tmp_path: its ancestors are mode 0700 and
        # owned by the invoking user, so a server running as postgres cannot
        # traverse into them. A short /tmp path also keeps the unix socket
        # inside the 107-character limit.
        self.base = Path(tempfile.mkdtemp(prefix="tdr-pg-"))
        self.data = self.base / "pgdata"
        self.socket = self.base / "sock"
        self.socket.mkdir(parents=True, exist_ok=True)
        if AS_POSTGRES:
            _run_as_root(["chmod", "0755", str(self.base)])
            _run_as_root(["chown", "-R", f"{PG_USER}:{PG_USER}", str(self.base)])

    def start(self) -> None:
        result = _run([str(PG_BIN / "initdb"), "-D", str(self.data), "-A", "trust",
                       "-U", PG_USER, "--no-sync"])
        assert result.returncode == 0, result.stderr
        # -l matters: without it the daemonized server inherits this process's
        # captured stdout/stderr pipes and the read never sees EOF, so the
        # test hangs instead of running.
        result = _run([str(PG_BIN / "pg_ctl"), "-D", str(self.data), "-w",
                       "-l", str(self.base / "server.log"), "-o",
                       f"-k {self.socket} -h '' -c fsync=off", "start"])
        assert result.returncode == 0, result.stdout + result.stderr
        for _ in range(50):
            if _run([str(PG_BIN / "pg_isready"), "-h", str(self.socket)]).returncode == 0:
                break
            time.sleep(0.2)
        # The roles Supabase provides and the migrations grant/revoke against.
        for role in ("anon", "authenticated", "service_role"):
            self.sql(f"create role {role};")

    def stop(self) -> None:
        _run([str(PG_BIN / "pg_ctl"), "-D", str(self.data), "-m", "immediate", "stop"])
        shutil.rmtree(self.base, ignore_errors=True)

    def _psql(self, args: list[str], sql: str | None = None) -> subprocess.CompletedProcess:
        return _run([str(PG_BIN / "psql"), "-h", str(self.socket), "-U", PG_USER,
                     "-d", "postgres", "-q", "-v", "ON_ERROR_STOP=1", *args], input=sql)

    def sql(self, statement: str) -> str:
        result = self._psql([], statement)
        assert result.returncode == 0, f"{statement}\n{result.stderr}"
        return result.stdout

    def try_sql(self, statement: str) -> tuple[bool, str]:
        result = self._psql([], statement)
        return result.returncode == 0, result.stderr

    def file(self, path: Path) -> None:
        # Piped rather than psql -f: the repo checkout is not necessarily
        # readable by the postgres account this may be running as.
        result = self._psql([], path.read_text(encoding="utf-8"))
        assert result.returncode == 0, f"{path.name}\n{result.stderr}"

    def rows(self, query: str) -> list[list[str]]:
        result = self._psql(["-t", "-A", "-F", "\x1f"], query)
        assert result.returncode == 0, f"{query}\n{result.stderr}"
        return [line.split("\x1f") for line in result.stdout.strip().splitlines() if line]

    def scalar(self, query: str) -> str:
        rows = self.rows(query)
        return rows[0][0] if rows else ""


#: What the Supabase platform provides and the migrations are written
#: against. Only what they actually touch: enough for the real files to
#: apply unedited, and no invented behaviour of our own.
PLATFORM_STUBS = """
create schema if not exists auth;
create schema if not exists extensions;
create schema if not exists storage;
create table if not exists auth.users (
  id uuid primary key default gen_random_uuid(),
  email text, phone text,
  phone_confirmed_at timestamptz, email_confirmed_at timestamptz,
  confirmed_at timestamptz, last_sign_in_at timestamptz,
  banned_until timestamptz, deleted_at timestamptz,
  is_anonymous boolean default false,
  raw_user_meta_data jsonb default '{}'::jsonb,
  raw_app_meta_data jsonb default '{}'::jsonb,
  created_at timestamptz default now(), updated_at timestamptz default now());
create or replace function auth.uid() returns uuid language sql stable
  as $$ select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
create or replace function auth.role() returns text language sql stable
  as $$ select coalesce(nullif(current_setting('request.jwt.claim.role', true), ''), 'anon') $$;
create or replace function auth.jwt() returns jsonb language sql stable
  as $$ select coalesce(nullif(current_setting('request.jwt.claims', true), '')::jsonb, '{}'::jsonb) $$;
create table if not exists storage.buckets (
  id text primary key, name text not null, public boolean default false,
  file_size_limit bigint, allowed_mime_types text[], owner uuid,
  created_at timestamptz default now(), updated_at timestamptz default now());
create table if not exists storage.objects (
  id uuid primary key default gen_random_uuid(),
  bucket_id text references storage.buckets(id),
  name text, owner uuid, metadata jsonb, created_at timestamptz default now());
grant usage on schema auth, storage to anon, authenticated, service_role;
"""


def migration_files(*, through: int | None = None) -> list[Path]:
    """The base schema and every migration, in the order production ran them."""
    files = sorted(
        (p for p in SUPABASE.glob("migration_v*.sql") if not p.stem.endswith("_verify")),
        key=lambda p: (int(p.name.split("_")[1][1:]), p.name))
    if through is not None:
        files = [p for p in files if int(p.name.split("_")[1][1:]) <= through]
    return [SUPABASE / "schema.sql", *files]


def apply_production_schema(cluster: Cluster, *, through: int | None = None) -> None:
    cluster.sql(PLATFORM_STUBS)
    for path in migration_files(through=through):
        cluster.file(path)


@pytest.fixture
def pg():
    if PG_BIN is None:
        pytest.skip("no local Postgres server binaries to run a real migration test")
    if AS_POSTGRES and shutil.which("su") is None:
        pytest.skip("Postgres refuses to run as root and su is unavailable to drop privileges")
    cluster = Cluster()
    try:
        cluster.start()
    except AssertionError as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"could not start a local Postgres cluster: {exc}")
    try:
        yield cluster
    finally:
        cluster.stop()

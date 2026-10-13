#!/usr/bin/env bash
set +e
log_file="docs/vehicle-db/drafts/phase1c/postgres_acceptance_stdout.log"
node --experimental-strip-types scripts/phase1c-postgres-acceptance.ts 2>&1 | tee "$log_file"
runner_status=${PIPESTATUS[0]}
printf 'runner_exit_code=%s\n' "$runner_status" | tee -a "$log_file"
exit "$runner_status"

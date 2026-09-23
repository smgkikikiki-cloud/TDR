-- publish_vehicle_release(jsonb) had no function-level statement_timeout,
-- so its execution was constrained by whatever the calling role's own
-- session default happened to be -- the authenticator role's 8s, well
-- under what a release this size (tens of thousands of spec facts and
-- price records, each its own set-based INSERT ... SELECT FROM
-- jsonb_array_elements()) takes to project, so the September 2026 ECO
-- Sticker bulk import's publish was cancelled mid-transaction with
-- Postgres error 57014 on every attempt. The transaction rolled back
-- cleanly each time -- the previous release stayed ACTIVE -- but nothing
-- ever activated the new one.
--
-- A function-level override is scoped to exactly this one RPC: it does
-- not touch the authenticator or service_role session defaults, and
-- every other function in the schema keeps whatever timeout its own
-- caller's session already had. 45s is comfortably above what this
-- release size has been observed to need and comfortably under the
-- request timeout on the HTTP path that calls it.
alter function public.publish_vehicle_release(jsonb)
  set statement_timeout = '45s';

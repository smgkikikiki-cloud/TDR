-- Vehicle DB v3 Phase 1C BASIC identity schema.
-- UNNUMBERED / NONDEPLOYABLE. The first DO block permits execution only in the
-- disposable local PostgreSQL created by the Phase 1C acceptance runner. This
-- is not a production migration and has no allocated v-number.
DO $$
BEGIN
  IF current_database() <> 'phase1c_acceptance'
     OR to_regclass('public.phase1c_local_guard') IS NULL
     OR NOT EXISTS (SELECT 1 FROM public.phase1c_local_guard
                     WHERE only_disposable_local AND database_name = current_database()) THEN
    RAISE EXCEPTION 'PHASE1C_DDL_DISPOSABLE_DATABASE_ONLY';
  END IF;
  IF to_regclass('public.vehicle_models') IS NULL
     OR to_regclass('public.vehicle_brands') IS NULL
     OR to_regclass('public.vehicle_master_state') IS NULL
     OR to_regprocedure('public.vehicle_serving_parity_check()') IS NULL
     OR to_regprocedure('public.vehicle_engine_rules_check()') IS NULL THEN
    RAISE EXCEPTION 'PHASE1C_REQUIRED_V57_V59_SCHEMA_MISSING';
  END IF;
  IF EXISTS (SELECT 1 FROM public.vehicle_serving_parity_check() WHERE NOT ok)
     OR EXISTS (SELECT 1 FROM public.vehicle_engine_rules_check()) THEN
    RAISE EXCEPTION 'PHASE1C_CATALOG_BASELINE_NOT_VALID';
  END IF;
END $$;

BEGIN;

CREATE ROLE vm_structural_rpc_owner NOLOGIN NOINHERIT;
CREATE ROLE vm_structural_approver NOLOGIN NOINHERIT;
CREATE ROLE vm_structural_approval_admin NOLOGIN NOINHERIT;

CREATE SCHEMA vehicle_private AUTHORIZATION vm_structural_rpc_owner;
REVOKE ALL ON SCHEMA vehicle_private FROM PUBLIC, anon, authenticated, service_role;
GRANT USAGE ON SCHEMA vehicle_private TO vm_structural_approver, vm_structural_approval_admin;
CREATE OR REPLACE FUNCTION vehicle_private.vm_basic_evidence_valid(p jsonb)
RETURNS boolean LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE
SET search_path=pg_catalog,vehicle_private AS $$
DECLARE e jsonb; r jsonb;
BEGIN
  e := p->'identity_evidence';
  IF jsonb_typeof(e) IS DISTINCT FROM 'object'
     OR (e-'granularity'-'model_name'-'references') <> '{}'::jsonb
     OR e->>'granularity' NOT IN ('MODEL','MODEL_REGISTRATION_CLASS')
     OR nullif(btrim(e->>'model_name'),'') IS NULL
     OR jsonb_typeof(e->'references') IS DISTINCT FROM 'array'
     OR jsonb_array_length(e->'references') = 0 THEN RETURN false; END IF;
  FOR r IN SELECT value FROM jsonb_array_elements(e->'references') LOOP
    IF jsonb_typeof(r) IS DISTINCT FROM 'string' OR btrim(r#>>'{}')='' THEN RETURN false; END IF;
  END LOOP;
  RETURN true;
END $$;

-- CATALOG stays the default for every v57 row. BASIC may omit only the facts
-- whose absence is actually unknown: lifecycle/status, generation, serving
-- pin and TDR Segment/Body Type. Ice classifications stay observation-only.
ALTER TABLE public.vehicle_brands
  ADD COLUMN identity_level text NOT NULL DEFAULT 'CATALOG'
    CHECK (identity_level IN ('CATALOG','BASIC')),
  ADD COLUMN identity_aliases jsonb NOT NULL DEFAULT '[]'::jsonb
    CHECK (jsonb_typeof(identity_aliases) = 'array'),
  ALTER COLUMN served_as_of DROP NOT NULL,
  ALTER COLUMN seed_release_id DROP NOT NULL;
UPDATE public.vehicle_brands
   SET identity_aliases = CASE WHEN jsonb_typeof(payload->'aliases') = 'array'
                               THEN payload->'aliases' ELSE '[]'::jsonb END;
SET CONSTRAINTS ALL IMMEDIATE;
ALTER TABLE public.vehicle_brands
  ADD CONSTRAINT vm_phase1c_brand_identity_level CHECK (
    (identity_level = 'CATALOG' AND served_as_of IS NOT NULL AND seed_release_id IS NOT NULL)
    OR (identity_level = 'BASIC' AND served_as_of IS NULL AND seed_release_id IS NULL
        AND payload->>'identity_level' = 'BASIC' AND payload->'incomplete' = 'true'::jsonb
        AND identity_aliases = coalesce(payload->'aliases','[]'::jsonb))
  );

ALTER TABLE public.vehicle_models
  ADD COLUMN identity_level text NOT NULL DEFAULT 'CATALOG'
    CHECK (identity_level IN ('CATALOG','BASIC')),
  ADD COLUMN identity_aliases jsonb NOT NULL DEFAULT '[]'::jsonb
    CHECK (jsonb_typeof(identity_aliases) = 'array'),
  ALTER COLUMN status DROP NOT NULL,
  ALTER COLUMN served_as_of DROP NOT NULL,
  ALTER COLUMN seed_release_id DROP NOT NULL;
UPDATE public.vehicle_models
   SET identity_aliases = CASE WHEN jsonb_typeof(payload->'aliases') = 'array'
                               THEN payload->'aliases' ELSE '[]'::jsonb END;
SET CONSTRAINTS ALL IMMEDIATE;
ALTER TABLE public.vehicle_models
  DROP CONSTRAINT vm_rule_model_validate,
  ADD CONSTRAINT vm_rule_model_validate CHECK (
    (identity_level = 'CATALOG' AND status IS NOT NULL AND served_as_of IS NOT NULL
      AND seed_release_id IS NOT NULL AND public._vm_model_problems(payload) = '{}')
    OR (identity_level = 'BASIC'
      AND status IS NULL AND generation_id IS NULL AND segment IS NULL AND body_type IS NULL
      AND retail_price_min IS NULL AND retail_price_max IS NULL
      AND served_as_of IS NULL AND seed_release_id IS NULL AND tdr_model_id IS NULL
      AND payload->>'identity_level' = 'BASIC' AND payload->'incomplete' = 'true'::jsonb
      AND payload->>'id' = canonical_id AND payload->>'brand_id' = brand_id
      AND payload->>'name_en' = name_en AND payload->'body_type' = 'null'::jsonb
      AND payload->'segment' = 'null'::jsonb AND payload->'cab_type' = 'null'::jsonb
      AND identity_aliases = coalesce(payload->'aliases','[]'::jsonb)
      AND jsonb_typeof(identity_aliases) = 'array'
      AND vehicle_private.vm_basic_evidence_valid(payload)
    )
  ),
  ADD CONSTRAINT vm_phase1c_model_identity_level CHECK (
    (identity_level = 'CATALOG' AND served_as_of IS NOT NULL AND seed_release_id IS NOT NULL)
    OR (identity_level = 'BASIC' AND status IS NULL AND generation_id IS NULL
        AND segment IS NULL AND body_type IS NULL AND retail_price_min IS NULL AND retail_price_max IS NULL
        AND served_as_of IS NULL AND seed_release_id IS NULL)
  );

-- The original one-row CATALOG check remains exact; this additional check
-- keeps canonical ID, Brand FK and name equality for BASIC rows too.
ALTER TABLE public.vehicle_models
  ADD CONSTRAINT vm_phase1c_basic_identity_payload CHECK (
    identity_level = 'CATALOG'
    OR (public._vm_child_id(canonical_id, brand_id, '.')
        AND btrim(name_en) <> '' AND payload->>'id' = canonical_id
        AND payload->>'brand_id' = brand_id AND payload->>'name_en' = name_en)
  );

CREATE OR REPLACE FUNCTION vehicle_private.vm_identity_normalize(p_value text, p_brand text DEFAULT '')
RETURNS text LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE
SET search_path = pg_catalog, vehicle_private AS $$
DECLARE v text := lower(normalize(btrim(coalesce(p_value,'')), NFKC));
        b text := lower(normalize(btrim(coalesce(p_brand,'')), NFKC));
BEGIN
  IF b <> '' AND (left(v, length(b) + 1) = b || ' ' OR left(v, length(b) + 1) = b || ':') THEN
    v := substr(v, length(b) + 1);
  END IF;
  RETURN regexp_replace(v, '[^[:alnum:]]+', '', 'g');
END $$;

CREATE TABLE vehicle_private.vm_identity_tokens (
  entity_type text NOT NULL CHECK (entity_type IN ('BRAND','MODEL')),
  brand_id text NOT NULL DEFAULT '',
  canonical_id text NOT NULL,
  normalized_token text NOT NULL CHECK (normalized_token <> ''),
  source_kind text NOT NULL CHECK (source_kind IN ('MASTER_BACKFILL','LOCAL_READONLY_SNAPSHOT')),
  source_snapshot_sha256 text,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(entity_type, canonical_id, normalized_token)
);
CREATE INDEX vm_identity_tokens_lookup_idx
  ON vehicle_private.vm_identity_tokens(entity_type, brand_id, normalized_token);

-- An immutable snapshot of owner-supplied alias-equivalence approvals. Raw Ice
-- evidence is never inserted here and cannot authorize classification/aliases.
CREATE TABLE vehicle_private.vm_approved_alias_equivalences (
  model_id text NOT NULL,
  normalized_alias text NOT NULL,
  source_ref text NOT NULL CHECK (btrim(source_ref) <> ''),
  approved_by text NOT NULL,
  approved_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(model_id, normalized_alias)
);

CREATE TABLE vehicle_private.vm_structural_approvals (
  approval_ref text PRIMARY KEY,
  batch_hash text NOT NULL CHECK (batch_hash ~ '^[0-9a-f]{64}$'),
  approved_actor text NOT NULL,
  operations text[] NOT NULL CHECK (cardinality(operations) > 0),
  expires_at timestamptz NOT NULL,
  issued_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE vehicle_private.vm_structural_capabilities (
  token_sha256 bytea PRIMARY KEY,
  approval_ref text NOT NULL UNIQUE REFERENCES vehicle_private.vm_structural_approvals(approval_ref),
  batch_hash text NOT NULL CHECK (batch_hash ~ '^[0-9a-f]{64}$'),
  principal text NOT NULL,
  operations text[] NOT NULL,
  expires_at timestamptz NOT NULL,
  consumed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE vehicle_private.vm_structural_observations (
  observation_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  actor text NOT NULL,
  actor_kind text NOT NULL CHECK (actor_kind = 'ADMIN'),
  batch_id text NOT NULL,
  source_ref text NOT NULL,
  observed_at timestamptz NOT NULL,
  source_hash text NOT NULL CHECK (source_hash ~ '^[0-9a-f]{64}$'),
  batch_hash text NOT NULL CHECK (batch_hash ~ '^[0-9a-f]{64}$'),
  raw_evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
  complete_request jsonb NOT NULL CHECK (jsonb_typeof(complete_request) = 'object'),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(actor,batch_id)
);
CREATE TABLE vehicle_private.vm_structural_revisions (
  revision_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  batch_id text NOT NULL,
  actor text NOT NULL,
  entity_type text NOT NULL CHECK (entity_type IN ('vehicle_brands','vehicle_models')),
  entity_id text NOT NULL,
  operation text NOT NULL CHECK (operation IN ('CREATE_BRAND','CREATE_MODEL_BASIC','UPDATE_MODEL_ALIAS','REVERT')),
  before_revision integer,
  after_revision integer NOT NULL CHECK (after_revision > 0),
  before_state jsonb,
  after_state jsonb NOT NULL CHECK (jsonb_typeof(after_state) = 'object'),
  source_ref text NOT NULL,
  reason text NOT NULL,
  source_hash text NOT NULL CHECK (source_hash ~ '^[0-9a-f]{64}$'),
  reverts_revision_id uuid REFERENCES vehicle_private.vm_structural_revisions(revision_id),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX vm_structural_revisions_target_idx
  ON vehicle_private.vm_structural_revisions(entity_type,entity_id,created_at DESC);
CREATE UNIQUE INDEX vm_structural_revisions_revert_once_idx
  ON vehicle_private.vm_structural_revisions(reverts_revision_id) WHERE reverts_revision_id IS NOT NULL;
CREATE TABLE vehicle_private.vm_structural_receipts (
  actor text NOT NULL,
  batch_id text NOT NULL,
  batch_hash text NOT NULL CHECK (batch_hash ~ '^[0-9a-f]{64}$'),
  payload_hash text NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
  result jsonb NOT NULL CHECK (jsonb_typeof(result) = 'object'),
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(actor,batch_id)
);

-- Append-only evidence and revisions. Receipts cannot be rewritten either.
CREATE OR REPLACE FUNCTION vehicle_private.vm_reject_audit_mutation()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, vehicle_private AS $$
BEGIN RAISE EXCEPTION USING ERRCODE='55000', MESSAGE='STRUCTURAL_AUDIT_APPEND_ONLY'; END $$;
CREATE TRIGGER vm_structural_observations_immutable BEFORE UPDATE OR DELETE
  ON vehicle_private.vm_structural_observations FOR EACH ROW EXECUTE FUNCTION vehicle_private.vm_reject_audit_mutation();
CREATE TRIGGER vm_structural_revisions_immutable BEFORE UPDATE OR DELETE
  ON vehicle_private.vm_structural_revisions FOR EACH ROW EXECUTE FUNCTION vehicle_private.vm_reject_audit_mutation();
CREATE TRIGGER vm_structural_receipts_immutable BEFORE UPDATE OR DELETE
  ON vehicle_private.vm_structural_receipts FOR EACH ROW EXECUTE FUNCTION vehicle_private.vm_reject_audit_mutation();

-- Seed normalized collision rows from the actual catalog loaded into v57.
INSERT INTO vehicle_private.vm_identity_tokens(entity_type,brand_id,canonical_id,normalized_token,source_kind)
SELECT 'BRAND','',b.canonical_id,t.token,'MASTER_BACKFILL'
  FROM public.vehicle_brands b
 CROSS JOIN LATERAL (VALUES
   (vehicle_private.vm_identity_normalize(b.name_en,'')),
   (vehicle_private.vm_identity_normalize(b.name_th,''))
 ) t(token)
 WHERE b.identity_level='CATALOG' AND t.token <> ''
ON CONFLICT DO NOTHING;
INSERT INTO vehicle_private.vm_identity_tokens(entity_type,brand_id,canonical_id,normalized_token,source_kind)
SELECT 'MODEL',m.brand_id,m.canonical_id,t.token,'MASTER_BACKFILL'
  FROM public.vehicle_models m
  JOIN public.vehicle_brands b ON b.canonical_id=m.brand_id
 CROSS JOIN LATERAL (
   SELECT vehicle_private.vm_identity_normalize(m.name_en,b.name_en) AS token
   UNION ALL SELECT vehicle_private.vm_identity_normalize(m.name_th,b.name_en)
   UNION ALL SELECT vehicle_private.vm_identity_normalize(a.value #>> '{}',b.name_en)
     FROM jsonb_array_elements(m.identity_aliases) a(value)
 ) t
 WHERE m.identity_level='CATALOG' AND t.token <> ''
ON CONFLICT DO NOTHING;

-- A real Vehicle Master may contain intentionally shared display names (for
-- example pickup parent/child aliases). Duplicates remain in this index so a
-- new identity can fail closed on any colliding canonical owner.

-- Keep public CATALOG serving exact; BASIC identities have a separate private
-- lookup and can never enter retail, trim, price, generation or spec views.
CREATE OR REPLACE VIEW public.current_vehicle_brands WITH (security_invoker=true) AS
SELECT st.seed_release_id AS release_id,m.canonical_id,m.tdr_brand_id,m.slug,m.name_en,m.name_th,m.origin_country,m.payload
  FROM public.vehicle_brands m JOIN public.vehicle_master_state st ON st.scope='vehicle_master'
 WHERE m.deleted_at IS NULL AND m.identity_level='CATALOG';
CREATE OR REPLACE VIEW public.current_vehicle_models WITH (security_invoker=true) AS
SELECT st.seed_release_id AS release_id,m.canonical_id,m.tdr_model_id,m.brand_id,m.slug,m.name_en,m.name_th,m.generation_id,
       m.status,m.segment,m.body_type,m.retail_price_min,m.retail_price_max,m.payload
  FROM public.vehicle_models m JOIN public.vehicle_master_state st ON st.scope='vehicle_master'
 WHERE m.deleted_at IS NULL AND m.identity_level='CATALOG';
DROP POLICY IF EXISTS "public read served brands" ON public.vehicle_brands;
CREATE POLICY "public read served brands" ON public.vehicle_brands FOR SELECT TO anon,authenticated
  USING (deleted_at IS NULL AND identity_level='CATALOG');
DROP POLICY IF EXISTS "public read served models" ON public.vehicle_models;
CREATE POLICY "public read served models" ON public.vehicle_models FOR SELECT TO anon,authenticated
  USING (deleted_at IS NULL AND identity_level='CATALOG');

CREATE VIEW vehicle_private.market_analysis_basic_identities AS
SELECT m.canonical_id,m.brand_id,b.name_en AS brand_name,m.name_en,m.identity_aliases AS aliases,
       m.payload->'identity_evidence' AS identity_evidence
  FROM public.vehicle_models m JOIN public.vehicle_brands b ON b.canonical_id=m.brand_id
 WHERE m.identity_level='BASIC' AND m.deleted_at IS NULL;
REVOKE ALL ON vehicle_private.market_analysis_basic_identities FROM PUBLIC,anon,authenticated,service_role;

-- v57 release parity and v59 catalog rule reports continue to concern only the
-- exact seeded CATALOG universe. New BASIC rows are intentionally outside it.
ALTER FUNCTION public.vehicle_master_seed_check() RENAME TO vehicle_master_seed_check_v57_catalog;
CREATE FUNCTION public.vehicle_master_seed_check()
RETURNS TABLE(kind text,section text,check_name text,expected bigint,actual bigint,ok boolean)
LANGUAGE sql STABLE SET search_path=public,vehicle_private,pg_temp AS $$
  SELECT r.kind,r.section,r.check_name,r.expected,
         CASE
           WHEN r.kind='release' AND r.section='brands' AND r.check_name IN ('row_count','ids_not_in_release')
             THEN r.actual-(SELECT count(*) FROM public.vehicle_brands WHERE identity_level='BASIC')
           WHEN r.kind='release' AND r.section='models' AND r.check_name IN ('row_count','ids_not_in_release')
             THEN r.actual-(SELECT count(*) FROM public.vehicle_models WHERE identity_level='BASIC')
           ELSE r.actual END AS actual,
         CASE
           WHEN r.kind='release' AND r.section='brands' AND r.check_name IN ('row_count','ids_not_in_release')
             THEN r.actual-(SELECT count(*) FROM public.vehicle_brands WHERE identity_level='BASIC')=r.expected
           WHEN r.kind='release' AND r.section='models' AND r.check_name IN ('row_count','ids_not_in_release')
             THEN r.actual-(SELECT count(*) FROM public.vehicle_models WHERE identity_level='BASIC')=r.expected
           ELSE r.ok END AS ok
    FROM public.vehicle_master_seed_check_v57_catalog() r
$$;
GRANT EXECUTE ON FUNCTION public.vehicle_master_seed_check() TO service_role;

CREATE OR REPLACE FUNCTION public._vm_check_structure()
RETURNS trigger LANGUAGE plpgsql SET search_path=public,vehicle_private,pg_temp AS $$
DECLARE col text; k text; keys text[] := '{}'; p record;
BEGIN
  FOREACH col IN ARRAY TG_ARGV LOOP
    IF TG_OP <> 'DELETE' THEN k := to_jsonb(NEW)->>col; IF k IS NOT NULL THEN keys:=keys||k; END IF; END IF;
    IF TG_OP <> 'INSERT' THEN k := to_jsonb(OLD)->>col; IF k IS NOT NULL THEN keys:=keys||k; END IF; END IF;
  END LOOP;
  IF TG_TABLE_NAME='vehicle_current_retail_sets' AND TG_OP<>'DELETE' THEN keys:=keys||NEW.trim_ids; END IF;
  FOREACH k IN ARRAY keys LOOP
    FOR p IN SELECT * FROM public._vm_structure_problems(k) LOOP
      IF p.rule IN ('model_has_generation','model_has_variant')
         AND EXISTS (SELECT 1 FROM public.vehicle_models m WHERE m.canonical_id=p.key AND m.identity_level='BASIC') THEN
        CONTINUE;
      END IF;
      RAISE EXCEPTION USING ERRCODE='P0001',MESSAGE=format('engine rule %s violated for %s: %s',p.rule,p.key,p.detail);
    END LOOP;
  END LOOP;
  RETURN NULL;
END $$;
ALTER FUNCTION public._vm_check_structure() OWNER TO vm_structural_rpc_owner;
ALTER FUNCTION public._vm_check_structure() SECURITY DEFINER;
CREATE OR REPLACE FUNCTION public.vehicle_engine_rules_check()
RETURNS TABLE(rule text,key text,detail text)
LANGUAGE sql STABLE SET search_path=public,vehicle_private,pg_temp AS $$
  SELECT p.rule,p.key,p.detail FROM public._vm_structure_problems(NULL) p
   WHERE NOT (p.rule IN ('model_has_generation','model_has_variant')
     AND EXISTS (SELECT 1 FROM public.vehicle_models m WHERE m.canonical_id=p.key AND m.identity_level='BASIC'))
$$;
GRANT EXECUTE ON FUNCTION public.vehicle_engine_rules_check() TO service_role;

-- BASIC may never acquire catalog generations/trims/specs/prices by an
-- unrelated direct insert. The future RPC can create only identities/aliases.
CREATE OR REPLACE FUNCTION vehicle_private.vm_require_catalog_parent()
RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog,public,vehicle_private,pg_temp AS $$
DECLARE mid text;
BEGIN
  mid := CASE WHEN TG_TABLE_NAME='vehicle_generations' THEN NEW.model_id ELSE NEW.model_id END;
  IF EXISTS (SELECT 1 FROM public.vehicle_models m WHERE m.canonical_id=mid AND m.identity_level='BASIC') THEN
    RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='BASIC_IDENTITY_CANNOT_HAVE_CATALOG_CHILDREN';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER vm_phase1c_generation_catalog_parent BEFORE INSERT OR UPDATE ON public.vehicle_generations
  FOR EACH ROW EXECUTE FUNCTION vehicle_private.vm_require_catalog_parent();
CREATE TRIGGER vm_phase1c_variant_catalog_parent BEFORE INSERT OR UPDATE ON public.vehicle_variants
  FOR EACH ROW EXECUTE FUNCTION vehicle_private.vm_require_catalog_parent();
CREATE TRIGGER vm_phase1c_trim_catalog_parent BEFORE INSERT OR UPDATE ON public.vehicle_trims
  FOR EACH ROW EXECUTE FUNCTION vehicle_private.vm_require_catalog_parent();

-- Private functions/tables are executable only by the non-login RPC owner.
GRANT SELECT,INSERT,UPDATE ON public.vehicle_brands,public.vehicle_models TO vm_structural_rpc_owner;
GRANT SELECT ON public.vehicle_generations,public.vehicle_variants,public.vehicle_trims,
  public.vehicle_current_retail_sets,public.vehicle_trim_lifecycle_decisions,public.vehicle_price_ledger,
  public.vehicle_facts,public.vehicle_master_state,public.canonical_vehicle_state,public.ice_model_crosswalk,
  public.vehicle_campaigns,public.vehicle_promotions,public.vehicle_eco_evidence,public.vehicle_model_operational_states TO vm_structural_rpc_owner;
GRANT EXECUTE ON FUNCTION public._vm_child_id(text,text,text),public._vm_slug_segment(text),
  public._vm_model_problems(jsonb),public._vm_structure_problems(text),public._vm_truthy(jsonb),public._vm_variant_problems(jsonb),
  public._vm_none(jsonb),public._vm_num(jsonb) TO vm_structural_rpc_owner;
GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA vehicle_private TO vm_structural_rpc_owner;
GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA vehicle_private TO vm_structural_rpc_owner;
CREATE POLICY vm_phase1c_rpc_brand_access ON public.vehicle_brands TO vm_structural_rpc_owner
  USING (true) WITH CHECK (true);
CREATE POLICY vm_phase1c_rpc_model_access ON public.vehicle_models TO vm_structural_rpc_owner
  USING (true) WITH CHECK (true);
CREATE POLICY vm_phase1c_rpc_generation_read ON public.vehicle_generations FOR SELECT TO vm_structural_rpc_owner USING (true);
CREATE POLICY vm_phase1c_rpc_variant_read ON public.vehicle_variants FOR SELECT TO vm_structural_rpc_owner USING (true);
CREATE POLICY vm_phase1c_rpc_trim_read ON public.vehicle_trims FOR SELECT TO vm_structural_rpc_owner USING (true);
CREATE POLICY vm_phase1c_rpc_retail_set_read ON public.vehicle_current_retail_sets FOR SELECT TO vm_structural_rpc_owner USING (true);
CREATE POLICY vm_phase1c_rpc_lifecycle_read ON public.vehicle_trim_lifecycle_decisions FOR SELECT TO vm_structural_rpc_owner USING (true);
CREATE POLICY vm_phase1c_rpc_price_read ON public.vehicle_price_ledger FOR SELECT TO vm_structural_rpc_owner USING (true);
CREATE POLICY vm_phase1c_rpc_fact_read ON public.vehicle_facts FOR SELECT TO vm_structural_rpc_owner USING (true);
CREATE POLICY vm_phase1c_rpc_master_state_read ON public.vehicle_master_state FOR SELECT TO vm_structural_rpc_owner USING (true);
CREATE POLICY vm_phase1c_rpc_release_state_read ON public.canonical_vehicle_state FOR SELECT TO vm_structural_rpc_owner USING (true);
CREATE POLICY vm_phase1c_rpc_legacy_ice_read ON public.ice_model_crosswalk FOR SELECT TO vm_structural_rpc_owner USING (true);
CREATE POLICY vm_phase1c_rpc_campaign_read ON public.vehicle_campaigns FOR SELECT TO vm_structural_rpc_owner USING (true);
CREATE POLICY vm_phase1c_rpc_promotion_read ON public.vehicle_promotions FOR SELECT TO vm_structural_rpc_owner USING (true);
CREATE POLICY vm_phase1c_rpc_eco_read ON public.vehicle_eco_evidence FOR SELECT TO vm_structural_rpc_owner USING (true);
CREATE POLICY vm_phase1c_rpc_operational_read ON public.vehicle_model_operational_states FOR SELECT TO vm_structural_rpc_owner USING (true);

REVOKE INSERT,UPDATE,DELETE,TRUNCATE ON public.vehicle_brands,public.vehicle_models FROM PUBLIC,anon,authenticated,service_role;
GRANT SELECT,INSERT,UPDATE ON public.vehicle_brands,public.vehicle_models TO vm_structural_rpc_owner;

COMMIT;

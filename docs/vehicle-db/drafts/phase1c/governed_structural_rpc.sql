-- Phase 1C local acceptance DDL. Unnumbered and nondeployable.
-- Apply only after basic_identity_schema.sql in phase1c_acceptance.
DO $$ BEGIN
  IF current_database()<>'phase1c_acceptance' OR to_regclass('public.phase1c_local_guard') IS NULL
     OR NOT EXISTS(SELECT 1 FROM public.phase1c_local_guard WHERE only_disposable_local AND database_name=current_database())
     OR to_regclass('vehicle_private.vm_structural_receipts') IS NULL THEN
    RAISE EXCEPTION 'PHASE1C_RPC_DDL_DISPOSABLE_DATABASE_ONLY';
  END IF;
END $$;
GRANT EXECUTE ON FUNCTION public._vm_structure_problems(text) TO vm_structural_rpc_owner;

CREATE OR REPLACE FUNCTION vehicle_private.vm_json_canonical(p_value jsonb)
RETURNS text LANGUAGE plpgsql IMMUTABLE STRICT PARALLEL SAFE
SET search_path=pg_catalog,vehicle_private,public AS $$
DECLARE result text;
BEGIN
  CASE jsonb_typeof(p_value)
    WHEN 'object' THEN
      SELECT '{'||coalesce(string_agg(to_jsonb(k)::text||': '||vehicle_private.vm_json_canonical(v),', ' ORDER BY k),'')||'}'
        INTO result FROM jsonb_each(p_value) e(k,v);
      RETURN result;
    WHEN 'array' THEN
      SELECT '['||coalesce(string_agg(vehicle_private.vm_json_canonical(v),', ' ORDER BY n),'')||']'
        INTO result FROM jsonb_array_elements(p_value) WITH ORDINALITY e(v,n);
      RETURN result;
    WHEN 'string' THEN RETURN to_jsonb(p_value #>> '{}')::text;
    ELSE RETURN p_value::text;
  END CASE;
END $$;

CREATE OR REPLACE FUNCTION vehicle_private.vm_issue_structural_capability(
  p_approval_ref text,p_executor text,p_batch_hash text,p_operations text[],p_expires_at timestamptz,
  p_token text,p_admin_evidence_ref text)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,vehicle_private AS $$
DECLARE actor text := session_user; nonce_value uuid:=gen_random_uuid(); canonical_ops text[];
BEGIN
  IF NOT pg_has_role(session_user,'vm_structural_approval_admin','member') THEN
    RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='STRUCTURAL_APPROVAL_ISSUER_FORBIDDEN';
  END IF;
  IF p_executor IS NULL OR p_executor=actor
     OR NOT pg_has_role(p_executor::name,'vm_structural_approver','member')
     OR pg_has_role(p_executor::name,'vm_structural_approval_admin','member') THEN
    RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='STRUCTURAL_EXECUTOR_MUST_BE_DISTINCT_APPROVER';
  END IF;
  SELECT array_agg(DISTINCT value ORDER BY value) INTO canonical_ops FROM unnest(p_operations) x(value);
  IF p_approval_ref IS NULL OR p_approval_ref !~ '^[A-Za-z0-9_.:-]{1,128}$'
     OR p_batch_hash IS NULL OR p_batch_hash !~ '^[0-9a-f]{64}$'
     OR coalesce(cardinality(p_operations),0)=0
     OR array_position(p_operations,NULL) IS NOT NULL
     OR canonical_ops IS DISTINCT FROM p_operations
     OR EXISTS (SELECT 1 FROM unnest(p_operations) x(value)
       WHERE value NOT IN ('CREATE_BRAND','CREATE_MODEL_BASIC','UPDATE_MODEL_ALIAS','REVERT'))
     OR p_admin_evidence_ref IS NULL OR btrim(p_admin_evidence_ref)=''
     OR p_token IS NULL OR length(p_token)<32 OR p_expires_at IS NULL OR p_expires_at<=clock_timestamp() THEN
    RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='INVALID_STRUCTURAL_APPROVAL';
  END IF;
  INSERT INTO vehicle_private.vm_structural_approvals(approval_ref,batch_hash,approved_actor,executor_actor,admin_evidence_ref,operations,nonce,expires_at,issued_at)
  VALUES(p_approval_ref,p_batch_hash,actor,p_executor,p_admin_evidence_ref,p_operations,nonce_value,p_expires_at,clock_timestamp());
  INSERT INTO vehicle_private.vm_structural_capabilities(token_sha256,approval_ref,batch_hash,principal,issuer_actor,nonce,operations,expires_at)
  VALUES(public.digest(p_token,'sha256'),p_approval_ref,p_batch_hash,p_executor,actor,nonce_value,p_operations,p_expires_at);
  RETURN nonce_value;
END $$;
ALTER FUNCTION vehicle_private.vm_issue_structural_capability(text,text,text,text[],timestamptz,text,text) OWNER TO vm_structural_rpc_owner;
REVOKE ALL ON FUNCTION vehicle_private.vm_issue_structural_capability(text,text,text,text[],timestamptz,text,text) FROM PUBLIC,anon,authenticated,service_role;
GRANT EXECUTE ON FUNCTION vehicle_private.vm_issue_structural_capability(text,text,text,text[],timestamptz,text,text) TO vm_structural_approval_admin;

CREATE OR REPLACE FUNCTION vehicle_private.vm_apply_structural_changes(p_request jsonb,p_capability text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,vehicle_private,public,pg_temp AS $$
DECLARE
  actor text := session_user; cap vehicle_private.vm_structural_capabilities%ROWTYPE;
  approval vehicle_private.vm_structural_approvals%ROWTYPE;
  intent jsonb; op text; entity text; target_id text; brand_id text; name text; alias_set jsonb; evidence jsonb;
  expected integer; current_revision integer; current_row jsonb; next_payload jsonb; token text;
  batch_id text; batch_hash text; payload_hash text; source_hash text; expected_ops text[];
  receipts jsonb; revision_ids uuid[] := '{}'; revision_id uuid; before_state jsonb; after_state jsonb;
  operation_count integer; source_ref text; reason text; observed_at timestamptz; raw_evidence jsonb;
  i integer := 0; token_item text; canonical_token text;
BEGIN
  IF current_setting('transaction_isolation') <> 'serializable' THEN
    RAISE EXCEPTION USING ERRCODE='25001',MESSAGE='STRUCTURAL_RPC_REQUIRES_SERIALIZABLE';
  END IF;
  IF NOT pg_has_role(session_user,'vm_structural_approver','member') THEN
    RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='STRUCTURAL_APPROVER_FORBIDDEN';
  END IF;
  IF pg_has_role(session_user,'vm_structural_approval_admin','member') THEN
    RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='STRUCTURAL_ISSUER_CANNOT_EXECUTE';
  END IF;
  IF jsonb_typeof(p_request) IS DISTINCT FROM 'object'
     OR (p_request - 'rpc' - 'contract_version' - 'batch_hash' - 'batch_id' - 'payload_hash' - 'expected_revisions' - 'intents' - 'raw_evidence' - 'provenance') <> '{}'::jsonb
     OR p_request->>'rpc'<>'vm_apply_structural_changes'
     OR p_request->>'contract_version'<>'basic-identity-draft-v1'
     OR jsonb_typeof(p_request->'intents') IS DISTINCT FROM 'array'
     OR jsonb_array_length(p_request->'intents')=0 OR jsonb_array_length(p_request->'intents')>500
     OR jsonb_typeof(p_request->'expected_revisions') IS DISTINCT FROM 'array'
     OR jsonb_typeof(p_request->'provenance') IS DISTINCT FROM 'object'
     OR ((p_request->'provenance') - 'source_ref'::text - 'observed_at'::text - 'reason'::text - 'source_hash'::text) <> '{}'::jsonb THEN
    RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='INVALID_STRUCTURAL_RPC_ENVELOPE';
  END IF;
  batch_id := p_request->>'batch_id'; batch_hash := p_request->>'batch_hash'; payload_hash := p_request->>'payload_hash';
  source_ref := p_request#>>'{provenance,source_ref}'; reason := p_request#>>'{provenance,reason}';
  observed_at := (p_request#>>'{provenance,observed_at}')::timestamptz;
  raw_evidence := coalesce(p_request->'raw_evidence','null'::jsonb);
  IF batch_id IS NULL OR batch_id !~ '^[A-Za-z0-9_.:-]{1,128}$'
     OR batch_hash !~ '^[0-9a-f]{64}$' OR payload_hash !~ '^[0-9a-f]{64}$'
     OR source_ref IS NULL OR btrim(source_ref)='' OR reason IS NULL OR btrim(reason)=''
     OR p_request#>>'{provenance,source_hash}' !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='INVALID_STRUCTURAL_RPC_PROVENANCE';
  END IF;
  IF encode(public.digest(convert_to(vehicle_private.vm_json_canonical(p_request-'payload_hash'),'UTF8'),'sha256'),'hex') <> payload_hash THEN
    RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='STRUCTURAL_PAYLOAD_HASH_MISMATCH';
  END IF;
  -- Rebuild the writer's original batch hash and source hash from the strict envelope.
  IF encode(public.digest(convert_to(vehicle_private.vm_json_canonical(
       jsonb_build_object('batch_id',batch_id,'reason',reason,'source_ref',source_ref,'observed_at',p_request#>>'{provenance,observed_at}',
         'intents',p_request->'intents') || CASE WHEN p_request ? 'raw_evidence' THEN jsonb_build_object('raw_evidence',p_request->'raw_evidence') ELSE '{}'::jsonb END
       ),'UTF8'),'sha256'),'hex') <> batch_hash THEN
    RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='STRUCTURAL_BATCH_HASH_MISMATCH';
  END IF;
  -- Validate the raw JSON contract in SQL. These checks are intentionally
  -- independent of the TypeScript serializer and reject operation unions.
  FOR intent IN SELECT value FROM jsonb_array_elements(p_request->'intents') LOOP
    op:=intent->>'operation';
    IF jsonb_typeof(intent) IS DISTINCT FROM 'object'
       OR jsonb_typeof(intent->'operation') IS DISTINCT FROM 'string'
       OR jsonb_typeof(intent->'canonical_id') IS DISTINCT FROM 'string'
       OR jsonb_typeof(intent->'expected_revision') IS DISTINCT FROM 'number'
       OR (intent->>'expected_revision') !~ '^(0|[1-9][0-9]*)$' THEN
      RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='INVALID_STRUCTURAL_INTENT_SHAPE';
    END IF;
    IF op='CREATE_BRAND' THEN
      IF intent-'operation'-'canonical_id'-'name_en'-'aliases'-'expected_revision'<>'{}'::jsonb
         OR jsonb_typeof(intent->'name_en') IS DISTINCT FROM 'string'
         OR (intent ? 'aliases' AND jsonb_typeof(intent->'aliases') IS DISTINCT FROM 'array') THEN
        RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='INVALID_CREATE_BRAND_FIELDS';
      END IF;
    ELSIF op='CREATE_MODEL_BASIC' THEN
      IF intent-'operation'-'canonical_id'-'brand_id'-'name_en'-'aliases'-'identity_evidence'-'expected_revision'<>'{}'::jsonb
         OR jsonb_typeof(intent->'brand_id') IS DISTINCT FROM 'string'
         OR jsonb_typeof(intent->'name_en') IS DISTINCT FROM 'string'
         OR jsonb_typeof(intent->'identity_evidence') IS DISTINCT FROM 'object'
         OR (intent ? 'aliases' AND jsonb_typeof(intent->'aliases') IS DISTINCT FROM 'array')
         OR NOT vehicle_private.vm_basic_evidence_valid(jsonb_build_object('identity_evidence',intent->'identity_evidence')) THEN
        RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='INVALID_CREATE_MODEL_BASIC_FIELDS';
      END IF;
    ELSIF op='UPDATE_MODEL_ALIAS' THEN
      IF intent-'operation'-'canonical_id'-'aliases'-'expected_revision'<>'{}'::jsonb
         OR jsonb_typeof(intent->'aliases') IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='INVALID_UPDATE_MODEL_ALIAS_FIELDS';
      END IF;
    ELSE
      RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='STRUCTURAL_OPERATION_NOT_ALLOWED';
    END IF;
  END LOOP;
  IF EXISTS (SELECT 1 FROM jsonb_array_elements(p_request->'expected_revisions') r
       WHERE jsonb_typeof(r) IS DISTINCT FROM 'object'
         OR (r-'entity_type'-'entity_id'-'revision')<>'{}'::jsonb
         OR jsonb_typeof(r->'entity_type') IS DISTINCT FROM 'string'
         OR jsonb_typeof(r->'entity_id') IS DISTINCT FROM 'string'
         OR jsonb_typeof(r->'revision') IS DISTINCT FROM 'number'
         OR (r->>'revision') !~ '^(0|[1-9][0-9]*)$')
     OR EXISTS (SELECT 1 FROM jsonb_array_elements(p_request->'expected_revisions') r
       GROUP BY r->>'entity_type',r->>'entity_id' HAVING count(*)<>1) THEN
    RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='INVALID_STRUCTURAL_REVISION_SET';
  END IF;
  SELECT array_agg(DISTINCT value->>'operation' ORDER BY value->>'operation') INTO expected_ops
    FROM jsonb_array_elements(p_request->'intents');
  SELECT * INTO cap FROM vehicle_private.vm_structural_capabilities
   WHERE token_sha256=public.digest(p_capability,'sha256') FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='STRUCTURAL_CAPABILITY_NOT_FOUND'; END IF;
  IF cap.principal<>actor OR cap.issuer_actor=actor THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='STRUCTURAL_CAPABILITY_ACTOR_MISMATCH'; END IF;
  IF cap.batch_hash<>batch_hash THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='STRUCTURAL_CAPABILITY_BATCH_HASH_MISMATCH'; END IF;
  IF cap.operations<>expected_ops THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='STRUCTURAL_CAPABILITY_OPERATION_SET_MISMATCH'; END IF;
  IF cap.expires_at<=clock_timestamp() THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='STRUCTURAL_CAPABILITY_EXPIRED'; END IF;
  SELECT * INTO approval FROM vehicle_private.vm_structural_approvals a WHERE a.approval_ref=cap.approval_ref;
  IF NOT FOUND OR approval.approved_actor<>cap.issuer_actor OR approval.executor_actor<>actor
      OR approval.approved_actor=actor OR approval.admin_evidence_ref IS NULL OR btrim(approval.admin_evidence_ref)=''
      OR NOT pg_has_role(approval.approved_actor::name,'vm_structural_approval_admin','member')
      OR cap.nonce<>approval.nonce OR approval.batch_hash<>(p_request->>'batch_hash')
      OR approval.operations<>expected_ops OR approval.expires_at<=clock_timestamp() THEN
    RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='STRUCTURAL_APPROVAL_BINDING_MISMATCH';
  END IF;
  SELECT r.result INTO receipts FROM vehicle_private.vm_structural_receipts r
   WHERE r.actor=session_user AND r.batch_id=(p_request->>'batch_id');
  IF FOUND THEN
    IF (SELECT r.payload_hash FROM vehicle_private.vm_structural_receipts r WHERE r.actor=session_user AND r.batch_id=(p_request->>'batch_id'))<>payload_hash THEN
      RAISE EXCEPTION USING ERRCODE='23505',MESSAGE='STRUCTURAL_IDEMPOTENCY_HASH_CONFLICT';
    END IF;
    RETURN receipts || jsonb_build_object('replay',true);
  END IF;
  IF cap.consumed_at IS NOT NULL THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='STRUCTURAL_CAPABILITY_REPLAYED'; END IF;
  IF encode(public.digest(convert_to(vehicle_private.vm_json_canonical(
      jsonb_build_object('source_ref',source_ref,'raw_evidence',raw_evidence,'intents',
        (SELECT jsonb_agg(value - 'expected_revision' ORDER BY ord) FROM jsonb_array_elements(p_request->'intents') WITH ORDINALITY q(value,ord)))
      ),'UTF8'),'sha256'),'hex') <> p_request#>>'{provenance,source_hash}' THEN
    RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='STRUCTURAL_SOURCE_HASH_MISMATCH';
  END IF;
  operation_count := jsonb_array_length(p_request->'intents');
  IF jsonb_array_length(p_request->'expected_revisions')<>operation_count THEN
    RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='STRUCTURAL_REVISION_SET_MISMATCH';
  END IF;
  INSERT INTO vehicle_private.vm_structural_observations(actor,actor_kind,batch_id,source_ref,observed_at,source_hash,batch_hash,raw_evidence,complete_request)
  VALUES(actor,'ADMIN',batch_id,source_ref,observed_at,p_request#>>'{provenance,source_hash}',batch_hash,raw_evidence,p_request);

  FOR intent IN SELECT value FROM jsonb_array_elements(p_request->'intents') LOOP
    i:=i+1; op:=intent->>'operation'; target_id:=intent->>'canonical_id'; expected:=(intent->>'expected_revision')::integer;
    entity:=CASE WHEN op='CREATE_BRAND' THEN 'vehicle_brands' ELSE 'vehicle_models' END;
    IF intent - 'operation' - 'canonical_id' - 'brand_id' - 'name_en' - 'aliases' - 'identity_evidence' - 'expected_revision' <> '{}'::jsonb THEN
      RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='UNKNOWN_STRUCTURAL_INTENT_FIELD';
    END IF;
    IF (SELECT count(*) FROM jsonb_array_elements(p_request->'expected_revisions') r
        WHERE r->>'entity_type'=entity AND r->>'entity_id'=target_id
          AND (r->>'revision')::integer=expected)<>1 THEN
      RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='STRUCTURAL_REVISION_SET_MISMATCH';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(entity||':'||coalesce(intent->>'brand_id','')||':'||target_id,0));
    IF op IN ('CREATE_BRAND','CREATE_MODEL_BASIC') THEN
      name:=btrim(intent->>'name_en'); alias_set:=coalesce(intent->'aliases','[]'::jsonb);
      IF expected<>0 OR name IS NULL OR name='' OR jsonb_typeof(alias_set) IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='STRUCTURAL_CREATE_PRECONDITION';
      END IF;
      IF EXISTS (SELECT vehicle_private.vm_identity_normalize(a.value #>> '{}',coalesce((SELECT name_en FROM public.vehicle_brands WHERE canonical_id=intent->>'brand_id'),''))
          FROM jsonb_array_elements(alias_set) a(value) GROUP BY 1 HAVING count(*)>1) THEN
        RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='DUPLICATE_NORMALIZED_ALIAS';
      END IF;
      IF op='CREATE_BRAND' THEN
        IF jsonb_array_length(alias_set)>0 THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='UNAPPROVED_BRAND_ALIAS'; END IF;
        IF target_id !~ '^[a-z0-9]+(_[a-z0-9]+)*$' THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='INVALID_BRAND_ID'; END IF;
        brand_id:=target_id;
      ELSE
        brand_id:=intent->>'brand_id'; evidence:=intent->'identity_evidence';
        IF brand_id IS NULL OR target_id !~ ('^'||brand_id||'\.[a-z0-9]+(_[a-z0-9]+)*$')
          OR NOT vehicle_private.vm_basic_evidence_valid(jsonb_build_object('identity_evidence',evidence)) THEN
          RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='INVALID_BASIC_MODEL_IDENTITY';
        END IF;
        PERFORM 1 FROM public.vehicle_brands WHERE canonical_id=brand_id AND deleted_at IS NULL FOR UPDATE;
        IF NOT FOUND THEN RAISE EXCEPTION USING ERRCODE='23503',MESSAGE='BASIC_BRAND_FK_MISSING'; END IF;
        IF vehicle_private.vm_identity_normalize(evidence->>'model_name',(SELECT name_en FROM public.vehicle_brands WHERE canonical_id=brand_id))
           <> vehicle_private.vm_identity_normalize(name,(SELECT name_en FROM public.vehicle_brands WHERE canonical_id=brand_id)) THEN
          RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='BASIC_EVIDENCE_NAME_MISMATCH';
        END IF;
        IF EXISTS (SELECT 1 FROM jsonb_array_elements_text(alias_set) a(value)
          WHERE vehicle_private.vm_identity_normalize(a.value,(SELECT name_en FROM public.vehicle_brands WHERE canonical_id=brand_id))
              <> vehicle_private.vm_identity_normalize(name,(SELECT name_en FROM public.vehicle_brands WHERE canonical_id=brand_id))
            AND NOT EXISTS (SELECT 1 FROM vehicle_private.vm_approved_alias_equivalences e WHERE e.model_id=target_id
              AND e.normalized_alias=vehicle_private.vm_identity_normalize(a.value,(SELECT name_en FROM public.vehicle_brands WHERE canonical_id=brand_id)))) THEN
          RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='UNAPPROVED_BASIC_IDENTITY_ALIAS';
        END IF;
      END IF;
      IF EXISTS (SELECT 1 FROM public.vehicle_brands WHERE slug=replace(target_id,'.','-'))
         OR (entity='vehicle_models' AND EXISTS(SELECT 1 FROM public.vehicle_models WHERE slug=replace(target_id,'.','-')))
         OR (entity='vehicle_brands' AND EXISTS(SELECT 1 FROM public.vehicle_brands WHERE canonical_id=target_id))
         OR (entity='vehicle_models' AND EXISTS(SELECT 1 FROM public.vehicle_models WHERE canonical_id=target_id)) THEN
        RAISE EXCEPTION USING ERRCODE='23505',MESSAGE='STRUCTURAL_CANONICAL_OR_SLUG_COLLISION';
      END IF;
      FOR token_item IN SELECT name UNION SELECT jsonb_array_elements_text(alias_set) LOOP
        canonical_token:=vehicle_private.vm_identity_normalize(token_item,CASE WHEN entity='vehicle_models' THEN (SELECT name_en FROM public.vehicle_brands WHERE canonical_id=brand_id) ELSE '' END);
        PERFORM pg_advisory_xact_lock(hashtextextended(entity||':'||brand_id||':'||canonical_token,0));
        IF canonical_token='' OR EXISTS(SELECT 1 FROM vehicle_private.vm_identity_tokens t
          WHERE t.entity_type=CASE WHEN entity='vehicle_models' THEN 'MODEL' ELSE 'BRAND' END
            AND (entity='vehicle_brands' OR t.brand_id=(intent->>'brand_id')) AND t.normalized_token=canonical_token) THEN
          RAISE EXCEPTION USING ERRCODE='23505',MESSAGE='STRUCTURAL_NORMALIZED_IDENTITY_COLLISION';
        END IF;
      END LOOP;
      IF entity='vehicle_brands' THEN
        INSERT INTO public.vehicle_brands(canonical_id,slug,name_en,payload,served_as_of,revision,seed_release_id,identity_level,identity_aliases)
        VALUES(target_id,replace(target_id,'.','-'),name,jsonb_build_object('id',target_id,'name_en',name,'aliases',alias_set,'identity_level','BASIC','incomplete',true),NULL,1,NULL,'BASIC',alias_set);
      ELSE
        INSERT INTO public.vehicle_models(canonical_id,brand_id,slug,name_en,generation_id,status,segment,body_type,retail_price_min,retail_price_max,payload,served_as_of,revision,seed_release_id,identity_level,identity_aliases)
        VALUES(target_id,brand_id,replace(target_id,'.','-'),name,NULL,NULL,NULL,NULL,NULL,NULL,
          jsonb_build_object('id',target_id,'brand_id',brand_id,'name_en',name,'aliases',alias_set,'identity_level','BASIC','incomplete',true,
            'body_type',NULL,'segment',NULL,'cab_type',NULL,'identity_evidence',evidence),NULL,1,NULL,'BASIC',alias_set);
      END IF;
      INSERT INTO vehicle_private.vm_identity_tokens(entity_type,brand_id,canonical_id,normalized_token,source_kind)
      SELECT CASE WHEN entity='vehicle_models' THEN 'MODEL' ELSE 'BRAND' END,CASE WHEN entity='vehicle_models' THEN brand_id ELSE '' END,target_id,
             vehicle_private.vm_identity_normalize(value,CASE WHEN entity='vehicle_models' THEN (SELECT name_en FROM public.vehicle_brands WHERE canonical_id=brand_id) ELSE '' END),'MASTER_BACKFILL'
        FROM (SELECT name AS value UNION SELECT jsonb_array_elements_text(alias_set)) names
       WHERE vehicle_private.vm_identity_normalize(value,CASE WHEN entity='vehicle_models' THEN (SELECT name_en FROM public.vehicle_brands WHERE canonical_id=brand_id) ELSE '' END)<>'';
      current_row:=CASE WHEN entity='vehicle_models' THEN (SELECT to_jsonb(m) FROM public.vehicle_models m WHERE m.canonical_id=target_id)
                        ELSE (SELECT to_jsonb(b) FROM public.vehicle_brands b WHERE b.canonical_id=target_id) END;
      current_revision:=1; before_state:=NULL;
    ELSIF op='UPDATE_MODEL_ALIAS' THEN
      IF jsonb_typeof(intent->'aliases') IS DISTINCT FROM 'array' THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='ALIAS_SET_REQUIRED'; END IF;
      IF EXISTS (SELECT vehicle_private.vm_identity_normalize(a.value,(SELECT b.name_en FROM public.vehicle_brands b JOIN public.vehicle_models m ON m.brand_id=b.canonical_id WHERE m.canonical_id=(intent->>'canonical_id')))
          FROM jsonb_array_elements_text(intent->'aliases') a(value) GROUP BY 1 HAVING count(*)>1) THEN
        RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='DUPLICATE_NORMALIZED_ALIAS';
      END IF;
      SELECT revision,to_jsonb(m) INTO current_revision,current_row FROM public.vehicle_models m WHERE canonical_id=target_id AND deleted_at IS NULL FOR UPDATE;
      IF NOT FOUND OR current_revision<>expected THEN RAISE EXCEPTION USING ERRCODE='40001',MESSAGE='STRUCTURAL_STALE_REVISION'; END IF;
      before_state:=current_row; brand_id:=current_row->>'brand_id';
      FOR token_item IN SELECT jsonb_array_elements_text(intent->'aliases') LOOP
        canonical_token:=vehicle_private.vm_identity_normalize(token_item,(SELECT name_en FROM public.vehicle_brands WHERE canonical_id=brand_id));
        IF canonical_token='' THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='EMPTY_NORMALIZED_ALIAS'; END IF;
        PERFORM pg_advisory_xact_lock(hashtextextended('vehicle_models:'||brand_id||':'||canonical_token,0));
        IF canonical_token<>vehicle_private.vm_identity_normalize(current_row->>'name_en',(SELECT name_en FROM public.vehicle_brands WHERE canonical_id=brand_id))
          AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements_text(coalesce(current_row->'identity_aliases','[]'::jsonb)) old_alias
            WHERE vehicle_private.vm_identity_normalize(old_alias,(SELECT name_en FROM public.vehicle_brands WHERE canonical_id=brand_id))=canonical_token)
          AND NOT EXISTS (SELECT 1 FROM vehicle_private.vm_approved_alias_equivalences e WHERE e.model_id=target_id AND e.normalized_alias=canonical_token)
          THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='UNPROVEN_ALIAS_EQUIVALENCE'; END IF;
        IF EXISTS (SELECT 1 FROM vehicle_private.vm_identity_tokens t WHERE t.entity_type='MODEL' AND t.brand_id=(current_row->>'brand_id')
          AND t.canonical_id<>(intent->>'canonical_id') AND t.normalized_token=canonical_token) THEN
          RAISE EXCEPTION USING ERRCODE='23505',MESSAGE='STRUCTURAL_NORMALIZED_IDENTITY_COLLISION';
        END IF;
      END LOOP;
      UPDATE public.vehicle_models SET identity_aliases=intent->'aliases',revision=revision+1,updated_at=now(),payload=jsonb_set(payload,'{aliases}',intent->'aliases',true)
       WHERE canonical_id=target_id;
      DELETE FROM vehicle_private.vm_identity_tokens t WHERE t.entity_type='MODEL' AND t.canonical_id=(intent->>'canonical_id');
      INSERT INTO vehicle_private.vm_identity_tokens(entity_type,brand_id,canonical_id,normalized_token,source_kind)
      SELECT 'MODEL',brand_id,target_id,vehicle_private.vm_identity_normalize(value,(SELECT name_en FROM public.vehicle_brands WHERE canonical_id=brand_id)),'MASTER_BACKFILL'
        FROM (SELECT current_row->>'name_en' AS value UNION SELECT jsonb_array_elements_text(intent->'aliases')) names;
      SELECT revision,to_jsonb(m) INTO current_revision,current_row FROM public.vehicle_models m WHERE canonical_id=target_id;
    ELSE
      RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='STRUCTURAL_OPERATION_NOT_ALLOWED';
    END IF;
    after_state:=current_row;
    INSERT INTO vehicle_private.vm_structural_revisions(batch_id,actor,entity_type,entity_id,operation,before_revision,after_revision,before_state,after_state,source_ref,reason,source_hash,approval_ref)
    VALUES(batch_id,actor,entity,target_id,op,expected,current_revision,before_state,after_state,source_ref,reason,p_request#>>'{provenance,source_hash}',cap.approval_ref)
    RETURNING vm_structural_revisions.revision_id INTO revision_id;
    revision_ids:=array_append(revision_ids,revision_id);
  END LOOP;
  UPDATE vehicle_private.vm_structural_capabilities SET consumed_at=clock_timestamp() WHERE token_sha256=cap.token_sha256;
  receipts:=jsonb_build_object('status','APPLIED','batch_id',batch_id,'revision_ids',to_jsonb(revision_ids),'replay',false);
  INSERT INTO vehicle_private.vm_structural_receipts(actor,batch_id,batch_hash,payload_hash,result)
  VALUES(actor,batch_id,batch_hash,payload_hash,receipts);
  RETURN receipts;
END $$;
ALTER FUNCTION vehicle_private.vm_apply_structural_changes(jsonb,text) OWNER TO vm_structural_rpc_owner;
REVOKE ALL ON FUNCTION vehicle_private.vm_apply_structural_changes(jsonb,text) FROM PUBLIC,anon,authenticated,service_role;
GRANT EXECUTE ON FUNCTION vehicle_private.vm_apply_structural_changes(jsonb,text) TO vm_structural_approver;

-- Compensating-only revert. It hides a created identity or restores the
-- prior alias set, after exact revision/dependency checks. It never deletes.
CREATE OR REPLACE FUNCTION vehicle_private.vm_revert_structural_revision(
  p_revision_id uuid,p_expected_revision integer,p_capability text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,vehicle_private,public,pg_temp AS $$
DECLARE
  actor text:=session_user; original vehicle_private.vm_structural_revisions%ROWTYPE;
  cap vehicle_private.vm_structural_capabilities%ROWTYPE; approval vehicle_private.vm_structural_approvals%ROWTYPE;
  existing vehicle_private.vm_structural_revisions%ROWTYPE;
  row_state jsonb; entity text; target text; brand text; next_rev integer; revert_batch text; receipt_hash text; revert_id uuid;
  aliases_before jsonb;
BEGIN
  IF current_setting('transaction_isolation')<>'serializable' THEN RAISE EXCEPTION USING ERRCODE='25001',MESSAGE='STRUCTURAL_RPC_REQUIRES_SERIALIZABLE'; END IF;
  IF NOT pg_has_role(session_user,'vm_structural_approver','member') THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='STRUCTURAL_APPROVER_FORBIDDEN'; END IF;
  IF pg_has_role(session_user,'vm_structural_approval_admin','member') THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='STRUCTURAL_ISSUER_CANNOT_EXECUTE'; END IF;
  SELECT r.* INTO original FROM vehicle_private.vm_structural_revisions r WHERE r.revision_id=p_revision_id FOR UPDATE;
  IF NOT FOUND OR original.operation NOT IN ('CREATE_BRAND','CREATE_MODEL_BASIC','UPDATE_MODEL_ALIAS') THEN
    RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='STRUCTURAL_REVERT_TARGET_INVALID';
  END IF;
  revert_batch:='revert:'||p_revision_id::text;
  receipt_hash:=encode(public.digest(convert_to(vehicle_private.vm_json_canonical(jsonb_build_object(
    'operation','REVERT','revision_id',p_revision_id::text,'expected_revision',p_expected_revision)), 'UTF8'),'sha256'),'hex');
  SELECT * INTO cap FROM vehicle_private.vm_structural_capabilities c WHERE c.token_sha256=public.digest(p_capability,'sha256') FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='STRUCTURAL_CAPABILITY_NOT_FOUND'; END IF;
  IF cap.principal<>actor OR cap.issuer_actor=actor OR cap.batch_hash<>receipt_hash OR cap.operations<>ARRAY['REVERT'] THEN
    RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='STRUCTURAL_CAPABILITY_BINDING_MISMATCH';
  END IF;
  IF cap.expires_at<=clock_timestamp() THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='STRUCTURAL_CAPABILITY_EXPIRED'; END IF;
  SELECT * INTO approval FROM vehicle_private.vm_structural_approvals a WHERE a.approval_ref=cap.approval_ref;
  IF NOT FOUND OR approval.approved_actor<>cap.issuer_actor OR approval.executor_actor<>actor
      OR approval.approved_actor=actor OR approval.admin_evidence_ref IS NULL OR btrim(approval.admin_evidence_ref)=''
      OR NOT pg_has_role(approval.approved_actor::name,'vm_structural_approval_admin','member')
      OR cap.nonce<>approval.nonce OR approval.batch_hash<>receipt_hash OR approval.operations<>ARRAY['REVERT']
      OR approval.expires_at<=clock_timestamp() THEN
    RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='STRUCTURAL_APPROVAL_BINDING_MISMATCH';
  END IF;
  SELECT r.* INTO existing FROM vehicle_private.vm_structural_revisions r WHERE r.reverts_revision_id=p_revision_id;
  IF FOUND THEN
    IF existing.approval_ref<>cap.approval_ref THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='STRUCTURAL_REVERT_REPLAY_AUTHORIZATION_MISMATCH'; END IF;
    RETURN jsonb_build_object('status','REVERTED','revision_id',existing.revision_id,'replay',true);
  END IF;
  IF cap.consumed_at IS NOT NULL THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='STRUCTURAL_CAPABILITY_REPLAYED'; END IF;
  entity:=original.entity_type; target:=original.entity_id;
  IF entity='vehicle_models' THEN
    SELECT to_jsonb(m) INTO row_state FROM public.vehicle_models m WHERE m.canonical_id=target AND m.deleted_at IS NULL FOR UPDATE;
  ELSE
    SELECT to_jsonb(b) INTO row_state FROM public.vehicle_brands b WHERE b.canonical_id=target AND b.deleted_at IS NULL FOR UPDATE;
  END IF;
  IF row_state IS NULL OR (row_state->>'revision')::integer<>p_expected_revision OR p_expected_revision<>original.after_revision THEN
    RAISE EXCEPTION USING ERRCODE='40001',MESSAGE='STRUCTURAL_REVERT_STALE_REVISION';
  END IF;
  IF original.operation='CREATE_BRAND' THEN
    IF EXISTS (SELECT 1 FROM public.vehicle_models m WHERE m.brand_id=target AND m.deleted_at IS NULL) THEN
      RAISE EXCEPTION USING ERRCODE='23503',MESSAGE='STRUCTURAL_REVERT_ACTIVE_MODEL_DEPENDENT';
    END IF;
  ELSIF original.operation='CREATE_MODEL_BASIC' THEN
    IF EXISTS (SELECT 1 FROM public.vehicle_generations g WHERE g.model_id=target AND g.deleted_at IS NULL)
       OR EXISTS (SELECT 1 FROM public.vehicle_variants v WHERE v.model_id=target AND v.deleted_at IS NULL)
       OR EXISTS (SELECT 1 FROM public.vehicle_trims t WHERE t.model_id=target AND t.deleted_at IS NULL)
       OR EXISTS (SELECT 1 FROM public.vehicle_current_retail_sets r WHERE r.model_id=target)
       OR EXISTS (SELECT 1 FROM public.vehicle_model_operational_states s WHERE s.model_id=target)
       OR EXISTS (SELECT 1 FROM public.ice_model_crosswalk x WHERE x.canonical_model_id=target) THEN
      RAISE EXCEPTION USING ERRCODE='23503',MESSAGE='STRUCTURAL_REVERT_ACTIVE_DEPENDENT';
    END IF;
  ELSE
    aliases_before:=coalesce(original.before_state->'identity_aliases','[]'::jsonb);
    brand:=row_state->>'brand_id';
    IF EXISTS (SELECT 1 FROM jsonb_array_elements_text(aliases_before) a(value)
      JOIN vehicle_private.vm_identity_tokens t ON t.entity_type='MODEL' AND t.brand_id=brand
        AND t.canonical_id<>target AND t.normalized_token=vehicle_private.vm_identity_normalize(a.value,(SELECT name_en FROM public.vehicle_brands WHERE canonical_id=brand))) THEN
      RAISE EXCEPTION USING ERRCODE='23505',MESSAGE='STRUCTURAL_REVERT_ALIAS_COLLISION';
    END IF;
  END IF;
  IF entity='vehicle_models' AND original.operation='UPDATE_MODEL_ALIAS' THEN
    UPDATE public.vehicle_models SET identity_aliases=aliases_before,revision=revision+1,updated_at=now(),
      payload=jsonb_set(payload,'{aliases}',aliases_before,true) WHERE canonical_id=target RETURNING revision,to_jsonb(vehicle_models) INTO next_rev,row_state;
    DELETE FROM vehicle_private.vm_identity_tokens t WHERE t.entity_type='MODEL' AND t.canonical_id=target;
    brand:=row_state->>'brand_id';
    INSERT INTO vehicle_private.vm_identity_tokens(entity_type,brand_id,canonical_id,normalized_token,source_kind)
      SELECT 'MODEL',brand,target,vehicle_private.vm_identity_normalize(value,(SELECT name_en FROM public.vehicle_brands WHERE canonical_id=brand)),'MASTER_BACKFILL'
        FROM (SELECT row_state->>'name_en' AS value UNION SELECT jsonb_array_elements_text(aliases_before)) names
       WHERE vehicle_private.vm_identity_normalize(value,(SELECT name_en FROM public.vehicle_brands WHERE canonical_id=brand))<>'';
  ELSIF entity='vehicle_models' THEN
    UPDATE public.vehicle_models SET deleted_at=now(),revision=revision+1,updated_at=now() WHERE canonical_id=target RETURNING revision,to_jsonb(vehicle_models) INTO next_rev,row_state;
  ELSE
    UPDATE public.vehicle_brands SET deleted_at=now(),revision=revision+1,updated_at=now() WHERE canonical_id=target RETURNING revision,to_jsonb(vehicle_brands) INTO next_rev,row_state;
  END IF;
  INSERT INTO vehicle_private.vm_structural_observations(actor,actor_kind,batch_id,source_ref,observed_at,source_hash,batch_hash,raw_evidence,complete_request)
  VALUES(actor,'ADMIN',revert_batch,original.source_ref,clock_timestamp(),original.source_hash,receipt_hash,'{}'::jsonb,
    jsonb_build_object('operation','REVERT','revision_id',p_revision_id,'expected_revision',p_expected_revision));
  INSERT INTO vehicle_private.vm_structural_revisions(batch_id,actor,entity_type,entity_id,operation,before_revision,after_revision,before_state,after_state,source_ref,reason,source_hash,reverts_revision_id,approval_ref)
  VALUES(revert_batch,actor,entity,target,'REVERT',p_expected_revision,next_rev,original.after_state,row_state,original.source_ref,'COMPENSATING_REVERT',original.source_hash,p_revision_id,cap.approval_ref)
  RETURNING vm_structural_revisions.revision_id INTO revert_id;
  UPDATE vehicle_private.vm_structural_capabilities SET consumed_at=clock_timestamp() WHERE token_sha256=cap.token_sha256;
  RETURN jsonb_build_object('status','REVERTED','revision_id',revert_id,'replay',false);
END $$;
ALTER FUNCTION vehicle_private.vm_revert_structural_revision(uuid,integer,text) OWNER TO vm_structural_rpc_owner;
REVOKE ALL ON FUNCTION vehicle_private.vm_revert_structural_revision(uuid,integer,text) FROM PUBLIC,anon,authenticated,service_role;
GRANT EXECUTE ON FUNCTION vehicle_private.vm_revert_structural_revision(uuid,integer,text) TO vm_structural_approver;

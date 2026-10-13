-- Local acceptance fixture only. This is a deterministic CATALOG seed for
-- replaying the repository's v58 serving-parity gate; it is not production
-- evidence and it is never included in any production migration.
BEGIN;
SET CONSTRAINTS ALL DEFERRED;

INSERT INTO public.canonical_vehicle_releases
  (release_id, schema_version, canonical_revision, source_hash, as_of, counts, payload, status, activated_at)
VALUES
  ('phase1c-local-catalog-fixture', 1, 'phase1c-catalog-fixture-v1', repeat('a',64), DATE '2026-10-13',
   '{"brands":1,"models":1,"generations":1,"market_trims":0,"price_ledger":0,"spec_facts":0}'::jsonb,
   '{"fixture":"Phase 1C local PostgreSQL acceptance only"}'::jsonb, 'ACTIVE', now());
INSERT INTO public.canonical_vehicle_state(scope, active_release_id)
VALUES ('vehicle_catalog','phase1c-local-catalog-fixture');

INSERT INTO public.canonical_brand_projection
  (release_id, canonical_id, tdr_brand_id, slug, name_en, name_th, origin_country, payload)
VALUES
  ('phase1c-local-catalog-fixture','toyota',NULL,'toyota','Toyota','โตโยต้า','JP',
   '{"id":"toyota","name_en":"Toyota","aliases":[]}'::jsonb);
INSERT INTO public.canonical_model_projection
  (release_id, canonical_id, tdr_model_id, brand_id, slug, name_en, name_th, generation_id, status,
   segment, body_type, retail_price_min, retail_price_max, payload)
VALUES
  ('phase1c-local-catalog-fixture','toyota.corolla',NULL,'toyota','toyota-corolla','Corolla',NULL,
   'toyota.corolla.gen1','HISTORICAL','C','SEDAN',NULL,NULL,
   '{"id":"toyota.corolla","brand_id":"toyota","name_en":"Corolla","body_type":"SEDAN","cab_type":"NOT_APPLICABLE","registration_type":"RY1","market_scope":"CORE","retail_status":"HISTORICAL","incomplete":true,"aliases":["Corolla Altis"]}'::jsonb);
INSERT INTO public.canonical_generation_projection
  (release_id, canonical_id, model_id, code, segment, launched, ended, payload)
VALUES
  ('phase1c-local-catalog-fixture','toyota.corolla.gen1','toyota.corolla','gen1','C',NULL,NULL,
   '{"id":"toyota.corolla.gen1","model_id":"toyota.corolla"}'::jsonb);

INSERT INTO public.vehicle_master_state
  (scope, seed_release_id, seed_as_of, seed_source_hash, seed_canonical_revision, release_counts,
   supplemental_expected, supplemental_seeded_at)
VALUES
  ('vehicle_master','phase1c-local-catalog-fixture',DATE '2026-10-13',repeat('a',64),
   'phase1c-catalog-fixture-v1',
   '{"brands":1,"models":1,"generations":1,"market_trims":0,"price_ledger":0,"spec_facts":0}'::jsonb,
   '{"variants":1,"catalog_trims":0,"prices":0,"campaigns":0,"facts":0,"eco_evidence":0,"current_retail_sets":0,"trim_lifecycle_decisions":0,"model_operational_states":0,"legacy_identities":0}'::jsonb,
   now());
INSERT INTO public.vehicle_brands
  (canonical_id, slug, name_en, name_th, origin_country, payload, served_as_of, revision, seed_release_id)
VALUES
  ('toyota','toyota','Toyota','โตโยต้า','JP','{"id":"toyota","name_en":"Toyota","aliases":[]}'::jsonb,
   DATE '2026-10-13',1,'phase1c-local-catalog-fixture');
INSERT INTO public.vehicle_models
  (canonical_id, brand_id, slug, name_en, generation_id, status, segment, body_type, payload, served_as_of,
   revision, seed_release_id)
VALUES
  ('toyota.corolla','toyota','toyota-corolla','Corolla','toyota.corolla.gen1','HISTORICAL','C','SEDAN',
   '{"id":"toyota.corolla","brand_id":"toyota","name_en":"Corolla","body_type":"SEDAN","cab_type":"NOT_APPLICABLE","registration_type":"RY1","market_scope":"CORE","retail_status":"HISTORICAL","incomplete":true,"aliases":["Corolla Altis"]}'::jsonb,
   DATE '2026-10-13',1,'phase1c-local-catalog-fixture');
INSERT INTO public.vehicle_generations
  (canonical_id, model_id, code, segment, payload, revision, seed_release_id)
VALUES
  ('toyota.corolla.gen1','toyota.corolla','gen1','C',
   '{"id":"toyota.corolla.gen1","model_id":"toyota.corolla"}'::jsonb,1,'phase1c-local-catalog-fixture');
INSERT INTO public.vehicle_variants
  (canonical_id, generation_id, model_id, name, powertrain, import_type, origin_country, payload, revision, seed_release_id)
VALUES
  ('toyota.corolla.gen1.unknown','toyota.corolla.gen1','toyota.corolla','Corolla unknown','UNKNOWN','UNKNOWN','UNKNOWN',
   '{"id":"toyota.corolla.gen1.unknown","generation_id":"toyota.corolla.gen1","model_id":"toyota.corolla","name":"Corolla unknown","powertrain":"UNKNOWN","import_type":"UNKNOWN","drivetrain":"UNKNOWN","origin_country":"UNKNOWN","incomplete":true}'::jsonb,
   1,'phase1c-local-catalog-fixture');
COMMIT;

-- Second reviewed brand-logo backfill pass (see migration_v28).
--
-- These are presentation assets only. Wikimedia Commons hosting does not mean
-- every file has identical reuse terms, so do not treat this list as a legal
-- clearance registry. Each candidate should remain independently reviewable,
-- and TDR can later move to a curated/self-hosted asset registry with explicit
-- provenance if stronger guarantees are needed.
--
-- Two candidates from the original pass were deliberately removed here:
-- - Farizon: the Commons candidate was a CC BY-SA photograph of a vehicle badge,
--   not a clean brand asset.
-- - Riddara: the candidate was Radar Auto's logo. Radar is the related China
--   brand/company identity, but the Thai consumer-facing brand is RIDDARA.
--
-- Still unresolved after this pass: denza, farizon, fomm, lotus,
-- mine_mobility, neta, nextem, riddara, sokon, volt.
--
-- As in v28, never overwrite a logo that was already curated manually.

update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/8/8f/AION_Auto_UK_simple_logo.svg' where slug = 'aion' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/6/69/Bentley.svg' where slug = 'bentley' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/0/00/Changan_icon.svg' where slug = 'changan' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/5/55/Chevrolet_simple_logo.svg' where slug = 'chevrolet' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/c/c0/Deepal_global_logo.svg' where slug = 'deepal' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/9/9b/Ferrari_wordmark.svg' where slug = 'ferrari' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/d/dc/%D7%9C%D7%95%D7%92%D7%95_%D7%A9%D7%9C_%D7%A7%D7%91%D7%95%D7%A6%D7%AA_GAC.png' where slug = 'gac' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/b/ba/Logo_da_Great_Wall_Motors.png' where slug = 'gwm' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/f/f7/Jac_motors_textlogo.png' where slug = 'jac' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/3/3a/Lamborghini_-_logo_wordmark%2Bpayoff_%28Italy%2C_1963-%29.svg' where slug = 'lamborghini' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/c/c2/Land_Rover_2023.svg' where slug = 'land-rover' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/e/ed/McLaren_Automotive_logo.svg' where slug = 'mclaren' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/2/25/Peugeot_textlogo21.png' where slug = 'peugeot' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/0/05/Porsche_Schriftzug.svg' where slug = 'porsche' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/3/36/Wuling_Motor_logo.png' where slug = 'wuling' and logo_url is null;

-- Second backfill pass for brand logo_url (see migration_v28 for the first 37).
--
-- v28 only used a Wikipedia-infobox scrape, which missed Commons-hosted logos
-- that exist under filenames the infobox never referenced. This pass instead
-- queries each brand's Wikidata entity for the P154 (logo image) claim --
-- Wikidata itself never hosts non-free/fair-use content, so a P154 value is
-- reliably a freely-licensed Commons file -- and falls back to a direct
-- Commons file search for entities with no P154 claim. Every URL below was
-- verified to resolve to a real image before being included.
--
-- One judgment call worth flagging: `riddara` is mapped to the "Radar Auto"
-- logo. Riddara has no Wikipedia article of its own; Commons only has vehicle
-- photos captioned "Riddara RD6" (2024/2025/2026), and RD6 is Radar Auto's
-- actual model name -- strong evidence Riddara is Radar Auto's Thai-market
-- brand name, not a coincidental redirect. Worth a manual confirmation.
--
-- Still unresolved after this pass (no Commons-licensed logo found, or the
-- brand has no Wikipedia/Wikidata presence at all): denza, fomm, lotus,
-- mine_mobility, neta, nextem, sokon, volt.
--
-- Slug matching is best-effort (same as v28) -- spot check after running.

update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/8/8f/AION_Auto_UK_simple_logo.svg' where slug = 'aion';
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/6/69/Bentley.svg' where slug = 'bentley';
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/0/00/Changan_icon.svg' where slug = 'changan';
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/5/55/Chevrolet_simple_logo.svg' where slug = 'chevrolet';
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/c/c0/Deepal_global_logo.svg' where slug = 'deepal';
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/3/3c/Farizon_badge.jpg' where slug = 'farizon';
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/9/9b/Ferrari_wordmark.svg' where slug = 'ferrari';
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/d/dc/%D7%9C%D7%95%D7%92%D7%95_%D7%A9%D7%9C_%D7%A7%D7%91%D7%95%D7%A6%D7%AA_GAC.png' where slug = 'gac';
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/b/ba/Logo_da_Great_Wall_Motors.png' where slug = 'gwm';
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/f/f7/Jac_motors_textlogo.png' where slug = 'jac';
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/3/3a/Lamborghini_-_logo_wordmark%2Bpayoff_%28Italy%2C_1963-%29.svg' where slug = 'lamborghini';
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/c/c2/Land_Rover_2023.svg' where slug = 'land-rover';
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/e/ed/McLaren_Automotive_logo.svg' where slug = 'mclaren';
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/2/25/Peugeot_textlogo21.png' where slug = 'peugeot';
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/0/05/Porsche_Schriftzug.svg' where slug = 'porsche';
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/1/12/Radar_Auto_logo.png' where slug = 'riddara';
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/3/36/Wuling_Motor_logo.png' where slug = 'wuling';

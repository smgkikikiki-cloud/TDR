-- Brand logos: fill the presentation field the public pages already render.
--
-- app/brands/page.tsx, app/brands/[slug]/page.tsx, app/models/page.tsx and
-- app/page.tsx have all rendered `logo_url ? <img> : <initials>` since they
-- were written, and every one of them has always taken the second branch:
-- getCanonicalBrands() returned a hardcoded `logo_url: null`, and
-- public.brands.logo_url is null on all 62 production rows. The reader saw
-- text initials not because a logo was missing but because the field was
-- never filled and never read.
--
-- Brand identity stays canonical in current_vehicle_brands. logo_url is an
-- optional TDR presentation overlay on public.brands, joined back through the
-- stable tdr_brand_id foreign key rather than a mutable slug -- see
-- getCanonicalBrands() in lib/canonical-data.ts, where the read is fail-open:
-- if the optional editorial table cannot be read, the catalogue still renders
-- and the initials fallback stands.
--
-- These 52 URLs point at Wikimedia Commons files that were reviewed for brand
-- identity and availability. Commons hosting is not a blanket legal clearance:
-- each file carries its own copyright, attribution and trademark terms. This
-- is a presentation backfill, not a provenance registry; if TDR later needs
-- stronger guarantees, move to curated self-hosted assets.
--
-- Two candidates were dropped during review and are deliberately absent:
-- Farizon (the Commons file is a CC BY-SA photograph of a badge, not a brand
-- asset) and Riddara (the candidate was Radar Auto's mark -- a related China
-- identity, but not the Thai consumer-facing brand). BMW is the roundel, not
-- the BMW Group corporate wordmark.
--
-- Still on the initials fallback, by choice rather than by oversight:
-- denza, farizon, fomm, lotus, mine-mobility, neta, nextem, riddara, sokon,
-- volt.
--
-- Every statement is non-destructive: `and logo_url is null` means a logo
-- curated by hand always wins and re-running this changes nothing.
--
-- Numbering: this work was originally written as v28 and v29 before either
-- was applied. v29 was taken by migration_v29_registration_dlt_v2_shadow.sql,
-- which is live, so both passes are renumbered into this one file. v28 is a
-- gap that was never applied to any database and is left as one.

begin;

update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/8/8f/AION_Auto_UK_simple_logo.svg' where slug = 'aion' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/9/92/Audi-Logo_2016.svg' where slug = 'audi' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/3/32/Avatr_Technology_logo.svg' where slug = 'avatr' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/6/69/Bentley.svg' where slug = 'bentley' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/6/66/BMW_logo_%28white_%2B_grey_background_circle%29.svg' where slug = 'bmw' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/9/99/BYD_Company%2C_Ltd._-_Logo.svg' where slug = 'byd' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/0/00/Changan_icon.svg' where slug = 'changan' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/b/b6/Chery_logo.svg' where slug = 'chery' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/5/55/Chevrolet_simple_logo.svg' where slug = 'chevrolet' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/b/bc/Daihatsu_logo_1998.svg' where slug = 'daihatsu' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/c/c0/Deepal_global_logo.svg' where slug = 'deepal' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/9/9b/Ferrari_wordmark.svg' where slug = 'ferrari' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/3/3e/Ford_logo_flat.svg' where slug = 'ford' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/f/fa/Foton_Motor_logo.svg' where slug = 'foton' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/d/dc/%D7%9C%D7%95%D7%92%D7%95_%D7%A9%D7%9C_%D7%A7%D7%91%D7%95%D7%A6%D7%AA_GAC.png' where slug = 'gac' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/2/2c/Geely_Logo_2022.svg' where slug = 'geely' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/b/ba/Logo_da_Great_Wall_Motors.png' where slug = 'gwm' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/1/1a/Hino_Motors_logo_2026.svg' where slug = 'hino' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/7/76/Honda_logo.svg' where slug = 'honda' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/4/44/Hyundai_Motor_Company_logo.svg' where slug = 'hyundai' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/4/49/Isuzu.svg' where slug = 'isuzu' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/f/f7/Jac_motors_textlogo.png' where slug = 'jac' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/4/4b/Jaecoo_wordmark.svg' where slug = 'jaecoo' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/9/92/Jeep_wordmark.svg' where slug = 'jeep' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/b/b6/KIA_logo3.svg' where slug = 'kia' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/3/3a/Lamborghini_-_logo_wordmark%2Bpayoff_%28Italy%2C_1963-%29.svg' where slug = 'lamborghini' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/c/c2/Land_Rover_2023.svg' where slug = 'land-rover' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/d/d8/Leapmotor_logo_en.svg' where slug = 'leapmotor' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/7/75/Lexus.svg' where slug = 'lexus' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/7/78/Maserati_logo_2.svg' where slug = 'maserati' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/4/43/Mazda_logo_2024_%28vertical%29.svg' where slug = 'mazda' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/e/ed/McLaren_Automotive_logo.svg' where slug = 'mclaren' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/9/98/Mercedes-Benz_Star_%281969-1986%2C_2025-%29.svg' where slug = 'mercedes-benz' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/c/c8/MG_Motor_2021_logo.svg' where slug = 'mg' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/e/e9/MINI_logo.svg' where slug = 'mini' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/9/9a/Mitsubishi_motors_new_logo.svg' where slug = 'mitsubishi' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/a/a6/Nissan_Motor_Corporation_2020_logo.svg' where slug = 'nissan' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/2/25/Peugeot_textlogo21.png' where slug = 'peugeot' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/0/05/Porsche_Schriftzug.svg' where slug = 'porsche' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/0/0a/Rolls_royce_motorcars_logo.svg' where slug = 'rolls-royce' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/3/3d/Logo_Seres_Group.svg' where slug = 'seres' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/c/ca/Subaru_logo_%28transparent%29.svg' where slug = 'subaru' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/e/ee/Suzuki_logo_2025_%28vertical%29.svg' where slug = 'suzuki' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/f/f1/Tata_Motors_Logo.svg' where slug = 'tata' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/b/bd/Tesla_Motors.svg' where slug = 'tesla' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/e/e7/Toyota.svg' where slug = 'toyota' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/a/a2/UD_Trucks_logo_detailed_SVG.svg' where slug = 'ud-trucks' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/6/6d/Volkswagen_logo_2019.svg' where slug = 'volkswagen' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/2/29/Volvo-Iron-Mark-Black.svg' where slug = 'volvo' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/3/36/Wuling_Motor_logo.png' where slug = 'wuling' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/c/ca/XPeng_logo.svg' where slug = 'xpeng' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/1/1e/Zeekr_logo.svg' where slug = 'zeekr' and logo_url is null;

commit;

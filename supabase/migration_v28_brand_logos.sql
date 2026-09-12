-- Backfill logo_url for the 62 canonical brands' legacy TDR brand rows.
--
-- getCanonicalBrands() hardcoded logo_url: null (current_vehicle_brands
-- carries only canonical identity fields, never a display asset), so no
-- brand card or brand page could ever show a real logo regardless of data.
-- The legacy `brands` table already has a real logo_url column that the
-- deprecated admin edit UI used to set, and nothing has been backfilling it
-- since brand identity moved to the canonical pipeline.
--
-- These 37 logos are all hosted on Wikimedia Commons (verified, not
-- Wikipedia's local non-free/fair-use repository) so they're safe to embed
-- on a commercial site. The remaining 25 canonical brands are intentionally
-- left out: no usable Commons-licensed logo could be found, or the only
-- candidate was fair-use-only, or the Wikipedia match was ambiguous/wrong.
--
-- Matching is by slug, using the same _slug() convention tdr_bridge/release.py
-- uses to derive current_vehicle_brands.slug (e.g. mercedes_benz -> mercedes-benz).
-- This was written without live read access to the `brands` table, so slugs
-- are a best-effort match -- spot check after running that these updated the
-- rows you expect (a slug with no matching row is simply a no-op update).

update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/9/92/Audi-Logo_2016.svg' where slug = 'audi';
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/3/32/Avatr_Technology_logo.svg' where slug = 'avatr';
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/7/73/Logo_BMW_Group_2021.svg' where slug = 'bmw';
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/9/99/BYD_Company%2C_Ltd._-_Logo.svg' where slug = 'byd';
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/b/b6/Chery_logo.svg' where slug = 'chery';
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/b/bc/Daihatsu_logo_1998.svg' where slug = 'daihatsu';
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/3/3e/Ford_logo_flat.svg' where slug = 'ford';
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/f/fa/Foton_Motor_logo.svg' where slug = 'foton';
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/2/2c/Geely_Logo_2022.svg' where slug = 'geely';
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/1/1a/Hino_Motors_logo_2026.svg' where slug = 'hino';
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/7/76/Honda_logo.svg' where slug = 'honda';
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/4/44/Hyundai_Motor_Company_logo.svg' where slug = 'hyundai';
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/4/49/Isuzu.svg' where slug = 'isuzu';
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/4/4b/Jaecoo_wordmark.svg' where slug = 'jaecoo';
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/9/92/Jeep_wordmark.svg' where slug = 'jeep';
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/b/b6/KIA_logo3.svg' where slug = 'kia';
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/d/d8/Leapmotor_logo_en.svg' where slug = 'leapmotor';
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/7/75/Lexus.svg' where slug = 'lexus';
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/7/78/Maserati_logo_2.svg' where slug = 'maserati';
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/4/43/Mazda_logo_2024_%28vertical%29.svg' where slug = 'mazda';
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/9/98/Mercedes-Benz_Star_%281969-1986%2C_2025-%29.svg' where slug = 'mercedes-benz';
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/c/c8/MG_Motor_2021_logo.svg' where slug = 'mg';
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/e/e9/MINI_logo.svg' where slug = 'mini';
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/9/9a/Mitsubishi_motors_new_logo.svg' where slug = 'mitsubishi';
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/a/a6/Nissan_Motor_Corporation_2020_logo.svg' where slug = 'nissan';
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/0/0a/Rolls_royce_motorcars_logo.svg' where slug = 'rolls-royce';
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/3/3d/Logo_Seres_Group.svg' where slug = 'seres';
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/c/ca/Subaru_logo_%28transparent%29.svg' where slug = 'subaru';
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/e/ee/Suzuki_logo_2025_%28vertical%29.svg' where slug = 'suzuki';
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/f/f1/Tata_Motors_Logo.svg' where slug = 'tata';
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/b/bd/Tesla_Motors.svg' where slug = 'tesla';
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/e/e7/Toyota.svg' where slug = 'toyota';
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/a/a2/UD_Trucks_logo_detailed_SVG.svg' where slug = 'ud-trucks';
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/6/6d/Volkswagen_logo_2019.svg' where slug = 'volkswagen';
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/2/29/Volvo-Iron-Mark-Black.svg' where slug = 'volvo';
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/c/ca/XPeng_logo.svg' where slug = 'xpeng';
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/1/1e/Zeekr_logo.svg' where slug = 'zeekr';

-- Backfill reviewed brand-logo candidates onto the TDR editorial brand rows.
--
-- Brand identity remains canonical in current_vehicle_brands. logo_url is an
-- optional presentation field on public.brands and is joined back through the
-- stable tdr_brand_id foreign key by getCanonicalBrands().
--
-- The URLs below point to Wikimedia Commons-hosted files that were checked for
-- brand identity and image availability when this migration was prepared.
-- Commons hosting is not, by itself, a blanket legal clearance: each file can
-- carry its own copyright, attribution and trademark conditions. Keep source
-- review separate from canonical vehicle truth and prefer a curated/self-hosted
-- asset registry if TDR later needs stronger provenance guarantees.
--
-- These updates are intentionally non-destructive. A logo already curated in
-- public.brands wins over this backfill and will never be overwritten.

update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/9/92/Audi-Logo_2016.svg' where slug = 'audi' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/3/32/Avatr_Technology_logo.svg' where slug = 'avatr' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/6/66/BMW_logo_%28white_%2B_grey_background_circle%29.svg' where slug = 'bmw' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/9/99/BYD_Company%2C_Ltd._-_Logo.svg' where slug = 'byd' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/b/b6/Chery_logo.svg' where slug = 'chery' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/b/bc/Daihatsu_logo_1998.svg' where slug = 'daihatsu' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/3/3e/Ford_logo_flat.svg' where slug = 'ford' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/f/fa/Foton_Motor_logo.svg' where slug = 'foton' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/2/2c/Geely_Logo_2022.svg' where slug = 'geely' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/1/1a/Hino_Motors_logo_2026.svg' where slug = 'hino' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/7/76/Honda_logo.svg' where slug = 'honda' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/4/44/Hyundai_Motor_Company_logo.svg' where slug = 'hyundai' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/4/49/Isuzu.svg' where slug = 'isuzu' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/4/4b/Jaecoo_wordmark.svg' where slug = 'jaecoo' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/9/92/Jeep_wordmark.svg' where slug = 'jeep' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/b/b6/KIA_logo3.svg' where slug = 'kia' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/d/d8/Leapmotor_logo_en.svg' where slug = 'leapmotor' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/7/75/Lexus.svg' where slug = 'lexus' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/7/78/Maserati_logo_2.svg' where slug = 'maserati' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/4/43/Mazda_logo_2024_%28vertical%29.svg' where slug = 'mazda' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/9/98/Mercedes-Benz_Star_%281969-1986%2C_2025-%29.svg' where slug = 'mercedes-benz' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/c/c8/MG_Motor_2021_logo.svg' where slug = 'mg' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/e/e9/MINI_logo.svg' where slug = 'mini' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/9/9a/Mitsubishi_motors_new_logo.svg' where slug = 'mitsubishi' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/a/a6/Nissan_Motor_Corporation_2020_logo.svg' where slug = 'nissan' and logo_url is null;
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
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/c/ca/XPeng_logo.svg' where slug = 'xpeng' and logo_url is null;
update public.brands set logo_url = 'https://upload.wikimedia.org/wikipedia/commons/1/1e/Zeekr_logo.svg' where slug = 'zeekr' and logo_url is null;

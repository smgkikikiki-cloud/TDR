/*
 * Curated brand-logo fallbacks for the public presentation layer.
 *
 * The same assets are already listed in migration_v37_brand_logos.sql, but
 * production may lag that data migration. Keeping this fallback in code means
 * the public catalogue does not silently collapse back to initials whenever
 * the editorial logo column is still empty. A database logo always wins.
 */
const BRAND_LOGO_FALLBACKS: Record<string, string> = {
  aion: "https://upload.wikimedia.org/wikipedia/commons/8/8f/AION_Auto_UK_simple_logo.svg",
  audi: "https://upload.wikimedia.org/wikipedia/commons/9/92/Audi-Logo_2016.svg",
  avatr: "https://upload.wikimedia.org/wikipedia/commons/3/32/Avatr_Technology_logo.svg",
  bentley: "https://upload.wikimedia.org/wikipedia/commons/6/69/Bentley.svg",
  bmw: "https://upload.wikimedia.org/wikipedia/commons/6/66/BMW_logo_%28white_%2B_grey_background_circle%29.svg",
  byd: "https://upload.wikimedia.org/wikipedia/commons/9/99/BYD_Company%2C_Ltd._-_Logo.svg",
  changan: "https://upload.wikimedia.org/wikipedia/commons/0/00/Changan_icon.svg",
  chery: "https://upload.wikimedia.org/wikipedia/commons/b/b6/Chery_logo.svg",
  chevrolet: "https://upload.wikimedia.org/wikipedia/commons/5/55/Chevrolet_simple_logo.svg",
  daihatsu: "https://upload.wikimedia.org/wikipedia/commons/b/bc/Daihatsu_logo_1998.svg",
  deepal: "https://upload.wikimedia.org/wikipedia/commons/c/c0/Deepal_global_logo.svg",
  ferrari: "https://upload.wikimedia.org/wikipedia/commons/9/9b/Ferrari_wordmark.svg",
  ford: "https://upload.wikimedia.org/wikipedia/commons/3/3e/Ford_logo_flat.svg",
  foton: "https://upload.wikimedia.org/wikipedia/commons/f/fa/Foton_Motor_logo.svg",
  gac: "https://upload.wikimedia.org/wikipedia/commons/d/dc/%D7%9C%D7%95%D7%92%D7%95_%D7%A9%D7%9C_%D7%A7%D7%91%D7%95%D7%A6%D7%AA_GAC.png",
  geely: "https://upload.wikimedia.org/wikipedia/commons/2/2c/Geely_Logo_2022.svg",
  gwm: "https://upload.wikimedia.org/wikipedia/commons/b/ba/Logo_da_Great_Wall_Motors.png",
  hino: "https://upload.wikimedia.org/wikipedia/commons/1/1a/Hino_Motors_logo_2026.svg",
  honda: "https://upload.wikimedia.org/wikipedia/commons/7/76/Honda_logo.svg",
  hyundai: "https://upload.wikimedia.org/wikipedia/commons/4/44/Hyundai_Motor_Company_logo.svg",
  isuzu: "https://upload.wikimedia.org/wikipedia/commons/4/49/Isuzu.svg",
  jac: "https://upload.wikimedia.org/wikipedia/commons/f/f7/Jac_motors_textlogo.png",
  jaecoo: "https://upload.wikimedia.org/wikipedia/commons/4/4b/Jaecoo_wordmark.svg",
  jeep: "https://upload.wikimedia.org/wikipedia/commons/9/92/Jeep_wordmark.svg",
  kia: "https://upload.wikimedia.org/wikipedia/commons/b/b6/KIA_logo3.svg",
  lamborghini: "https://upload.wikimedia.org/wikipedia/commons/3/3a/Lamborghini_-_logo_wordmark%2Bpayoff_%28Italy%2C_1963-%29.svg",
  "land-rover": "https://upload.wikimedia.org/wikipedia/commons/c/c2/Land_Rover_2023.svg",
  leapmotor: "https://upload.wikimedia.org/wikipedia/commons/d/d8/Leapmotor_logo_en.svg",
  lexus: "https://upload.wikimedia.org/wikipedia/commons/7/75/Lexus.svg",
  maserati: "https://upload.wikimedia.org/wikipedia/commons/7/78/Maserati_logo_2.svg",
  mazda: "https://upload.wikimedia.org/wikipedia/commons/4/43/Mazda_logo_2024_%28vertical%29.svg",
  mclaren: "https://upload.wikimedia.org/wikipedia/commons/e/ed/McLaren_Automotive_logo.svg",
  "mercedes-benz": "https://upload.wikimedia.org/wikipedia/commons/9/98/Mercedes-Benz_Star_%281969-1986%2C_2025-%29.svg",
  mg: "https://upload.wikimedia.org/wikipedia/commons/c/c8/MG_Motor_2021_logo.svg",
  mini: "https://upload.wikimedia.org/wikipedia/commons/e/e9/MINI_logo.svg",
  mitsubishi: "https://upload.wikimedia.org/wikipedia/commons/9/9a/Mitsubishi_motors_new_logo.svg",
  nissan: "https://upload.wikimedia.org/wikipedia/commons/a/a6/Nissan_Motor_Corporation_2020_logo.svg",
  peugeot: "https://upload.wikimedia.org/wikipedia/commons/2/25/Peugeot_textlogo21.png",
  porsche: "https://upload.wikimedia.org/wikipedia/commons/0/05/Porsche_Schriftzug.svg",
  "rolls-royce": "https://upload.wikimedia.org/wikipedia/commons/0/0a/Rolls_royce_motorcars_logo.svg",
  seres: "https://upload.wikimedia.org/wikipedia/commons/3/3d/Logo_Seres_Group.svg",
  subaru: "https://upload.wikimedia.org/wikipedia/commons/c/ca/Subaru_logo_%28transparent%29.svg",
  suzuki: "https://upload.wikimedia.org/wikipedia/commons/e/ee/Suzuki_logo_2025_%28vertical%29.svg",
  tata: "https://upload.wikimedia.org/wikipedia/commons/f/f1/Tata_Motors_Logo.svg",
  tesla: "https://upload.wikimedia.org/wikipedia/commons/b/bd/Tesla_Motors.svg",
  toyota: "https://upload.wikimedia.org/wikipedia/commons/e/e7/Toyota.svg",
  "ud-trucks": "https://upload.wikimedia.org/wikipedia/commons/a/a2/UD_Trucks_logo_detailed_SVG.svg",
  volkswagen: "https://upload.wikimedia.org/wikipedia/commons/6/6d/Volkswagen_logo_2019.svg",
  volvo: "https://upload.wikimedia.org/wikipedia/commons/2/29/Volvo-Iron-Mark-Black.svg",
  wuling: "https://upload.wikimedia.org/wikipedia/commons/3/36/Wuling_Motor_logo.png",
  xpeng: "https://upload.wikimedia.org/wikipedia/commons/c/ca/XPeng_logo.svg",
  zeekr: "https://upload.wikimedia.org/wikipedia/commons/1/1e/Zeekr_logo.svg",
};

export function resolveBrandLogo(slug: string | null | undefined, databaseLogo?: string | null): string | null {
  if (databaseLogo) return databaseLogo;
  const key = String(slug || "").trim().toLowerCase();
  return BRAND_LOGO_FALLBACKS[key] || null;
}

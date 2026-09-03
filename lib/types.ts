export type Brand = {
  id: string;
  slug: string;
  name_th: string;
  name_en: string | null;
  country_origin: string | null;
  status: string;
  notes: string | null;
  updated_at: string;
};

export type Plant = {
  id: string;
  slug: string;
  name_th: string;
  name_en: string | null;
  maker_group: string | null;
  province: string | null;
  district: string | null;
  capacity_annual: number | null;
  opened_year: number | null;
  status: string;
  notes: string | null;
  updated_at: string;
};

export type Company = {
  id: string;
  slug: string;
  name_th: string;
  name_en: string | null;
  company_type: string;
  parent_company: string | null;
  province: string | null;
  products_services: string | null;
  notes: string | null;
  updated_at: string;
};

export type Model = {
  id: string;
  slug: string;
  brand_id: string | null;
  name_th: string;
  name_en: string | null;
  generation: string | null;
  body_type: string | null;
  segment: string | null;
  market_position: string | null;
  powertrains: string[];
  production_type: string | null;
  production_country: string | null;
  launch_month: number | null;
  launch_quarter: string | null;
  launch_year: number | null;
  status: string | null;
  upcoming_status: string | null;
  notes: string | null;
  updated_at: string;
  brands?: { name_th: string; slug: string } | null;
  model_plants?: { plant_id: string; plants: { name_th: string; slug: string; province: string | null; maker_group: string | null } | null }[];
};

export type Event = {
  id: string;
  title_th: string;
  title_en: string | null;
  event_date: string;
  event_type: string;
  summary_th: string | null;
  source_name: string | null;
  source_url: string | null;
  related_brand_id: string | null;
  related_model_id: string | null;
  related_plant_id: string | null;
  related_company_id: string | null;
  published: boolean;
  created_at: string;
};

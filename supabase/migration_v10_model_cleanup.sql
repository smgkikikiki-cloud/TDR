-- TDR Automotive Intelligence V1.0 model-editor cleanup
-- Add quarter-based launch field. Old date/month columns are intentionally left in place for compatibility but are no longer used by the editor.
alter table models add column if not exists launch_quarter text;

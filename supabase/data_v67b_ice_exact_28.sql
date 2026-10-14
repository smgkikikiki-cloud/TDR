-- Owner approval 2026-10-14 (chat: "อนุมัติ 28"): 28 exact same-brand name links, 47,891 units (Mercedes-Benz x27, Rolls-Royce Ghost x1).
-- Run in Supabase SQL Editor (project: smgkikikiki-cloud's Project). Safe to re-run. Rollback: delete from public.ice_model_crosswalk_scoped where decision_ref = 'owner-chat-2026-10-14-exact-28';
insert into public.ice_model_crosswalk_scoped
  (model_group_id, reg_type_scope, status, canonical_model_id, pending_target_id, master_version, decision_ref, source_sha256, reason)
select v.g, v.s, 'APPROVED', v.c, null, '7.0', 'owner-chat-2026-10-14-exact-28', 'c558d2d4cc3ed667f8b30ea028dbb66c4030cdce4e7daabe735df870cb94677d',
       'owner approved batch of exact same-brand normalized-name links (SAME_BRAND_EXACT_NORMALIZED_MODEL_NAME)'
from (values
('mercedes-benz-mercedes-benz-a-class','รย.1','mercedes_benz.a_class'),
('mercedes-benz-mercedes-benz-c-class','รย.1','mercedes_benz.mb_c_class'),
('mercedes-benz-mercedes-benz-c-class','รย.10','mercedes_benz.mb_c_class'),
('mercedes-benz-mercedes-benz-c250','รย.1','mercedes_benz.mb_c_class'),
('mercedes-benz-mercedes-benz-cls','รย.1','mercedes_benz.cls'),
('mercedes-benz-mercedes-benz-e-class','รย.1','mercedes_benz.mb_e_class'),
('mercedes-benz-mercedes-benz-e-class','รย.10','mercedes_benz.mb_e_class'),
('mercedes-benz-mercedes-benz-e-class','รย.11','mercedes_benz.mb_e_class'),
('mercedes-benz-mercedes-benz-e-class','รย.9','mercedes_benz.mb_e_class'),
('mercedes-benz-mercedes-benz-g-class','รย.1','mercedes_benz.g_class'),
('mercedes-benz-mercedes-benz-s-class','รย.1','mercedes_benz.s_class'),
('mercedes-benz-mercedes-benz-s-class','รย.9','mercedes_benz.s_class'),
('mercedes-benz-mercedes-benz-sprinter','รย.1','mercedes_benz.sprinter'),
('mercedes-benz-mercedes-benz-sprinter','รย.2','mercedes_benz.sprinter'),
('mercedes-benz-mercedes-benz-sprinter','รย.3','mercedes_benz.sprinter'),
('mercedes-benz-mercedes-benz-v-class','รย.1','mercedes_benz.v_class'),
('mercedes-benz-mercedes-benz-v-class','รย.2','mercedes_benz.v_class'),
('mercedes-benz-mercedes-benz-v-class','รย.9','mercedes_benz.v_class'),
('mercedes-benz-mercedes-benz-vito','รย.1','mercedes_benz.vito'),
('mercedes-benz-mercedes-benz-vito','รย.2','mercedes_benz.vito'),
('mercedes-benz-mercedes-benz-vito','รย.3','mercedes_benz.vito'),
('mercedes-benz-mercedes-gla','รย.1','mercedes_benz.mb_gla'),
('mercedes-benz-mercedes-glc','รย.1','mercedes_benz.mb_glc'),
('mercedes-benz-mercedes-glc','รย.10','mercedes_benz.mb_glc'),
('mercedes-benz-mercedes-gle','รย.1','mercedes_benz.gle'),
('mercedes-benz-mercedes-gle','รย.9','mercedes_benz.gle'),
('mercedes-benz-mercedes-gls','รย.1','mercedes_benz.gls'),
('rolls-royce-rolls-royce-ghost','รย.1','rolls_royce.ghost')
) as v(g, s, c)
where exists (select 1 from public.vehicle_models m where m.canonical_id = v.c)
on conflict (model_group_id, reg_type_scope) do nothing;

-- Check (expected: APPROVED 476 = 448 + 28):
select status, count(*) from public.ice_model_crosswalk_scoped group by status order by status;

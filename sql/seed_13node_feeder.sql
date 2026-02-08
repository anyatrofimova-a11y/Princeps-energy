-- Seed for 13-node feeder example (Table I & Table II from paper).
-- Uses the network_nodes / network_components tables from schema.sql.

BEGIN;

-- Insert nodes (buses)
INSERT INTO network_nodes (node_id, current_load_mw, current_gen_mw, pf) VALUES
  ('301',   0, 0, 0.98),
  ('1100',  0, 0, 0.98),
  ('1115',  2.1, 0.3, 0.98),
  ('1116',  1.8, 0.2, 0.98),
  ('1117',  1.5, 0.1, 0.98),
  ('1118',  1.9, 0.4, 0.98),
  ('1119',  1.2, 0.6, 0.98),
  ('1120',  0.8, 0.2, 0.98),
  ('1121',  0.6, 0.1, 0.98),
  ('1122',  0.4, 0.05, 0.98),
  ('1123',  0.5, 0.1, 0.98),
  ('1124',  0.3, 0.05, 0.98),
  ('1125',  0.2, 0.02, 0.98)
ON CONFLICT (node_id) DO NOTHING;

-- Insert components (Table I)
INSERT INTO network_components (comp_id, from_node, to_node, asset_cost_gbp, capacity_mva, current_flow_mw) VALUES
  ('T1',   '301',  '1100', 2011429.00, 26.40, 12.0),
  ('T2',   '301',  '1100', 2011429.00, 26.40, 12.0),
  ('L1',   '1100', '1115',   99220.00,  8.86,  5.5),
  ('L2',   '1115', '1116',   99220.00,  8.86,  4.2),
  ('L3',   '1116', '1117',   99220.00,  8.86,  2.8),
  ('L4',   '1117', '1118',   99220.00,  8.86,  3.1),
  ('L5',   '1118', '1119',   99220.00,  8.86,  1.9),
  ('L6',   '1119', '1120',   99220.00,  8.86,  0.8),
  ('L7',   '1120', '1121',   99220.00,  8.86,  0.6),
  ('L8',   '1116', '1122',   22550.00,  4.84,  0.4),
  ('L9',   '1118', '1123',   22550.00,  4.84,  0.5),
  ('L10',  '1119', '1124',   22550.00,  4.84,  0.3),
  ('L11',  '1121', '1125',   22550.00,  4.84,  0.2)
ON CONFLICT (comp_id) DO NOTHING;

-- Sample results (Table II) stored in a dedicated table
CREATE TABLE IF NOT EXISTS component_results (
    comp_id             TEXT PRIMARY KEY REFERENCES network_components(comp_id),
    years_to_reinforce  NUMERIC,
    pv_gbp              NUMERIC
);

INSERT INTO component_results (comp_id, years_to_reinforce, pv_gbp) VALUES
  ('T1',   21.06, 121048.44),
  ('T2',   21.06, 121048.44),
  ('L1',    9.04,  54297.40),
  ('L2',   23.74,  20350.65),
  ('L3',   45.78,   4676.81),
  ('L4',   29.20,  14135.54),
  ('L5',  100.50,    121.41),
  ('L6',  500.00,      0.00),
  ('L7',   45.00,   4923.23),
  ('L8',  500.00,      0.00),
  ('L9',  500.00,      0.00),
  ('L10', 500.00,      0.00),
  ('L11', 500.00,      0.00)
ON CONFLICT (comp_id) DO UPDATE SET
  years_to_reinforce = EXCLUDED.years_to_reinforce,
  pv_gbp = EXCLUDED.pv_gbp;

-- Default DNO parameters
INSERT INTO dno_params (load_growth_pct, dg_growth_pct, discount_rate_pct)
VALUES (3.8, 11.4, 6.9)
ON CONFLICT DO NOTHING;

-- ── Node geometry (SRID 27700, tree layout centred near Birmingham) ──

-- BSP (301) at top
UPDATE network_nodes SET geom = ST_SetSRID(ST_MakePoint(430000, 285000), 27700) WHERE node_id = '301';
-- Primary substation (1100) below BSP
UPDATE network_nodes SET geom = ST_SetSRID(ST_MakePoint(430000, 283500), 27700) WHERE node_id = '1100';

-- Main trunk running south-west
UPDATE network_nodes SET geom = ST_SetSRID(ST_MakePoint(429200, 282500), 27700) WHERE node_id = '1115';
UPDATE network_nodes SET geom = ST_SetSRID(ST_MakePoint(428400, 281600), 27700) WHERE node_id = '1116';
UPDATE network_nodes SET geom = ST_SetSRID(ST_MakePoint(427600, 280800), 27700) WHERE node_id = '1117';
UPDATE network_nodes SET geom = ST_SetSRID(ST_MakePoint(426800, 280000), 27700) WHERE node_id = '1118';
UPDATE network_nodes SET geom = ST_SetSRID(ST_MakePoint(426000, 279200), 27700) WHERE node_id = '1119';
UPDATE network_nodes SET geom = ST_SetSRID(ST_MakePoint(425200, 278400), 27700) WHERE node_id = '1120';
UPDATE network_nodes SET geom = ST_SetSRID(ST_MakePoint(424400, 277600), 27700) WHERE node_id = '1121';

-- Lateral branches (east of trunk)
UPDATE network_nodes SET geom = ST_SetSRID(ST_MakePoint(429600, 281200), 27700) WHERE node_id = '1122';
UPDATE network_nodes SET geom = ST_SetSRID(ST_MakePoint(428000, 279600), 27700) WHERE node_id = '1123';
UPDATE network_nodes SET geom = ST_SetSRID(ST_MakePoint(427200, 278800), 27700) WHERE node_id = '1124';
UPDATE network_nodes SET geom = ST_SetSRID(ST_MakePoint(425600, 277200), 27700) WHERE node_id = '1125';

-- ── Component line geometry derived from node endpoints ──
UPDATE network_components c
SET geometry = ST_MakeLine(fn.geom, tn.geom)
FROM network_nodes fn, network_nodes tn
WHERE c.from_node = fn.node_id
  AND c.to_node   = tn.node_id
  AND fn.geom IS NOT NULL
  AND tn.geom IS NOT NULL;

COMMIT;

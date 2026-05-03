-- Seed: Essex BESS 100 MW + Slough DC 50 MW with full hierarchy.
-- Idempotent — re-running just upserts.

-- ---------- 1. twin_models stubs for sub-types (containment children) ----------
INSERT INTO twin_models (dtmi, display_name, version, parent_dtmi, raw, loaded_at)
VALUES
    ('dtmi:com:princeps:BessBlock;1',  'BESS Block',  1, 'dtmi:com:princeps:BESSUnit;1',  '{"_stub":"BESSBlock"}'::jsonb, NOW()),
    ('dtmi:com:princeps:BessRack;1',   'BESS Rack',   1, 'dtmi:com:princeps:BessBlock;1', '{"_stub":"BessRack"}'::jsonb,  NOW()),
    ('dtmi:com:princeps:BESSUnit;1',   'BESS Unit',   1, NULL,                            '{"_stub":"BESSUnit"}'::jsonb,  NOW()),
    ('dtmi:com:princeps:DataCentre;1', 'Data Centre', 1, NULL,                            '{"_stub":"DataCentre"}'::jsonb, NOW()),
    ('dtmi:com:princeps:DcHall;1',     'DC Hall',     1, 'dtmi:com:princeps:DataCentre;1','{"_stub":"DcHall"}'::jsonb,    NOW()),
    ('dtmi:com:princeps:DcAisle;1',    'DC Aisle',    1, 'dtmi:com:princeps:DcHall;1',    '{"_stub":"DcAisle"}'::jsonb,   NOW()),
    ('dtmi:com:princeps:Substation;1', 'Substation',  1, NULL,                            '{"_stub":"Substation"}'::jsonb, NOW())
ON CONFLICT (dtmi) DO NOTHING;


-- ---------- 2. Essex BESS 100 MW / 200 MWh — twin_instances ----------
INSERT INTO twin_instances (rid, dtmi, properties, geom, last_telemetry_at, created_at, updated_at) VALUES
  -- Root unit
  ('rid.princeps.production.bess_unit.essex-100',
   'dtmi:com:princeps:BESSUnit;1',
   '{
      "name":"Essex BESS 100 MW",
      "vendor":"Tesla","model":"Megapack 2 XL",
      "ratedPowerMw":100,"energyCapacityMwh":200,
      "chemistry":"LFP",
      "numBlocks":2,"numRacksPerBlock":12,"numModulesPerRack":16,"numCellsPerModule":104,
      "nominalDcBusV":1300,"fireSuppressionType":"NOVEC_1230",
      "gridCode":"G99 v1.7","commercialOpsDate":"2024-09-15",
      "stateOfChargePct":58.4,"stateOfHealthPct":97.1,
      "activePowerMw":-42.0,"reactivePowerMvar":2.5,
      "ambientTempC":18.6,"maxCellTempC":31.4,"minCellTempC":24.1,
      "maxCellVoltageV":3.42,"minCellVoltageV":3.34,"cellVoltageImbalancePct":2.1,
      "bmsState":"running","contactorState":"closed","groundFaultCurrentA":0.04,
      "cycleCountTotal":1421,"coolantFlowLpm":840,"fireDetectorOk":true
   }'::jsonb,
   ST_GeomFromText('POINT(572400 191800)', 27700),
   NOW(), NOW(), NOW()),

  -- 2 Blocks
  ('rid.princeps.production.bess_block.essex-100-blk1',
   'dtmi:com:princeps:BessBlock;1',
   '{"blockId":"BLK-1","ratedPowerMw":50,"energyCapacityMwh":100,"numRacks":12,
     "stateOfChargePct":58.7,"activePowerMw":-21.0,
     "containerInletTempC":17.9,"containerExhaustTempC":24.3,
     "fireDetectorOk":true,"gasDetectorPpm":0}'::jsonb,
   ST_GeomFromText('POINT(572395 191795)', 27700), NOW(), NOW(), NOW()),
  ('rid.princeps.production.bess_block.essex-100-blk2',
   'dtmi:com:princeps:BessBlock;1',
   '{"blockId":"BLK-2","ratedPowerMw":50,"energyCapacityMwh":100,"numRacks":12,
     "stateOfChargePct":58.1,"activePowerMw":-21.0,
     "containerInletTempC":18.2,"containerExhaustTempC":25.1,
     "fireDetectorOk":true,"gasDetectorPpm":0}'::jsonb,
   ST_GeomFromText('POINT(572410 191795)', 27700), NOW(), NOW(), NOW()),

  -- 4 Racks (sample — 2 per block)
  ('rid.princeps.production.bess_rack.essex-100-blk1-r01',
   'dtmi:com:princeps:BessRack;1',
   '{"rackId":"BLK1-R01","numModules":16,"nominalVoltageV":1300,
     "stateOfChargePct":58.9,"voltageV":1304.2,"currentA":-1612,
     "maxModuleTempC":29.8,"minModuleTempC":25.2,"imbalancePct":1.4,"contactorState":"closed"}'::jsonb,
   NULL, NOW(), NOW(), NOW()),
  ('rid.princeps.production.bess_rack.essex-100-blk1-r07',
   'dtmi:com:princeps:BessRack;1',
   '{"rackId":"BLK1-R07","numModules":16,"nominalVoltageV":1300,
     "stateOfChargePct":58.2,"voltageV":1300.7,"currentA":-1610,
     "maxModuleTempC":31.4,"minModuleTempC":26.7,"imbalancePct":3.1,"contactorState":"closed"}'::jsonb,
   NULL, NOW(), NOW(), NOW()),
  ('rid.princeps.production.bess_rack.essex-100-blk2-r03',
   'dtmi:com:princeps:BessRack;1',
   '{"rackId":"BLK2-R03","numModules":16,"nominalVoltageV":1300,
     "stateOfChargePct":58.0,"voltageV":1301.5,"currentA":-1608,
     "maxModuleTempC":28.6,"minModuleTempC":24.9,"imbalancePct":1.8,"contactorState":"closed"}'::jsonb,
   NULL, NOW(), NOW(), NOW()),
  ('rid.princeps.production.bess_rack.essex-100-blk2-r11',
   'dtmi:com:princeps:BessRack;1',
   '{"rackId":"BLK2-R11","numModules":16,"nominalVoltageV":1300,
     "stateOfChargePct":58.4,"voltageV":1303.1,"currentA":-1612,
     "maxModuleTempC":30.1,"minModuleTempC":25.5,"imbalancePct":2.0,"contactorState":"closed"}'::jsonb,
   NULL, NOW(), NOW(), NOW())
ON CONFLICT (rid) DO UPDATE SET properties=EXCLUDED.properties, updated_at=NOW();


-- ---------- 3. BESS containment relationships ----------
INSERT INTO twin_relationships (rid, from_rid, to_rid, rel_name, properties) VALUES
  ('rid.princeps.production.twin_rel.essex-100-contains-blk1',
    'rid.princeps.production.bess_unit.essex-100',
    'rid.princeps.production.bess_block.essex-100-blk1',
    'containsBlock', '{}'::jsonb),
  ('rid.princeps.production.twin_rel.essex-100-contains-blk2',
    'rid.princeps.production.bess_unit.essex-100',
    'rid.princeps.production.bess_block.essex-100-blk2',
    'containsBlock', '{}'::jsonb),
  ('rid.princeps.production.twin_rel.essex-100-blk1-contains-r01',
    'rid.princeps.production.bess_block.essex-100-blk1',
    'rid.princeps.production.bess_rack.essex-100-blk1-r01',
    'containsRack', '{}'::jsonb),
  ('rid.princeps.production.twin_rel.essex-100-blk1-contains-r07',
    'rid.princeps.production.bess_block.essex-100-blk1',
    'rid.princeps.production.bess_rack.essex-100-blk1-r07',
    'containsRack', '{}'::jsonb),
  ('rid.princeps.production.twin_rel.essex-100-blk2-contains-r03',
    'rid.princeps.production.bess_block.essex-100-blk2',
    'rid.princeps.production.bess_rack.essex-100-blk2-r03',
    'containsRack', '{}'::jsonb),
  ('rid.princeps.production.twin_rel.essex-100-blk2-contains-r11',
    'rid.princeps.production.bess_block.essex-100-blk2',
    'rid.princeps.production.bess_rack.essex-100-blk2-r11',
    'containsRack', '{}'::jsonb)
ON CONFLICT (rid) DO NOTHING;


-- ---------- 4. Slough DC 50 MW — twin_instances ----------
INSERT INTO twin_instances (rid, dtmi, properties, geom, last_telemetry_at, created_at, updated_at) VALUES
  ('rid.princeps.production.data_centre.slough-50',
   'dtmi:com:princeps:DataCentre;1',
   '{"name":"Slough DC 50 MW","operator":"Hyperscaler X","tier":"III",
     "itLoadMw":50,"totalGridDrawMw":68,"puEDesign":1.36,"wuEDesign":0.42,
     "numHalls":2,"numPodsPerHall":4,"numAislesPerPod":3,"numRacksPerAisle":24,"rackPowerKw":18,
     "coolingType":"CHILLED_WATER","ttiTotalMinutesYtd":3.7,
     "currentItLoadMw":47.2,"currentTotalDrawMw":63.4,"currentPue":1.343,
     "ambientDbTempC":18.4,"outdoorWbTempC":15.1,
     "chilledWaterSupplyTempC":12.0,"chilledWaterReturnTempC":18.4,"chilledWaterFlowLps":740,
     "coolingPowerMw":11.2,"upsBatteryHealthPct":94.6,"upsLoadPct":71.2,
     "atsPositionA":true,"gensetTestDueDays":18,"gridFrequencyHz":50.01,
     "waterUsageM3PerMwh":0.39,"carbonIntensityGCo2PerKwh":214}'::jsonb,
   ST_GeomFromText('POINT(498100 178300)', 27700), NOW(), NOW(), NOW()),

  ('rid.princeps.production.dc_hall.slough-50-h1',
   'dtmi:com:princeps:DcHall;1',
   '{"hallId":"HALL-1","itLoadMw":24.5,"currentItLoadMw":23.7,
     "puEHall":1.35,"hotspots":1}'::jsonb,
   NULL, NOW(), NOW(), NOW()),
  ('rid.princeps.production.dc_hall.slough-50-h2',
   'dtmi:com:princeps:DcHall;1',
   '{"hallId":"HALL-2","itLoadMw":25.5,"currentItLoadMw":23.5,
     "puEHall":1.34,"hotspots":0}'::jsonb,
   NULL, NOW(), NOW(), NOW()),

  ('rid.princeps.production.dc_aisle.slough-50-h1-a01',
   'dtmi:com:princeps:DcAisle;1',
   '{"aisleId":"H1-A01","numRacks":24,"loadKw":380,
     "inletTempC":21.4,"exhaustTempC":35.6,"hotspot":false}'::jsonb,
   NULL, NOW(), NOW(), NOW()),
  ('rid.princeps.production.dc_aisle.slough-50-h1-a02',
   'dtmi:com:princeps:DcAisle;1',
   '{"aisleId":"H1-A02","numRacks":24,"loadKw":412,
     "inletTempC":22.1,"exhaustTempC":38.9,"hotspot":true}'::jsonb,
   NULL, NOW(), NOW(), NOW()),
  ('rid.princeps.production.dc_aisle.slough-50-h2-a01',
   'dtmi:com:princeps:DcAisle;1',
   '{"aisleId":"H2-A01","numRacks":24,"loadKw":368,
     "inletTempC":21.7,"exhaustTempC":35.1,"hotspot":false}'::jsonb,
   NULL, NOW(), NOW(), NOW()),
  ('rid.princeps.production.dc_aisle.slough-50-h2-a02',
   'dtmi:com:princeps:DcAisle;1',
   '{"aisleId":"H2-A02","numRacks":24,"loadKw":376,
     "inletTempC":21.8,"exhaustTempC":35.3,"hotspot":false}'::jsonb,
   NULL, NOW(), NOW(), NOW())
ON CONFLICT (rid) DO UPDATE SET properties=EXCLUDED.properties, updated_at=NOW();


-- ---------- 5. DC containment relationships ----------
INSERT INTO twin_relationships (rid, from_rid, to_rid, rel_name, properties) VALUES
  ('rid.princeps.production.twin_rel.slough-50-contains-h1',
    'rid.princeps.production.data_centre.slough-50',
    'rid.princeps.production.dc_hall.slough-50-h1',
    'containsHall', '{}'::jsonb),
  ('rid.princeps.production.twin_rel.slough-50-contains-h2',
    'rid.princeps.production.data_centre.slough-50',
    'rid.princeps.production.dc_hall.slough-50-h2',
    'containsHall', '{}'::jsonb),
  ('rid.princeps.production.twin_rel.slough-50-h1-a01',
    'rid.princeps.production.dc_hall.slough-50-h1',
    'rid.princeps.production.dc_aisle.slough-50-h1-a01',
    'containsAisle', '{}'::jsonb),
  ('rid.princeps.production.twin_rel.slough-50-h1-a02',
    'rid.princeps.production.dc_hall.slough-50-h1',
    'rid.princeps.production.dc_aisle.slough-50-h1-a02',
    'containsAisle', '{}'::jsonb),
  ('rid.princeps.production.twin_rel.slough-50-h2-a01',
    'rid.princeps.production.dc_hall.slough-50-h2',
    'rid.princeps.production.dc_aisle.slough-50-h2-a01',
    'containsAisle', '{}'::jsonb),
  ('rid.princeps.production.twin_rel.slough-50-h2-a02',
    'rid.princeps.production.dc_hall.slough-50-h2',
    'rid.princeps.production.dc_aisle.slough-50-h2-a02',
    'containsAisle', '{}'::jsonb)
ON CONFLICT (rid) DO NOTHING;

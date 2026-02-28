// CIM Bus-Branch Graph Schema for Neo4j
// IEC 61970 topology: Asset → Terminal → ConnectivityNode
//
// Run manually: cypher-shell -u neo4j -p princeps < scripts/db/init_graph_schema.cypher
// Or via Neo4j Browser at http://localhost:7474
//
// These constraints are also created programmatically by
// utils/graph_topology.py ensure_constraints().

// --- Uniqueness constraints ---
CREATE CONSTRAINT asset_id IF NOT EXISTS
  FOR (a:Asset) REQUIRE a.id IS UNIQUE;

CREATE CONSTRAINT terminal_id IF NOT EXISTS
  FOR (t:Terminal) REQUIRE t.id IS UNIQUE;

CREATE CONSTRAINT cnode_id IF NOT EXISTS
  FOR (c:ConnectivityNode) REQUIRE c.id IS UNIQUE;

// --- Performance indexes ---
CREATE INDEX asset_container IF NOT EXISTS
  FOR (a:Asset) ON (a.containerId);

CREATE INDEX asset_voltage IF NOT EXISTS
  FOR (a:Asset) ON (a.voltageKv);

CREATE INDEX asset_region IF NOT EXISTS
  FOR (a:Asset) ON (a.region);

CREATE INDEX asset_type IF NOT EXISTS
  FOR (a:Asset) ON (a.assetType);

// ===========================================================================
// Regulatory Intelligence Extension
// ===========================================================================

// --- Uniqueness constraints ---
CREATE CONSTRAINT developer_name IF NOT EXISTS
  FOR (d:Developer) REQUIRE d.name IS UNIQUE;

CREATE CONSTRAINT spv_id IF NOT EXISTS
  FOR (s:SPV) REQUIRE s.id IS UNIQUE;

CREATE CONSTRAINT planning_ref IF NOT EXISTS
  FOR (p:PlanningApplication) REQUIRE p.ref IS UNIQUE;

CREATE CONSTRAINT grid_conn_id IF NOT EXISTS
  FOR (g:GridConnection) REQUIRE g.id IS UNIQUE;

CREATE CONSTRAINT dno_zone_code IF NOT EXISTS
  FOR (z:DNOZone) REQUIRE z.code IS UNIQUE;

// --- Performance indexes ---
CREATE INDEX developer_search IF NOT EXISTS
  FOR (d:Developer) ON (d.name);

CREATE INDEX spv_developer IF NOT EXISTS
  FOR (s:SPV) ON (s.developer);

// --- Relationship patterns ---
// (:Developer)-[:DEVELOPS]->(:SPV)
// (:SPV)-[:HAS_PLANNING]->(:PlanningApplication)
// (:PlanningApplication)-[:CONNECTS_VIA]->(:GridConnection)
// (:GridConnection)-[:CONNECTS_TO]->(:Asset:Substation)
// (:Asset:Substation)-[:IN_ZONE]->(:DNOZone)

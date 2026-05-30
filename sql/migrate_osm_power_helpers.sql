-- ─────────────────────────────────────────────────────────────────────────────
-- migrate_osm_power_helpers.sql — port of OpenInfraMap's PostgreSQL helpers
-- so SQL-level voltage / power / semicolon-list parsing matches the upstream
-- imposm pipeline.
--
-- Sourced from
--   https://github.com/openinframap/openinframap/blob/main/schema/functions.sql
-- BSD-3-Clause. We port only the functions referenced from osm_power_infra.py
-- (the OIM tile-rendering helpers like simplify_boundary, area_sqm, etc. are
-- omitted — Princeps doesn't render vector tiles).
--
-- Idempotent: every function is CREATE OR REPLACE so re-running on warm starts
-- is safe.
-- ─────────────────────────────────────────────────────────────────────────────

-- Convert a power-tag string ("50 MW", "10kW", "1.5 GW") to numeric watts.
CREATE OR REPLACE FUNCTION convert_power(value TEXT) RETURNS NUMERIC
PARALLEL SAFE
IMMUTABLE
RETURNS NULL ON NULL INPUT
AS $$
DECLARE
  parts TEXT[];
  val NUMERIC;
BEGIN
  parts := regexp_matches(upper(value), '([0-9]+[\.,]?[0-9]*)[ ]?([KMG]?W)?', '');
  val := replace(parts[1], ',', '.')::NUMERIC;
  IF parts[2] = 'KW' THEN
    val := val * 1e3;
  ELSIF parts[2] = 'MW' THEN
    val := val * 1e6;
  ELSIF parts[2] = 'GW' THEN
    val := val * 1e9;
  ELSE
    -- No units → treat as invalid (upstream behaviour).
    val := NULL;
  END IF;
  RETURN val;
END
$$ LANGUAGE plpgsql;

-- Parse a possibly-formatted text integer ("400000") into an integer.
CREATE OR REPLACE FUNCTION convert_integer(value TEXT) RETURNS INTEGER
IMMUTABLE
PARALLEL SAFE
RETURNS NULL ON NULL INPUT
AS $$
DECLARE
  parts TEXT[];
BEGIN
    parts := regexp_matches(value, '^([0-9]{1,9})$', '');
    RETURN parts[1]::INTEGER;
EXCEPTION WHEN OTHERS THEN
    RETURN NULL;
END
$$ LANGUAGE plpgsql;

-- Explode a semicolon-delimited string of integers into rows.
CREATE OR REPLACE FUNCTION convert_integer_list(value TEXT) RETURNS TABLE (value INTEGER)
IMMUTABLE
PARALLEL SAFE
RETURNS NULL ON NULL INPUT
AS $$
    SELECT convert_integer(v) AS voltage
        FROM regexp_split_to_table(value, ';') AS v
        WHERE convert_integer(v) IS NOT NULL;
$$ LANGUAGE SQL;

-- Take the highest voltage from a semicolon-delimited list (volts).
CREATE OR REPLACE FUNCTION convert_voltage(value TEXT) RETURNS NUMERIC
IMMUTABLE
PARALLEL SAFE
RETURNS NULL ON NULL INPUT
AS $$
  SELECT v::NUMERIC FROM convert_integer_list(value) v ORDER BY v DESC LIMIT 1;
$$ LANGUAGE SQL;

-- Nth element of a semicolon-delimited list (1-indexed).
CREATE OR REPLACE FUNCTION nth_semi(input TEXT, index INTEGER) RETURNS TEXT
PARALLEL SAFE
IMMUTABLE
AS $$
DECLARE
    parts TEXT[];
BEGIN
    parts := string_to_array(input, ';');
    RETURN parts[index];
END
$$ LANGUAGE plpgsql;

-- First element of a semicolon-delimited list (sugar for nth_semi(.,1)).
CREATE OR REPLACE FUNCTION first_semi(input TEXT) RETURNS TEXT
PARALLEL SAFE
IMMUTABLE
AS $$
BEGIN
    RETURN nth_semi(input, 1);
END
$$ LANGUAGE plpgsql;

-- Angle of the underlying power line at a given point (degrees from north).
-- Used to rotate switch / transformer icons so they sit perpendicular to the
-- line they're attached to. Returns NULL if no line passes within 1m.
CREATE OR REPLACE FUNCTION power_line_angle(point GEOMETRY)
    RETURNS DOUBLE PRECISION
    LANGUAGE plpgsql
    IMMUTABLE STRICT
    PARALLEL SAFE
    AS $$
DECLARE
    angle DOUBLE PRECISION;
BEGIN
    -- Interpolate two points onto the line at 20% and 80% of the length, and
    -- calculate the azimuth between them.
    SELECT ST_Azimuth(
               ST_LineInterpolatePoint(line.geometry, 0.2),
               ST_LineInterpolatePoint(line.geometry, 0.8)
           ) / (2 * PI()) * 360 INTO angle
    FROM (
        -- Pull lines within a 1m radius of the point. Clip to a 5m buffer
        -- so the interpolation isn't dominated by long off-axis lines.
        SELECT ST_Intersection(l.geometry, ST_Buffer(point, 5)) AS geometry
        FROM osm_power_line l
        WHERE ST_Intersects(ST_Buffer(point, 1), l.geometry)
        ORDER BY (l.line_type = 'busbar') ASC -- prefer non-busbar
        LIMIT 5
    ) AS line
    WHERE ST_GeometryType(line.geometry) = 'ST_LineString' LIMIT 1;
    RETURN angle;
END $$;
</content>
</invoke>
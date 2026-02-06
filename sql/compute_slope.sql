-- Compute slope raster (degrees) from an elevation raster table.
-- Prerequisite: dem_elev table loaded via raster2pgsql:
--   raster2pgsql -s 27700 -I -C -M elevation.tif dem_elev | psql $DATABASE_URL
--
-- The DEM should be in a projected CRS (EPSG:27700) so that horizontal and
-- vertical units match (both metres). If using EPSG:4326, set scale ≈ 111120.

DROP TABLE IF EXISTS dem_slope;

CREATE TABLE dem_slope AS
SELECT rid,
       ST_Slope(rast, 1, '32BF', 'DEGREES', 1.0, FALSE) AS rast
FROM dem_elev
WHERE rast IS NOT NULL;

CREATE INDEX dem_slope_rast_gist ON dem_slope USING GIST (ST_ConvexHull(rast));
ANALYZE dem_slope;

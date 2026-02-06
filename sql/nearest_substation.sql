-- Compute nearest substation for every parcel using PostGIS KNN.
-- Run after both dno_substations and parcels are loaded.

-- 1. Ensure centroids exist
UPDATE parcels
SET centroid = ST_Centroid(geometry)
WHERE centroid IS NULL;

-- 2. KNN lateral join + update
WITH nearest AS (
    SELECT p.parcel_id,
           s.sub_id,
           s.capacity_kw,
           ST_Distance(p.centroid, s.geometry) AS dist_m
    FROM parcels p
    JOIN LATERAL (
        SELECT sub_id, capacity_kw, geometry
        FROM dno_substations
        ORDER BY p.centroid <-> geometry
        LIMIT 1
    ) s ON true
)
UPDATE parcels
SET nearest_substation_id   = n.sub_id,
    distance_to_sub_km      = n.dist_m / 1000.0,
    nearest_sub_capacity_kw = n.capacity_kw
FROM nearest n
WHERE parcels.parcel_id = n.parcel_id;

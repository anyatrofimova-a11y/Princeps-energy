#!/usr/bin/env bash
# process_dem_and_tiles.sh — DEM tile generation pipeline
#
# Downloads a DEM tile, clips to a bounding box, computes slope,
# and generates XYZ map tiles for the frontend.
#
# Usage:
#   ./scripts/process_dem_and_tiles.sh <parcel_id> <minx> <miny> <maxx> <maxy> [out_dir]
#
# Requirements: GDAL (gdalwarp, gdaldem, gdal2tiles.py)
# CRS: EPSG:27700 (British National Grid)

set -euo pipefail

PARCEL_ID="${1:?Usage: $0 <parcel_id> <minx> <miny> <maxx> <maxy> [out_dir]}"
MINX="${2:?}"
MINY="${3:?}"
MAXX="${4:?}"
MAXY="${5:?}"
OUT_DIR="${6:-/tmp/feasi_data}"

DEM_SRC="${DEM_SOURCE:-/tmp/uk_dem_50m.tif}"  # pre-downloaded national DEM
DEM_CLIPPED="${OUT_DIR}/${PARCEL_ID}_dem_27700.tif"
SLOPE_TIF="${OUT_DIR}/${PARCEL_ID}_slope.tif"
SLOPE_COLOR="${OUT_DIR}/${PARCEL_ID}_slope_color.tif"
TILES_DIR="${OUT_DIR}/tiles/${PARCEL_ID}"

mkdir -p "${OUT_DIR}" "${TILES_DIR}"

echo "==> Clipping DEM to bbox [${MINX}, ${MINY}, ${MAXX}, ${MAXY}]"
gdalwarp \
  -s_srs EPSG:27700 -t_srs EPSG:27700 \
  -te "${MINX}" "${MINY}" "${MAXX}" "${MAXY}" \
  -r bilinear \
  -overwrite \
  "${DEM_SRC}" "${DEM_CLIPPED}"

echo "==> Computing slope (degrees)"
gdaldem slope "${DEM_CLIPPED}" "${SLOPE_TIF}" -compute_edges

echo "==> Applying colour ramp for visualisation"
# Create a temporary colour ramp file
RAMP=$(mktemp)
cat > "${RAMP}" <<'COLORRAMP'
0   255 255 255
2   144 238 144
5   255 255 0
10  255 165 0
15  255 69  0
25  139 0   0
90  80  0   0
COLORRAMP

gdaldem color-relief "${SLOPE_TIF}" "${RAMP}" "${SLOPE_COLOR}"
rm -f "${RAMP}"

echo "==> Generating XYZ tiles (zoom 10-16)"
gdal2tiles.py \
  -z 10-16 \
  -w none \
  -r bilinear \
  --processes=4 \
  "${SLOPE_COLOR}" "${TILES_DIR}"

echo "==> Done. Tiles at: ${TILES_DIR}"
echo "    DEM: ${DEM_CLIPPED}"
echo "    Slope: ${SLOPE_TIF}"

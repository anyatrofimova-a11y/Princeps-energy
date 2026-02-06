#!/usr/bin/env bash
set -euo pipefail

PARCEL_ID=${1:?parcel id required}
MINX=${2:?}
MINY=${3:?}
MAXX=${4:?}
MAXY=${5:?}

OUTDIR=/tmp/feasi_data/${PARCEL_ID}
mkdir -p "${OUTDIR}"

VIBE_BASE="https://vibe.ornl.gov"  # adapt if different
LAYER="DEM"

RAW_TIF="${OUTDIR}/${PARCEL_ID}_raw.tif"
CLIPPED="${OUTDIR}/${PARCEL_ID}_dem_27700.tif"
SLOPE="${OUTDIR}/${PARCEL_ID}_slope.tif"
TILE_DIR="${OUTDIR}/tiles"

echo "Fetching VIBE DEM (you may need to update the API call)..."
curl -G "${VIBE_BASE}/api/export" \
  --data-urlencode "layer=${LAYER}" \
  --data-urlencode "bbox=${MINX},${MINY},${MAXX},${MAXY}" \
  --data-urlencode "srs=EPSG:27700" \
  --data-urlencode "format=GTiff" \
  -o "${RAW_TIF}"

echo "Clipping / reprojecting with gdalwarp..."
gdalwarp -t_srs EPSG:27700 -te ${MINX} ${MINY} ${MAXX} ${MAXY} -tr 2 2 -r bilinear -of GTiff "${RAW_TIF}" "${CLIPPED}"

echo "Computing slope..."
gdaldem slope "${CLIPPED}" "${SLOPE}" -p

echo "Generating tiles with gdal2tiles.py (0-16)..."
gdal2tiles.py -z 0-16 -r bilinear "${SLOPE}" "${TILE_DIR}"

echo "Done: tiles in ${TILE_DIR}"

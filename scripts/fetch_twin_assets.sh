#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# fetch_twin_assets.sh — Princeps 3D Twin asset downloader
# -----------------------------------------------------------------------------
# Reads feasi-frontend/public/assets/twin3d/MANIFEST.csv, fetches each model
# from its vendor URL into raw/<vendor>/<slug>.glb, draco-compresses with
# gltfpack, and writes the compressed output to the target_path column.
#
# Idempotent: skips any file that already exists at its target_path unless
# FORCE=1 is set.
#
# Sandbox-safe: if curl cannot reach a host (network blocked, DNS refused),
# the script prints a warning and falls through to
# scripts/generate_placeholder_glbs.py, which guarantees every MANIFEST row
# has SOMETHING loadable at target_path.
#
# Usage:
#   bash scripts/fetch_twin_assets.sh          # normal
#   FORCE=1 bash scripts/fetch_twin_assets.sh  # re-download everything
#   SKIP_COMPRESS=1 bash ...                   # keep uncompressed
#
# Dependencies (install on maintainer machine, NOT required in CI):
#   - curl (any)
#   - gltfpack (npm i -g gltfpack, OR brew install gltfpack)
#   - python3 with trimesh / pygltflib for placeholder generation
# -----------------------------------------------------------------------------

set -euo pipefail

# Resolve repo root regardless of cwd.
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_ROOT="$( cd "${SCRIPT_DIR}/.." && pwd )"

ASSET_ROOT="${REPO_ROOT}/feasi-frontend/public/assets/twin3d"
MANIFEST="${ASSET_ROOT}/MANIFEST.csv"
RAW_DIR="${ASSET_ROOT}/raw"
PLACEHOLDER_SCRIPT="${REPO_ROOT}/scripts/generate_placeholder_glbs.py"

FORCE="${FORCE:-0}"
SKIP_COMPRESS="${SKIP_COMPRESS:-0}"

# ----- pretty printing -------------------------------------------------------
c_reset="\033[0m"
c_dim="\033[2m"
c_gold="\033[33m"
c_green="\033[32m"
c_red="\033[31m"

info()   { printf "%b[twin-assets]%b %s\n" "${c_gold}" "${c_reset}" "$*"; }
ok()     { printf "%b[twin-assets]%b %s\n" "${c_green}" "${c_reset}" "$*"; }
warn()   { printf "%b[twin-assets WARN]%b %s\n" "${c_red}" "${c_reset}" "$*"; }

# ----- dependency checks -----------------------------------------------------
if [[ ! -f "${MANIFEST}" ]]; then
  warn "Manifest not found: ${MANIFEST}"
  exit 1
fi

HAS_CURL=1; command -v curl >/dev/null 2>&1 || HAS_CURL=0
HAS_GLTFPACK=1; command -v gltfpack >/dev/null 2>&1 || HAS_GLTFPACK=0
HAS_PY=1; command -v python3 >/dev/null 2>&1 || HAS_PY=0

if [[ "${HAS_CURL}" -eq 0 ]]; then
  warn "curl not found — downloads will be skipped. Placeholders only."
fi
if [[ "${HAS_GLTFPACK}" -eq 0 ]]; then
  warn "gltfpack not found — compression skipped. Raw .glb will be copied to target."
  SKIP_COMPRESS=1
fi

mkdir -p "${RAW_DIR}/sketchfab" "${RAW_DIR}/kenney" "${RAW_DIR}/poly_pizza" "${RAW_DIR}/nrel"

# ----- placeholder fallback --------------------------------------------------
ensure_placeholder() {
  local target_rel="$1"
  local target_abs="${ASSET_ROOT}/${target_rel}"
  if [[ -f "${target_abs}" && "${FORCE}" != "1" ]]; then
    return 0
  fi
  if [[ "${HAS_PY}" -eq 1 && -f "${PLACEHOLDER_SCRIPT}" ]]; then
    info "  ↻ generating placeholder for ${target_rel}"
    python3 "${PLACEHOLDER_SCRIPT}" --only "${target_rel}" || {
      warn "  placeholder script failed — writing empty stub"
      mkdir -p "$(dirname "${target_abs}")"
      : > "${target_abs}"
    }
  else
    warn "  python3/placeholder script missing — writing empty stub"
    mkdir -p "$(dirname "${target_abs}")"
    : > "${target_abs}"
  fi
}

# ----- CSV loop --------------------------------------------------------------
# MANIFEST.csv columns: asset_id,vendor,source_url,licence,target_path,status,notes
tail -n +2 "${MANIFEST}" | while IFS=, read -r asset_id vendor source_url licence target_path status notes; do
  # strip potential quotes
  asset_id="${asset_id//\"/}"
  vendor="${vendor//\"/}"
  source_url="${source_url//\"/}"
  licence="${licence//\"/}"
  target_path="${target_path//\"/}"

  [[ -z "${asset_id}" ]] && continue
  info "─── ${asset_id} (${licence})"

  target_abs="${ASSET_ROOT}/${target_path}"
  if [[ -f "${target_abs}" && "${FORCE}" != "1" ]]; then
    ok "  ✓ exists — skip"
    continue
  fi

  # Normalise vendor for raw dir
  vdir=$(printf "%s" "${vendor}" | tr '[:upper:]' '[:lower:]')
  case "${vdir}" in
    sketchfab) raw_sub="sketchfab" ;;
    kenney)    raw_sub="kenney" ;;
    poly*|polypizza|poly_pizza) raw_sub="poly_pizza" ;;
    nrel)      raw_sub="nrel" ;;
    *)         raw_sub="misc"; mkdir -p "${RAW_DIR}/misc" ;;
  esac

  slug=$(printf "%s" "${asset_id}" | tr '.' '_' | tr '/' '_')
  raw_path="${RAW_DIR}/${raw_sub}/${slug}.glb"

  # Skip download if source URL is a placeholder
  if [[ "${source_url}" == "<tbd>" || -z "${source_url}" ]]; then
    warn "  source_url is <tbd> — placeholder only"
    ensure_placeholder "${target_path}"
    continue
  fi

  # Sketchfab/Kenney browse pages do NOT serve a direct .glb — they require
  # the user to click through and accept licence. We treat them as informational
  # URLs and always fall back to placeholder for now. When the team has
  # manually downloaded the real file to raw/, this same script will find it
  # and compress it on the next run.
  if [[ "${HAS_CURL}" -eq 1 && ! -f "${raw_path}" ]]; then
    case "${source_url}" in
      *\.glb|*\.gltf)
        info "  ↓ curl ${source_url}"
        if ! curl -sSLf -o "${raw_path}" "${source_url}"; then
          warn "  download failed (offline / licence wall)"
          rm -f "${raw_path}"
        fi
        ;;
      *)
        info "  ↪ vendor page — manual download required; see MANIFEST notes"
        ;;
    esac
  fi

  # If we now have a raw file, compress it; else placeholder.
  if [[ -f "${raw_path}" ]]; then
    mkdir -p "$(dirname "${target_abs}")"
    if [[ "${SKIP_COMPRESS}" == "1" ]]; then
      cp "${raw_path}" "${target_abs}"
      ok "  ✓ copied (no compression)"
    else
      if gltfpack -i "${raw_path}" -o "${target_abs}" -cc >/dev/null 2>&1; then
        ok "  ✓ compressed → ${target_path}"
      else
        warn "  gltfpack failed — copying raw"
        cp "${raw_path}" "${target_abs}"
      fi
    fi
  else
    ensure_placeholder "${target_path}"
  fi
done

info "Done. Review ${ASSET_ROOT}/ and update LICENSES.md with author + retrieved_date."

#!/usr/bin/env bash
# Universal setup-host zip packager for PSXRecomp game repos.
#
# Stages the host exe, title sources, filtered psxrecomp/ + recomp-ui/, then
# finishes with stage_setup_sdk.sh (emitters, OpenBIOS, MinGW DLLs).
# Portable cmake/clang is NOT embedded by default — RetComM / the setup wizard
# download cmake-clang-v1 from retcomm-toolchains (or accept an offline zip).
#
# Usage (from game repo root):
#   psxrecomp/tools/package_setup_host.sh \
#     --build-dir build-ci \
#     --artifact linux-x64 \
#     --zip-prefix bpe \
#     --exe-name Bomberman_Party_Edition_Recompiled \
#     --display-name "Bomberman Party Edition Recompiled" \
#     --recompiler-build build-recompiler \
#     [--project-file REL]... [--project-dir REL]... \
#     [--disc-hint "your legally owned disc"] \
#     [--version-env BPE_RELEASE_VERSION] \
#     [--embed-toolchain]   # optional: copy PSXRECOMP_TOOLCHAIN_DIR into zip
#
# Env:
#   RELEASE_VERSION / <version-env> / VERSION file
#   PSXRECOMP_TOOLCHAIN_DIR | TOOLCHAIN_DIR | BPE_TOOLCHAIN_DIR  (only with --embed-toolchain)
#   PSXRECOMP_EMBED_TOOLCHAIN=1  same as --embed-toolchain
#   PSXRECOMP_RUNTIME_BIN_DIR | BPE_RUNTIME_BIN_DIR  (Windows MinGW DLL search)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(pwd)"

BUILD_DIR=""
ARTIFACT=""
ZIP_PREFIX=""
EXE_NAME=""
DISPLAY_NAME=""
RECOMPILER_BUILD="build-recompiler"
VERSION_ENV="RELEASE_VERSION"
DISC_HINT="your legally owned game disc"
PROJECT_FILES=()
PROJECT_DIRS=()
RUNTIME_BIN_DIR="${PSXRECOMP_RUNTIME_BIN_DIR:-${BPE_RUNTIME_BIN_DIR:-/usr/x86_64-w64-mingw32/bin}}"
EMBED_TOOLCHAIN=0
if [[ "${PSXRECOMP_EMBED_TOOLCHAIN:-0}" == "1" ]]; then
  EMBED_TOOLCHAIN=1
fi

usage() {
  sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
  exit 2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage ;;
    --build-dir) BUILD_DIR="${2:?}"; shift 2 ;;
    --artifact) ARTIFACT="${2:?}"; shift 2 ;;
    --zip-prefix) ZIP_PREFIX="${2:?}"; shift 2 ;;
    --exe-name) EXE_NAME="${2:?}"; shift 2 ;;
    --display-name) DISPLAY_NAME="${2:?}"; shift 2 ;;
    --recompiler-build) RECOMPILER_BUILD="${2:?}"; shift 2 ;;
    --version-env) VERSION_ENV="${2:?}"; shift 2 ;;
    --disc-hint) DISC_HINT="${2:?}"; shift 2 ;;
    --project-file) PROJECT_FILES+=("${2:?}"); shift 2 ;;
    --project-dir) PROJECT_DIRS+=("${2:?}"); shift 2 ;;
    --runtime-bin) RUNTIME_BIN_DIR="${2:?}"; shift 2 ;;
    --root) ROOT="${2:?}"; shift 2 ;;
    --embed-toolchain) EMBED_TOOLCHAIN=1; shift ;;
    --no-embed-toolchain) EMBED_TOOLCHAIN=0; shift ;;
    *)
      echo "error: unknown arg: $1" >&2
      usage
      ;;
  esac
done

if [[ -z "${BUILD_DIR}" || -z "${ARTIFACT}" || -z "${ZIP_PREFIX}" || -z "${EXE_NAME}" ]]; then
  echo "error: --build-dir, --artifact, --zip-prefix, and --exe-name are required" >&2
  usage
fi
if [[ -z "${DISPLAY_NAME}" ]]; then
  DISPLAY_NAME="${EXE_NAME}"
fi

ROOT="$(cd "${ROOT}" && pwd)"
if [[ -d "${ROOT}/${BUILD_DIR}" ]]; then
  BUILD_DIR="$(cd "${ROOT}/${BUILD_DIR}" && pwd)"
elif [[ -d "${BUILD_DIR}" ]]; then
  BUILD_DIR="$(cd "${BUILD_DIR}" && pwd)"
else
  echo "error: build dir not found: ${BUILD_DIR}" >&2
  exit 1
fi

# Defaults for a typical title if caller passed none.
# Codegen host sources live in psxrecomp/host/ (copied with the framework tree).
if [[ ${#PROJECT_FILES[@]} -eq 0 && ${#PROJECT_DIRS[@]} -eq 0 ]]; then
  PROJECT_FILES=(CMakeLists.txt game.toml VERSION)
  for d in seeds launcher_assets; do
    if [[ -e "${ROOT}/${d}" ]]; then
      PROJECT_DIRS+=("${d}")
    fi
  done
  for f in codegen_setup.c codegen_setup.h DISC.md README.md; do
    if [[ -e "${ROOT}/${f}" ]]; then
      PROJECT_FILES+=("${f}")
    fi
  done
fi

# Resolve version.
VERSION=""
if [[ -n "${VERSION_ENV}" ]]; then
  VERSION="${!VERSION_ENV:-}"
fi
if [[ -z "${VERSION}" && -n "${RELEASE_VERSION:-}" ]]; then
  VERSION="${RELEASE_VERSION}"
fi
if [[ -z "${VERSION}" && -n "${BPE_RELEASE_VERSION:-}" ]]; then
  VERSION="${BPE_RELEASE_VERSION}"
fi
if [[ -z "${VERSION}" && -f "${ROOT}/VERSION" ]]; then
  VERSION="$(tr -d '[:space:]' <"${ROOT}/VERSION")"
fi
VERSION="$(printf '%s' "${VERSION}" | tr -d '[:space:]')"
VERSION="${VERSION#v}"
if [[ -z "${VERSION}" ]]; then
  echo "error: VERSION empty (set ${VERSION_ENV} / RELEASE_VERSION or write VERSION)" >&2
  exit 1
fi
printf '%s\n' "${VERSION}" >"${ROOT}/VERSION"

DIST="${ROOT}/dist"
STAGE="${DIST}/stage-setup-${ARTIFACT}"
ZIP_NAME="${ZIP_PREFIX}-${VERSION}-${ARTIFACT}.zip"

rm -rf "${STAGE}"
mkdir -p "${STAGE}" "${DIST}"
rm -f "${DIST}/${ZIP_NAME}"

EXE=""
for cand in \
  "${BUILD_DIR}/${EXE_NAME}" \
  "${BUILD_DIR}/${EXE_NAME}.exe" \
  "${BUILD_DIR}/Release/${EXE_NAME}.exe"
do
  if [[ -f "${cand}" ]]; then
    EXE="${cand}"
    break
  fi
done
if [[ -z "${EXE}" ]]; then
  echo "error: setup host executable '${EXE_NAME}' not found under ${BUILD_DIR}" >&2
  ls -la "${BUILD_DIR}" >&2 || true
  exit 1
fi

cp -a "${EXE}" "${STAGE}/"
EXE_BASENAME="$(basename "${EXE}")"
EXE_DIR="$(dirname "${EXE}")"

if [[ ! -d "${EXE_DIR}/assets/fonts" || ! -d "${EXE_DIR}/assets/img" ]]; then
  echo "error: ${EXE_DIR}/assets/{fonts,img} missing — rebuild psx-runtime" >&2
  exit 1
fi
mkdir -p "${STAGE}/assets"
cp -a "${EXE_DIR}/assets/fonts" "${STAGE}/assets/"
cp -a "${EXE_DIR}/assets/img" "${STAGE}/assets/"
if [[ ! -f "${STAGE}/assets/img/boxart.tga" && -f "${ROOT}/launcher_assets/img/boxart.tga" ]]; then
  cp -a "${ROOT}/launcher_assets/img/boxart.tga" "${STAGE}/assets/img/boxart.tga"
fi

copy_proj() {
  local rel="$1"
  if [[ -e "${ROOT}/${rel}" ]]; then
    mkdir -p "$(dirname "${STAGE}/${rel}")"
    cp -a "${ROOT}/${rel}" "${STAGE}/${rel}"
  else
    echo "error: missing ${rel}" >&2
    exit 1
  fi
}

for f in "${PROJECT_FILES[@]}"; do
  copy_proj "${f}"
done
for d in "${PROJECT_DIRS[@]}"; do
  copy_proj "${d}"
done

copy_tree_filtered() {
  local src="$1" dest="$2"
  shift 2
  mkdir -p "${dest}"
  if command -v rsync >/dev/null 2>&1; then
    rsync -a "$@" "${src}/" "${dest}/"
  else
    cp -a "${src}/." "${dest}/"
    rm -rf "${dest}/.git" "${dest}/recompiler/build" "${dest}/generated" 2>/dev/null || true
    find "${dest}" -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true
    find "${dest}" -type d \( -name 'build' -o -name 'build-*' \) -prune -exec rm -rf {} + 2>/dev/null || true
  fi
}

if [[ ! -d "${ROOT}/psxrecomp" ]]; then
  echo "error: ${ROOT}/psxrecomp missing (expected framework submodule)" >&2
  exit 1
fi
if [[ ! -d "${ROOT}/recomp-ui" ]]; then
  echo "error: ${ROOT}/recomp-ui missing (expected UI submodule)" >&2
  exit 1
fi

copy_tree_filtered "${ROOT}/psxrecomp" "${STAGE}/psxrecomp" \
  --exclude '.git' \
  --exclude 'recompiler/build' \
  --exclude 'generated' \
  --exclude '__pycache__' \
  --exclude 'build' \
  --exclude 'build-*'

copy_tree_filtered "${ROOT}/recomp-ui" "${STAGE}/recomp-ui" \
  --exclude '.git' \
  --exclude 'build' \
  --exclude '__pycache__'

# Never ship game generated C or common disc working trees.
rm -rf "${STAGE}/generated" "${STAGE}/bpe" "${STAGE}/motk" "${STAGE}/disc"

STAGE_SDK="${SCRIPT_DIR}/stage_setup_sdk.sh"
if [[ ! -f "${STAGE_SDK}" ]]; then
  echo "error: missing ${STAGE_SDK}" >&2
  exit 1
fi
chmod +x "${STAGE_SDK}" 2>/dev/null || true

stage_args=(
  --stage "${STAGE}"
  --framework "${ROOT}/psxrecomp"
  --search-dir "${EXE_DIR}"
  --search-dir "${BUILD_DIR}"
  --runtime-bin "${RUNTIME_BIN_DIR}"
  --host-exe "${STAGE}/${EXE_BASENAME}"
  --recompiler-build "${RECOMPILER_BUILD}"
)
if [[ "${EMBED_TOOLCHAIN}" -eq 1 ]]; then
  if [[ -z "${PSXRECOMP_TOOLCHAIN_DIR:-${TOOLCHAIN_DIR:-${BPE_TOOLCHAIN_DIR:-}}}" ]]; then
    echo "error: --embed-toolchain requires PSXRECOMP_TOOLCHAIN_DIR (or TOOLCHAIN_DIR)" >&2
    exit 1
  fi
  stage_args+=(--toolchain-dir "${PSXRECOMP_TOOLCHAIN_DIR:-${TOOLCHAIN_DIR:-${BPE_TOOLCHAIN_DIR}}}")
else
  stage_args+=(--allow-no-toolchain)
fi

bash "${STAGE_SDK}" "${stage_args[@]}"

cat >"${STAGE}/README-SETUP.txt" <<EOF
${DISPLAY_NAME} ${VERSION} — setup package
Platform: ${ARTIFACT}

One zip for first install and updates. Does NOT include disc images, retail
BIOS dumps, pre-generated game C, or a portable cmake/clang pack. Emitters
(psxrecomp-game / psxrecomp-bios) and the CLI are inside psxrecomp/.

Standalone:
1. Install Python 3.
2. Run ${EXE_BASENAME}.
3. Provide ${DISC_HINT} (and optional retail SCPH-1001 BIOS; otherwise
   OpenBIOS is regenerated locally).
4. Follow the Generate & rebuild wizard. On first rebuild the host downloads
   cmake-clang-v1 from TechnicallyComputers/retcomm-toolchains (or you can
   pick a local cmake-clang-v1-*.zip for offline builds). System cmake/ninja
   also works if already on PATH.

RetComM uses this same zip: it harvests emitters into a shared SDK cache,
downloads the toolchain pack (or uses RETCOMM_TOOLCHAIN_DIR), and preserves
saves/user config across updates.
EOF

find "${STAGE}" -exec touch -c {} + 2>/dev/null || find "${STAGE}" -exec touch {} +

(
  cd "${STAGE}"
  if command -v zip >/dev/null 2>&1; then
    zip -r -q "${DIST}/${ZIP_NAME}" .
  else
    echo "error: zip not found" >&2
    exit 1
  fi
)

echo "Wrote ${DIST}/${ZIP_NAME}"
du -h "${DIST}/${ZIP_NAME}"

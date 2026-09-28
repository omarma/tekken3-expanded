#!/usr/bin/env bash
# Bundle imported non-system DLLs next to Windows PE executables.
#
# Title packagers (BPE/MotK setup zips) call this for Windows PEs that still
# import non-system DLLs (typically the MSYS2-built setup host + SDL2).
# Emitters built with llvm-mingw + PSXRECOMP_STATIC_CLI should import none of
# the GCC runtimes; this script only copies DLLs each exe actually imports.
#
# Usage:
#   bundle_mingw_dlls.sh [options] --exe <path> [--dest <dir>] [--label <name>] ...
#
# Options:
#   --runtime-bin DIR   Preferred DLL search directory (repeatable)
#   --search-dir DIR    Extra DLL search directory (repeatable)
#   --exe PATH          PE to inspect (repeatable; --dest/--label apply to it)
#   --dest DIR          Copy DLLs here (default: dirname of the preceding --exe)
#   --label NAME        Log label for the preceding --exe
#   --require DLL       After bundling, DLL must exist in every --dest that
#                       imported it (repeatable)
#   --soft-missing      Warn instead of exit 1 when objdump is unavailable
#
# Exit 1 if an imported DLL cannot be found, or a --require check fails.
set -euo pipefail

SOFT_MISSING=0
RUNTIME_BINS=()
SEARCH_DIRS=()
REQUIRE=()

# Parallel arrays for targets.
EXE_PATHS=()
DEST_DIRS=()
LABELS=()

pending_dest=""
pending_label=""

usage() {
  sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'
  exit 2
}

flush_pending_meta() {
  # Apply trailing --dest/--label to the last --exe.
  local n="${#EXE_PATHS[@]}"
  if [[ "$n" -eq 0 ]]; then
    return 0
  fi
  local i=$((n - 1))
  if [[ -n "${pending_dest}" ]]; then
    DEST_DIRS[$i]="${pending_dest}"
    pending_dest=""
  fi
  if [[ -n "${pending_label}" ]]; then
    LABELS[$i]="${pending_label}"
    pending_label=""
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage ;;
    --soft-missing) SOFT_MISSING=1; shift ;;
    --runtime-bin)
      RUNTIME_BINS+=("${2:?}"); shift 2 ;;
    --search-dir)
      SEARCH_DIRS+=("${2:?}"); shift 2 ;;
    --require)
      REQUIRE+=("${2:?}"); shift 2 ;;
    --exe)
      flush_pending_meta
      EXE_PATHS+=("${2:?}")
      DEST_DIRS+=("")
      LABELS+=("")
      shift 2
      ;;
    --dest)
      pending_dest="${2:?}"; shift 2 ;;
    --label)
      pending_label="${2:?}"; shift 2 ;;
    *)
      echo "error: unknown arg: $1" >&2
      usage
      ;;
  esac
done
flush_pending_meta

if [[ ${#EXE_PATHS[@]} -eq 0 ]]; then
  echo "error: at least one --exe is required" >&2
  usage
fi

OBJDUMP=""
if command -v x86_64-w64-mingw32-objdump >/dev/null 2>&1; then
  OBJDUMP="x86_64-w64-mingw32-objdump"
elif command -v objdump >/dev/null 2>&1; then
  OBJDUMP="objdump"
else
  if [[ "${SOFT_MISSING}" -eq 1 ]]; then
    echo "warning: no objdump; skipping MinGW DLL bundling" >&2
    exit 0
  fi
  echo "error: no objdump; cannot bundle MinGW DLLs" >&2
  exit 1
fi

SYSTEM_DLL_RE='^(KERNEL32|USER32|GDI32|ADVAPI32|SHELL32|OLE32|OLEAUT32|WS2_32|WINMM|IMM32|SETUPAPI|VERSION|OPENGL32|COMCTL32|COMDLG32|RPCRT4|SHLWAPI|CRYPT32|BCRYPT|IPHLPAPI|NSI|DNSAPI|MSVCRT|UCRTBASE|VCRUNTIME|API-MS-).*\.DLL$'

PROBE_DLLS=(
  SDL2.dll
  zlib1.dll
  libgcc_s_seh-1.dll
  libstdc++-6.dll
  libc++.dll
  libunwind.dll
  libwinpthread-1.dll
  libssp-0.dll
)

exe_imports_dll() {
  local exe="$1"
  local dll="$2"
  "${OBJDUMP}" -p "${exe}" 2>/dev/null | grep -qi "DLL Name:[[:space:]]*${dll}"
}

bundle_one() {
  local exe="$1"
  local dest_dir="$2"
  local label="$3"
  local dll src key cand d
  local -a needed=()
  local -a unique=()
  local -a candidates=()
  local -A seen=()

  if [[ ! -f "${exe}" ]]; then
    echo "error: cannot bundle DLLs; missing ${exe}" >&2
    exit 1
  fi
  if [[ -z "${dest_dir}" ]]; then
    dest_dir="$(dirname "${exe}")"
  fi
  if [[ -z "${label}" ]]; then
    label="$(basename "${exe}")"
  fi
  mkdir -p "${dest_dir}"

  mapfile -t needed < <(
    "${OBJDUMP}" -p "${exe}" 2>/dev/null \
      | awk '/DLL Name:/{print $3}' \
      | grep -viE "${SYSTEM_DLL_RE}" \
      | sort -u || true
  )
  needed+=("${PROBE_DLLS[@]}")

  for dll in "${needed[@]}"; do
    [[ -n "${dll}" ]] || continue
    key="$(printf '%s' "${dll}" | tr '[:upper:]' '[:lower:]')"
    if [[ -n "${seen[$key]:-}" ]]; then
      continue
    fi
    seen[$key]=1
    unique+=("${dll}")
  done

  for dll in "${unique[@]}"; do
    if ! exe_imports_dll "${exe}" "${dll}"; then
      continue
    fi
    src=""
    candidates=(
      "$(dirname "${exe}")/${dll}"
      "${dest_dir}/${dll}"
      "/mingw64/bin/${dll}"
      "/usr/x86_64-w64-mingw32/bin/${dll}"
    )
    for d in "${SEARCH_DIRS[@]+"${SEARCH_DIRS[@]}"}"; do
      candidates+=("${d}/${dll}")
    done
    for d in "${RUNTIME_BINS[@]+"${RUNTIME_BINS[@]}"}"; do
      candidates+=("${d}/${dll}")
    done
    for cand in "${candidates[@]}"; do
      [[ -n "${cand}" ]] || continue
      if [[ -f "${cand}" ]]; then
        src="${cand}"
        break
      fi
    done
    if [[ -z "${src}" ]]; then
      echo "error: required DLL missing for ${label}: ${dll}" >&2
      echo "  exe: ${exe}" >&2
      echo "  dest: ${dest_dir}" >&2
      if [[ ${#SEARCH_DIRS[@]} -gt 0 ]]; then
        echo "  search-dirs: ${SEARCH_DIRS[*]}" >&2
      fi
      if [[ ${#RUNTIME_BINS[@]} -gt 0 ]]; then
        echo "  runtime-bins: ${RUNTIME_BINS[*]}" >&2
      fi
      exit 1
    fi
    dest_file="${dest_dir}/${dll}"
    # MSYS2/Windows cp fails when source and dest are the same file.
    if [[ -f "${dest_file}" ]] && [[ "${src}" -ef "${dest_file}" ]]; then
      echo "bundled ${dll} → ${dest_dir}/ (${label}; already present)"
      continue
    fi
    src_res="$(cd "$(dirname "${src}")" && pwd)/$(basename "${src}")"
    dest_res="$(cd "${dest_dir}" && pwd)/${dll}"
    if [[ "${src_res}" == "${dest_res}" ]]; then
      echo "bundled ${dll} → ${dest_dir}/ (${label}; already present)"
      continue
    fi
    cp -f "${src}" "${dest_dir}/"
    echo "bundled ${dll} → ${dest_dir}/ (${label})"
  done
}

for i in "${!EXE_PATHS[@]}"; do
  bundle_one "${EXE_PATHS[$i]}" "${DEST_DIRS[$i]}" "${LABELS[$i]}"
done

for dll in "${REQUIRE[@]}"; do
  [[ -n "${dll}" ]] || continue
  for i in "${!EXE_PATHS[@]}"; do
    exe="${EXE_PATHS[$i]}"
    dest="${DEST_DIRS[$i]:-}"
    if [[ -z "${dest}" ]]; then
      dest="$(dirname "${exe}")"
    fi
    if ! exe_imports_dll "${exe}" "${dll}"; then
      continue
    fi
    if [[ ! -f "${dest}/${dll}" ]]; then
      echo "error: $(basename "${exe}") imported ${dll} but it is missing under ${dest}" >&2
      exit 1
    fi
  done
done

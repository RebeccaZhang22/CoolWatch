#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
OVERLAY_DIR="$SCRIPT_DIR/vllm-0.25.1-overlay"
MANIFEST="$OVERLAY_DIR/manifest.json"
BACKUP_NAME=".perspective-watch-inline-probing-vllm-0.25.1-backup"

die() {
  echo "patch-vllm: $*" >&2
  exit 1
}

sha256_file() {
  sha256sum "$1" | awk '{print $1}'
}

usage() {
  echo "usage: $0 {apply|check|restore} --target SITE_PACKAGES/VLLM" >&2
  exit 2
}

[[ $# -ge 1 ]] || usage
ACTION="$1"
shift
TARGET=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --target) [[ $# -ge 2 ]] || usage; TARGET="$2"; shift 2 ;;
    *) usage ;;
  esac
done
[[ "$ACTION" =~ ^(apply|check|restore)$ ]] || usage
[[ -n "$TARGET" ]] || usage
TARGET="$(realpath "$TARGET")"
[[ -d "$TARGET" && "$(basename "$TARGET")" == "vllm" ]] || \
  die "--target must be an installed site-packages/vllm directory"

command -v jq >/dev/null || die "jq is required"
command -v sha256sum >/dev/null || die "sha256sum is required"
jq -e '.schema == "perspective_watch.inline_probing.vllm_overlay.v1" and .vllm_version == "0.25.1"' \
  "$MANIFEST" >/dev/null || die "unsupported or malformed overlay manifest"

mapfile -t METADATA_FILES < <(find "$(dirname "$TARGET")" -mindepth 2 -maxdepth 2 \
  -name METADATA -type f -path "$(dirname "$TARGET")/vllm-*.dist-info/METADATA" -print)
[[ ${#METADATA_FILES[@]} -eq 1 ]] || die "expected exactly one vLLM dist-info METADATA"
VERSION="$(awk -F ': ' '$1 == "Version" {print $2; exit}' "${METADATA_FILES[0]}")"
BASE_VERSION="${VERSION%%+*}"
[[ "$BASE_VERSION" == "0.25.1" ]] || die "expected vLLM 0.25.1, found ${VERSION:-unknown}"

mapfile -t FILE_ROWS < <(jq -r '.files[] | [.path, (.upstream_sha256 // "ABSENT"), .patched_sha256] | @tsv' "$MANIFEST")
EXPECTED_FILES="$(jq -r '.files | length' "$MANIFEST")"
[[ "$EXPECTED_FILES" -gt 0 && ${#FILE_ROWS[@]} -eq "$EXPECTED_FILES" ]] || \
  die "overlay manifest file count mismatch"

for row in "${FILE_ROWS[@]}"; do
  IFS=$'\t' read -r relative upstream patched <<<"$row"
  source_file="$OVERLAY_DIR/vllm/$relative"
  [[ -f "$source_file" ]] || die "overlay file missing: $relative"
  [[ "$(sha256_file "$source_file")" == "$patched" ]] || die "overlay hash mismatch: $relative"
done

compile_overlay() {
  local cache_dir row relative
  cache_dir="$(mktemp -d)"
  for row in "${FILE_ROWS[@]}"; do
    IFS=$'\t' read -r relative _ _ <<<"$row"
    PYTHONPYCACHEPREFIX="$cache_dir" "${PYTHON_BIN:-python3}" -m py_compile \
      "$OVERLAY_DIR/vllm/$relative"
  done
  rm -rf -- "$cache_dir"
}

check_patched() {
  local row relative upstream patched destination actual
  for row in "${FILE_ROWS[@]}"; do
    IFS=$'\t' read -r relative upstream patched <<<"$row"
    destination="$TARGET/$relative"
    [[ -f "$destination" ]] || die "installed overlay file missing: $relative"
    actual="$(sha256_file "$destination")"
    [[ "$actual" == "$patched" ]] || die "installed overlay hash mismatch: $relative ($actual)"
  done
  compile_overlay
}

print_result() {
  local action="$1" changed="$2" backup="${3:-}"
  jq -n \
    --arg action "$action" --arg target "$TARGET" --arg version "$VERSION" \
    --arg backup "$backup" --argjson changed "$changed" \
    --argjson files "${#FILE_ROWS[@]}" \
    '{action:$action,status:"ok",target:$target,vllm_version:$version,verified_files:$files,changed:$changed}
     + if $backup == "" then {} else {backup:$backup} end'
}

BACKUP_DIR="$(dirname "$TARGET")/$BACKUP_NAME"

if [[ "$ACTION" == "check" ]]; then
  check_patched
  print_result check false
  exit 0
fi

restore_backup() {
  [[ -f "$BACKUP_DIR/state.tsv" ]] || die "no recoverable backup at $BACKUP_DIR"
  while IFS=$'\t' read -r relative existed expected; do
    destination="$TARGET/$relative"
    if [[ "$existed" == "1" ]]; then
      source_file="$BACKUP_DIR/vllm/$relative"
      [[ -f "$source_file" ]] || die "backup file missing: $relative"
      [[ "$(sha256_file "$source_file")" == "$expected" ]] || die "backup hash mismatch: $relative"
      mkdir -p "$(dirname "$destination")"
      temporary="$(mktemp "$(dirname "$destination")/.restore.XXXXXX")"
      cp -p "$source_file" "$temporary"
      mv -f "$temporary" "$destination"
    else
      rm -f -- "$destination"
    fi
  done < "$BACKUP_DIR/state.tsv"
  rm -rf -- "$BACKUP_DIR"
}

if [[ "$ACTION" == "restore" ]]; then
  check_patched
  restore_backup
  print_result restore true
  exit 0
fi

state=""
for row in "${FILE_ROWS[@]}"; do
  IFS=$'\t' read -r relative upstream patched <<<"$row"
  destination="$TARGET/$relative"
  actual="ABSENT"
  [[ -f "$destination" ]] && actual="$(sha256_file "$destination")"
  if [[ "$actual" == "$patched" ]]; then
    current="patched"
  elif [[ "$actual" == "$upstream" ]]; then
    current="upstream"
  else
    die "refusing unknown source $relative: actual=$actual upstream=$upstream patched=$patched"
  fi
  [[ -z "$state" || "$state" == "$current" ]] || die "refusing mixed upstream/patched installation"
  state="$current"
done

if [[ "$state" == "patched" ]]; then
  check_patched
  print_result apply false
  exit 0
fi

[[ ! -e "$BACKUP_DIR" ]] || die "backup already exists: $BACKUP_DIR"
mkdir -p "$BACKUP_DIR/vllm"
: > "$BACKUP_DIR/state.tsv"
for row in "${FILE_ROWS[@]}"; do
  IFS=$'\t' read -r relative _ _ <<<"$row"
  destination="$TARGET/$relative"
  if [[ -f "$destination" ]]; then
    mkdir -p "$BACKUP_DIR/vllm/$(dirname "$relative")"
    cp -p "$destination" "$BACKUP_DIR/vllm/$relative"
    printf '%s\t1\t%s\n' "$relative" "$(sha256_file "$destination")" >> "$BACKUP_DIR/state.tsv"
  else
    printf '%s\t0\tABSENT\n' "$relative" >> "$BACKUP_DIR/state.tsv"
  fi
done

rollback=1
trap 'if [[ $rollback -eq 1 ]]; then restore_backup; fi' ERR
for row in "${FILE_ROWS[@]}"; do
  IFS=$'\t' read -r relative _ _ <<<"$row"
  source_file="$OVERLAY_DIR/vllm/$relative"
  destination="$TARGET/$relative"
  mkdir -p "$(dirname "$destination")"
  temporary="$(mktemp "$(dirname "$destination")/.inline-probing.XXXXXX")"
  cp -p "$source_file" "$temporary"
  mv -f "$temporary" "$destination"
done
check_patched
rollback=0
trap - ERR
print_result apply true "$BACKUP_DIR"

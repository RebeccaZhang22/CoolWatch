#!/usr/bin/env bash
# 应用到部署树。默认 dry-run；加 --apply 才真写。
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="${1:?usage: apply.sh <CoolWatch-server 目录> [--apply]}"
MODE="${2:-dry}"
cd "$TARGET"
for p in "$HERE"/patch/0[1-6]*.patch; do
    if [[ "$MODE" == "--apply" ]]; then
        patch -p1 < "$p"
    else
        patch -p1 --dry-run < "$p" >/dev/null && echo "OK  $(basename "$p")"
    fi
done
if [[ "$MODE" != "--apply" ]]; then
    echo "dry-run 通过；加 --apply 真正写入"
fi

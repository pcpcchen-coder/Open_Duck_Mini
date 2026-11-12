#!/usr/bin/env bash
# 檢查本 fork 相對於上游 apirrone/Open_Duck_Mini v2 的差異只出現在允許的路徑。
# 允許：nous_duck/、根目錄 CLAUDE.md、.github/
# 用法：nous_duck/tools/check_upstream_untouched.sh [上游 ref，預設 upstream/v2]
# 需要先有上游 ref，例如：
#   git remote add upstream https://github.com/apirrone/Open_Duck_Mini.git
#   git fetch upstream v2
set -euo pipefail

BASE_REF="${1:-upstream/v2}"

if ! git rev-parse --verify --quiet "${BASE_REF}^{commit}" >/dev/null; then
  echo "找不到上游 ref：${BASE_REF}（請先 git fetch upstream v2）" >&2
  exit 2
fi

# 以 merge-base 比較：上游之後新增的 commit 不算我們的修改。
MERGE_BASE="$(git merge-base HEAD "${BASE_REF}")"

violations="$(git diff --name-only "${MERGE_BASE}" HEAD \
  | grep -Ev '^(nous_duck/|\.github/|CLAUDE\.md$)' || true)"

echo "上游 ref：${BASE_REF}（merge-base ${MERGE_BASE:0:7}）"
if [[ -n "${violations}" ]]; then
  echo "以下上游檔案被修改、新增或刪除（只允許 nous_duck/、CLAUDE.md、.github/）：" >&2
  echo "${violations}" | sed 's/^/  - /' >&2
  exit 1
fi
echo "OK：與上游的差異只在 nous_duck/、CLAUDE.md、.github/。"

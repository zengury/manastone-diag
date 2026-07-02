#!/usr/bin/env bash
# init_public_repo.sh — 产出可公开发布的干净快照 (全新历史)
#
# 用法: bash scripts/init_public_repo.sh <输出目录> [版本号]
# 例:   bash scripts/init_public_repo.sh /tmp/manastone-diag-public v2.2.0
#
# 步骤:
#   1. git archive 导出当前 HEAD 的树 (不带历史)
#   2. 删除剔除清单中的文件 (若仍存在)
#   3. 泄漏扫描硬门禁 (check_boundary.sh, 命中即中止)
#   4. 快照内完整跑 verify_all + check_knowledge (公开的东西必须开箱即用)
#   5. git init + 单 commit (作者 zengury <zengury@gmail.com>) + 版本 tag
#   6. 产出 git bundle
set -euo pipefail
cd "$(dirname "$0")/.."
REPO_ROOT=$(pwd)

OUT=${1:?用法: init_public_repo.sh <输出目录> [版本号]}
VERSION=${2:-v2.2.0}

if [ -e "$OUT" ]; then
  echo "❌ 输出目录已存在: $OUT (请先删除或换一个)"
  exit 1
fi
mkdir -p "$OUT"

echo "── 1/6 导出树 (git archive HEAD) ──"
git archive HEAD | tar -x -C "$OUT"

echo "── 2/6 删除剔除清单 ──"
# 注意: 用通配符而非完整文件名, 避免本脚本自身携带真实 SN 触发泄漏门禁
EXCLUDE_LIST=(
  "docs/DIAG_REPORT_"*.md
  "docs/DEVLOG_"*.md
  "docs/HANDOFF_"*.md
  "docs/SAFETY_CONSTRAINT_"*.md
  ".pi/skills/connect-robot.md"
)
(
  cd "$OUT"
  for f in "${EXCLUDE_LIST[@]}"; do
    if [ -e "$f" ]; then
      rm -f "$f"
      echo "  删除: $f"
    fi
  done
)

echo "── 3/6 泄漏扫描硬门禁 ──"
(cd "$OUT" && bash scripts/check_boundary.sh)

echo "── 4/6 快照内完整验证 ──"
(cd "$OUT" && python3 tools/verify_all.py && python3 scripts/check_knowledge.py)

echo "── 5/6 git init + 单 commit + tag ──"
(
  cd "$OUT"
  git init -q -b main
  git add -A
  GIT_AUTHOR_NAME=zengury GIT_AUTHOR_EMAIL=zengury@gmail.com \
  GIT_COMMITTER_NAME=zengury GIT_COMMITTER_EMAIL=zengury@gmail.com \
  git commit -q -m "manastone-diag $VERSION — offline fault diagnosis for the AgiBot X2 Ultra

Public snapshot with fresh history. See CHANGELOG.md for what changed."
  git tag "$VERSION"
)

echo "── 6/6 产出 bundle ──"
BUNDLE="$OUT.bundle"
(cd "$OUT" && git bundle create "$BUNDLE" HEAD main "$VERSION")

echo ""
echo "✅ 干净快照就绪:"
echo "   目录:   $OUT"
echo "   bundle: $BUNDLE"
echo ""
echo "本地发布步骤 (在 bundle 克隆出的目录里执行, 不要在内部仓目录里跑):"
echo "   git clone $BUNDLE manastone-diag-public"
echo "   cd manastone-diag-public"
echo "   python3 tools/verify_all.py          # 最后一遍确认"
echo "   git remote add origin git@github.com:zengury/manastone-diag.git"
echo "   git push --force origin main $VERSION"

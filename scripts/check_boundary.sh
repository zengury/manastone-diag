#!/usr/bin/env bash
# check_boundary.sh — 泄漏扫描硬门禁
#
# 扫描仓库中不允许出现的内部信息 (内核私有接口、真实整机 SN、内部代号、
# 内部路径/邮箱域)。任何命中 → exit 1。CI 与发布快照都跑这个脚本。
#
# 边界策略 ("开两端、闭内核"): 开源版只允许依赖 runtime 的公开 ledger 读 API,
# 不得出现内核私有 CLI、内核源码文件引用、内核私仓 issue 编号。
set -u
cd "$(dirname "$0")/.."

FORBIDDEN=(
  'X220028C4Z0079'          # 真实整机 SN (示例请用 X2EXAMPLE00001)
  'X2[0-9]{5}[A-Z][0-9][A-Z][0-9]{4}'  # 真实 SN 形态
  'agent-runtime'           # 内核私有 CLI, 不属于公开接口面
  'runtime\.py:[0-9]'       # 内核源码文件行号引用
  '星行侠'                   # 内部产品代号
  '\bSnakes\b'              # 内部代号
  '\bOpenClaw\b'            # 内部代号
  'silicon38'               # 内部代号
  '/Users/ZQ'               # 内部开发机路径
  'digit\.com\.cn'          # 内部邮箱域
)

EXCLUDE=(--exclude-dir=.git --exclude-dir=__pycache__ --exclude-dir=data
         --exclude-dir=robot-logs --exclude=check_boundary.sh)

fail=0
for pat in "${FORBIDDEN[@]}"; do
  hits=$(grep -rInE "${EXCLUDE[@]}" -e "$pat" . 2>/dev/null)
  if [ -n "$hits" ]; then
    echo "❌ 命中禁用模式: $pat"
    echo "$hits" | head -10
    fail=1
  fi
done

if [ "$fail" -ne 0 ]; then
  echo ""
  echo "❌ 泄漏扫描失败 — 上述内容不得进入公开仓库"
  exit 1
fi
echo "✅ 泄漏扫描通过 (共 ${#FORBIDDEN[@]} 条禁用模式)"

#!/bin/bash
set -e

echo "═══════════════════════════════════════════"
echo "  manastone-diag 安装"
echo "═══════════════════════════════════════════"
echo ""

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# 1. Node.js
if ! command -v node &> /dev/null; then
    echo "❌ 未找到 Node.js。请先安装：https://nodejs.org"
    exit 1
fi
echo "✅ Node.js $(node -v)"

# 2. Python
if ! command -v python3 &> /dev/null; then
    echo "❌ 未找到 Python 3。请先安装 Python 3.10+"
    exit 1
fi
echo "✅ Python $(python3 -V | cut -d' ' -f2)"

# 3. pi
if command -v pi &> /dev/null; then
    echo "✅ pi 已安装"
else
    echo "📦 安装 pi ..."
    npm install -g @mariozechner/pi-coding-agent
    echo "✅ pi 安装完成"
fi

# 4. Python 依赖
echo "📦 安装 Python 依赖 ..."
pip3 install -r "$SCRIPT_DIR/requirements.txt" --quiet
echo "✅ Python 依赖安装完成"

# 5. manastone-diag 命令
BIN_DIR="$HOME/.local/bin"
mkdir -p "$BIN_DIR"
sed "s|__INSTALL_DIR__|$SCRIPT_DIR|g" "$SCRIPT_DIR/manastone-diag" > "$BIN_DIR/manastone-diag"
chmod +x "$BIN_DIR/manastone-diag"
echo "✅ manastone-diag 安装到 $BIN_DIR"

# 6. PATH 检查
if ! echo "$PATH" | grep -q "$BIN_DIR"; then
    echo ""
    echo "⚠️  $BIN_DIR 不在 PATH 中"
    echo "   请将以下行添加到 ~/.zshrc 或 ~/.bashrc："
    echo ""
    echo "   export PATH=\"\$HOME/.local/bin:\$PATH\""
    echo ""
fi

# 7. API key
if [ -z "$ANTHROPIC_API_KEY" ] && [ -z "$OPENAI_API_KEY" ] && [ -z "$DEEPSEEK_API_KEY" ]; then
    echo ""
    echo "⚠️  未检测到 LLM API key"
    echo "   请在 ~/.zshrc 或 ~/.bashrc 中设置（任选一种）："
    echo ""
    echo "   export ANTHROPIC_API_KEY=sk-ant-..."
    echo "   export OPENAI_API_KEY=sk-..."
    echo "   export DEEPSEEK_API_KEY=sk-..."
    echo ""
    echo "   或启动后输入 /login 选择 provider"
fi

echo ""
echo "═══════════════════════════════════════════"
echo "  安装完成"
echo ""
echo "  启动: manastone-diag"
echo "  帮助: manastone-diag --help"
echo "═══════════════════════════════════════════"

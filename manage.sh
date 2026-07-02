#!/usr/bin/env bash
# Manastone 诊断助手 — 打开归档面板 (Linux/macOS)
set -e
cd "$(dirname "$0")"
python3 tools/session_archiver.py dashboard

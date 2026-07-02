"""
config.py — manastone-diag 全局配置
====================================

数据目录优先级:
  1. 环境变量 MANASTONE_DATA_DIR  (最高优先级, 用于多用户共享)
  2. 项目根目录下的 data/          (默认)
  3. 用户目录下的 .manastone-diag/  (fallback)

多用户共享场景:
  管理员在共享盘部署:
    set MANASTONE_DATA_DIR=\\server\manastone-shared\data
  或:
    set MANASTONE_DATA_DIR=D:\shared\manastone-data
  所有用户指向同一目录，经验库和知识自动共享。

用法:
    from tools.config import data_dir, is_shared_mode
    archive_dir = data_dir() / "archive"
"""

import os
from pathlib import Path


def data_dir() -> Path:
    """获取数据根目录。"""
    # 1. 环境变量
    env = os.environ.get("MANASTONE_DATA_DIR")
    if env:
        p = Path(env)
        p.mkdir(parents=True, exist_ok=True)
        return p

    # 2. 项目内
    cwd = Path.cwd()
    for parent in [cwd] + list(cwd.parents):
        if (parent / "AGENTS.md").exists() or (parent / "tools" / "knowledge").is_dir():
            d = parent / "data"
            d.mkdir(parents=True, exist_ok=True)
            return d

    # 3. 用户目录
    d = Path.home() / ".manastone-diag"
    d.mkdir(parents=True, exist_ok=True)
    return d


def is_shared_mode() -> bool:
    """是否使用共享数据目录。"""
    return "MANASTONE_DATA_DIR" in os.environ


def project_root() -> Path:
    """项目根目录。"""
    cwd = Path.cwd()
    for parent in [cwd] + list(cwd.parents):
        if (parent / "AGENTS.md").exists():
            return parent
        if (parent / "tools" / "knowledge").is_dir() and (parent / "tools").is_dir():
            return parent
    return cwd

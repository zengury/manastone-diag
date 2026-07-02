# manastone-diag PyPI 占名备份

> **备份日**: 2026-07-02  
> **PyPI 项目**: https://pypi.org/project/manastone-diag/ （**已上传** 2026-07-02）  
> **占位版本**: `0.0.1`（最小 stub，非完整诊断产品代码）

## PyPI 已占名

- **上传完成**: 2026-07-02
- **PyPI URL**: https://pypi.org/project/manastone-diag/
- **已发布版本**: `0.0.1`（wheel + sdist）
- **验证**: `curl -s https://pypi.org/pypi/manastone-diag/json` 应返回 `manastone-diag` / `0.0.1`

## 这是什么

本目录是 **PyPI 占名用最小占位包** 的永久备份，存放在正式产品仓库 **zengury/manastone-diag** 内。

目的是锁定 PyPI 包名 `manastone-diag`，避免被他人注册，并与 GitHub 上的 Manastone Diag 离线故障诊断产品对应。

**重要**: 仓库根目录的脚本、`tools/`、`knowledge/` 等才是 **Manastone Diag 正式产品**。  
占名包 `packaging/pypi-stub/` 与根目录产品是两套东西——未来若从本仓库发 PyPI 正式版，应从**产品级 `pyproject.toml`（尚未与占名包合并）** build + upload，不要误用仅占名的 `0.0.1` stub。

| 维度 | 占名 stub | 未来正式 PyPI 发版 |
|------|-----------|-------------------|
| 位置 | `packaging/pypi-stub/` | 待定（可能仓库根或 `src/` 布局） |
| 版本 | `0.0.1` | 须高于 `0.0.1`（如 `2.x` 对齐产品） |
| 内容 | 空壳 + README 说明 | 完整诊断工具/库 |

## 目录结构

```
packaging/pypi-stub/
├── BACKUP.md          ← 本说明（含操作备忘）
├── README.md          ← PyPI 项目页文案
├── LICENSE            ← Apache-2.0, Copyright 2026 zengury
├── pyproject.toml     ← name=manastone-diag, version=0.0.1
└── src/
    └── manastone_diag/
        └── __init__.py    ← 空壳，仅 __version__
```

## 已备份内容摘要

| 字段 | 值 |
|------|-----|
| PyPI name | `manastone-diag` |
| 占位版本 | `0.0.1` |
| 描述 | Manastone Diag — offline robot fault diagnosis. PyPI name reserved; releases forthcoming. |
| Python | `>=3.10` |
| 账号 | zengury @ pypi.org |
| GitHub 正式产品 | https://github.com/zengury/manastone-diag |

## 重新 build / 检查 / 上传占位包

```sh
cd packaging/pypi-stub
python3 -m pip install build twine
python3 -m build
python3 -m twine check dist/*
python3 -m twine upload dist/*
# Username: __token__
# Password: <pypi.org API token>
```

上传前确认 `twine check` 通过；勿将 API token 写入仓库或聊天。

## 与 manastone / roboonto 的关系

| 包 | PyPI | 状态（2026-07-02） |
|----|------|-------------------|
| `roboonto` | https://pypi.org/project/roboonto/ | 正式发版 |
| `manastone` | https://pypi.org/project/manastone/ | 占名 `0.0.1`（见 zengury/manastone `packaging/pypi-stub/`） |
| `manastone-diag` | https://pypi.org/project/manastone-diag/ | **已占名** `0.0.1`（2026-07-02 上传完成） |

## 安全提醒

PyPI API token 勿写入仓库或聊天。泄露后立即轮换：https://pypi.org/manage/account/token/

原始临时 build 路径：`/tmp/manastone-diag-pypi-stub`（以本目录为准；勿提交 `dist/`）

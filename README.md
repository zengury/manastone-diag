# Manastone 诊断助手

> X2 Ultra 人形机器人离线故障诊断工具 — 拖入日志包 → 对话描述故障 → 三轮审查诊断 → 自动出报告 → 经验持续积累

[![Version](https://img.shields.io/badge/version-2.0.0-blue)](https://github.com/thomastang237/manastone-diag/releases/tag/v2.0.0)
[![Latest](https://img.shields.io/badge/latest-2.1.0-green)](https://github.com/thomastang237/manastone-diag/releases/tag/v2.1.0)

> 📦 本项目基于 [zengury/manastone-diag](https://github.com/zengury/manastone-diag) 二次开发，感谢原作者的工作。
>
> 📋 版本历史详见 [CHANGELOG.md](CHANGELOG.md) · 其他版本请通过 [Releases](https://github.com/thomastang237/manastone-diag/releases) 页面的 Tag 下拉框切换。

---

## 快速开始

### 环境要求

- Windows 10 / 11
- [Hermes Agent](https://hermes-agent.nousresearch.com) 已安装
- Python 3.10+ (Hermes 自带)

### 安装

```powershell
# 1. 安装 Python 依赖
cd D:\manastone-diag
pip install pyyaml mcap mcap-ros2-support

# 2. (可选) atop 文件解析需要 WSL
wsl sudo apt install atop -y

# 3. (可选) 如有多用户共享需求
setx MANASTONE_DATA_DIR \\server\manastone-shared\data
```

### 启动

```powershell
# 默认方式（加载全部工具集）
cd D:\manastone-diag
hermes

# 省 token 方式（仅加载诊断必需的 5 个工具集，推荐）
cd D:\manastone-diag
hermes --profile diag
```

> **省 token 说明**: Hermes 默认加载 20+ 个工具集，诊断助手实际只需要 5 个（terminal/file/skills/memory/session_search）。
> 使用 `--profile diag` 启动可节省约 40-60% 的 system prompt token，不影响任何诊断功能。
>
> 工具集配置文件: `hermes-profile.yaml`（按需编辑，注释说明每个工具集的作用）

---

## 使用方式

```
┌──────────────────────────────────────────────────────┐
│  三步完成诊断：                                       │
│  ① 提交日志 — 拖入 tar 包到 robot-logs\               │
│  ② 描述现象 — 告诉 agent 发生了什么                   │
│  ③ 逐轮确认 — agent 分三轮出报告，每轮等你确认         │
└──────────────────────────────────────────────────────┘
```

### 日常操作

| 操作 | 方式 |
|------|------|
| 启动诊断 | `cd D:\manastone-diag && hermes` |
| 查看归档面板 | 双击 `manage.bat` |
| 导入其他用户数据 | 双击 `tools\import_tool.py` |
| 全功能验证 | `python tools\verify_all.py` |

### 诊断后验证

诊断完成后 agent 会提醒你去现场验证。验证方式：

```
你: X220028C4Z0079 验证结果 correct
你: 验证 [1]，诊断正确
你: 有哪些没验证？    ← 列出待验证列表
```

agent 自动更新经验库、修正规则权重。

---

## 项目结构

```
manastone-diag/
├── manage.bat              双击打开归档面板
├── AGENTS.md               Agent 人格 + 诊断流程
├── CHANGELOG.md            版本更新记录
├── hermes-profile.yaml     省 token 工具集配置
│
├── knowledge/              知识库 (8 份 YAML)
│   ├── diagnostic_knowledge.yaml    14 条故障规则
│   ├── event_patterns.yaml         10 种事件匹配规则
│   ├── causal_rules.yaml            6 条时序因果规则
│   └── ...
│
├── tools/                  诊断工具链 (10 个)
│   ├── log_ingestor.py            日志摄入 (支持 .yaml .log .json .mcap .atop)
│   ├── fault_library.py           故障匹配 (keyword/log/metric/timeline)
│   ├── experience_manager.py      经验库 (分片存储 + 规则追踪)
│   ├── session_archiver.py        归档面板 + 验证反馈
│   ├── import_tool.py             GUI 数据导入工具
│   └── verify_all.py              全功能验证脚本
│
├── data/                   运行时数据 (经验/归档/对话)
├── robot-logs/             日志投放目录
└── .pi/skills/             18 份诊断技能
```

---

## 诊断能力

| 数据源 | 支持格式 | 说明 |
|--------|---------|------|
| 文本日志 | `.log` `.txt` | 摔倒检测、模式切换、故障码 |
| ROS2 Bag | `.mcap` | 传感器/关节时序数据 |
| 配置文件 | `.yaml` `.json` | 状态快照、硬件配置 |
| 系统监控 | `.atop` | CPU/内存 (需 WSL) |

### 故障规则

内置 14 条故障规则，覆盖关节、传感器、电源、通信、运动五大类别。
诊断时自动匹配 + 时序因果推理 + 历史经验检索。

### 经验库

每次诊断自动沉淀，验证后自动修正。支持分片存储 (≤5MB/片)、索引加速、WAL 写保护。支持 100000+ 条经验，<20ms 检索。

---

## 多用户

| 场景 | 方式 |
|------|------|
| 共享经验库 | 设置 `MANASTONE_DATA_DIR` 环境变量指向共享目录 |
| 导入他人数据 | 双击 `tools\import_tool.py` → 选择对方的 data 文件夹 |
| 命令行导入 | `python tools\experience_manager.py import <路径>` |

---

## 从 v0.1 升级

v0.1 用户参考 [CHANGELOG.md](CHANGELOG.md) 了解完整变更。
主要变化：WSL+conda+npm → 原生 Windows；新增经验库、归档面板、时序推理。

---

## 依赖

- [Hermes Agent](https://hermes-agent.nousresearch.com) — AI Agent 框架
- Python 3.10+
- pyyaml / mcap / mcap-ros2-support
- atop (可选，WSL 内安装)

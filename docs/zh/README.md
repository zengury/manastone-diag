# Manastone 诊断助手

> 人形机器人离线故障诊断工具(AgiBot X2 Ultra · Unitree G1)— 拖入日志包 →
> 对话描述故障 → 三轮审查诊断 → 自动出报告 → 经验持续积累

[English README](../../README.md) · [快速开始](../QUICKSTART.md) ·
[规范文档](../SPEC.md) · [成熟度分级](../MATURITY.md) ·
[版本历史](../../CHANGELOG.md) · [溯源](../../SOURCES.md)

---

## 它做什么

机器人在现场摔倒了,有人丢给你一个 1GB 的日志 tar 包。manastone-diag 把它变成一份诊断报告:

1. **摄入** — `log_ingestor` 流式处理 `.log` `.yaml` `.json` `.mcap` `.atop`,
   产出精简的结构化事件流(隐私字段默认剥离,>1GB 不爆内存)
2. **匹配** — `fault_library` 用按机型分包的故障规则(中英文关键词)匹配症状与
   日志,并在事件时间线上做时序因果推理
3. **审查** — LLM agent 引导三轮审查(数据采集 → 诊断分析 → 报告),每轮等你确认
4. **积累** — 每次诊断自动归档;现场验证反馈回写经验库
   (分片存储 + WAL 写保护;实测 5000 条经验进程内检索约 15ms)

重活都在确定性的 Python 里完成,LLM 负责编排和解释。诊断全程本地运行,不需要联网。

## 快速开始

```bash
git clone https://github.com/zengury/manastone-diag.git
cd manastone-diag
pip install -r requirements.txt

# 全功能自检(应全绿,退出码 0)
python3 tools/verify_all.py

# 跑内置示例事故(X2 站立摔倒案例)
python3 tools/log_ingestor.py examples/sample-incident --robot agibot_x2 --output /tmp/diag-out

# G1 示例事故(过温保护降级案例)
python3 tools/log_ingestor.py examples/g1-sample-incident --robot g1 --output /tmp/g1-out
```

五分钟完整演示见 [QUICKSTART](../QUICKSTART.md)。

### 配合 LLM agent 使用

项目与 agent 框架解耦:核心资产是知识库(`knowledge/`)、工具链(`tools/`)
和诊断流程(`AGENTS.md`)。任何能读项目指令、能执行 shell 的 agent 框架都可以:

- **pi** — 运行 `./install.sh` 安装 pi 和 `manastone-diag` 启动命令;
  `.pi/` 内置技能文件和系统提示词
- **其他(Hermes、Claude Code 等)** — 让 agent 在仓库根目录工作即可,
  `AGENTS.md` 里是完整的三轮审查流程

## 使用方式

```
┌──────────────────────────────────────────────────────┐
│  三步完成诊断:                                        │
│  ① 提交日志 — 拖入 tar 包到 robot-logs/               │
│  ② 描述现象 — 告诉 agent 发生了什么                   │
│  ③ 逐轮确认 — agent 分三轮出报告,每轮等你确认         │
└──────────────────────────────────────────────────────┘
```

### 日常操作

| 操作 | 方式 |
|------|------|
| 启动诊断 | 在仓库目录启动你的 agent(如 `manastone-diag`) |
| 查看归档面板 | `./manage.sh`(Linux/macOS)或双击 `manage.bat`(Windows) |
| 导入其他用户数据 | `python3 tools/import_tool.py`(GUI) |
| 全功能验证 | `python3 tools/verify_all.py` |

### 诊断后验证

诊断完成后 agent 会提醒你去现场验证:

```
你: X2EXAMPLE00001 验证结果 correct
你: 验证 [1],诊断正确
你: 有哪些没验证?    ← 列出待验证列表
```

agent 自动更新经验库、修正规则权重。

## 数据源

| 数据源 | 支持格式 | 说明 |
|--------|---------|------|
| 文本日志 | `.log`(含切片 `.log_N`)`.txt` | 摔倒检测、模式切换、故障码 |
| ROS2 Bag | `.mcap` | 传感器/关节时序数据、关节对称性分析 |
| 配置文件 | `.yaml` `.json` | 状态快照、硬件配置 |
| 系统监控 | `.atop` | CPU/内存(Windows 下需 WSL) |

## 机型覆盖

知识库按机型分包(`tools/knowledge/`),每个包都有一个**覆盖成熟度等级**
([RCML,L0-L3](../MATURITY.md)),让你在依赖诊断结果之前知道该有什么预期:

| 机型 | 包 | 故障规则 | 成熟度 |
|------|-----|---------|--------|
| AgiBot X2 Ultra | `agibot_x2/` | 11 | **L2** · 场景级:能重建模式切换→摔倒因果链 · [实战案例](../cases/2026-05-x2-group-fall.md) |
| Unitree G1 | `unitree_g1/` | 8 | **L1** · 部件级:关节/传感器/灵巧手;摔倒诊断为初步 |

等级不是自封的:`scripts/check_maturity.py` 按可复现门槛(规则数、中英文关键词、
样例事故上真实触发因果链、主打场景覆盖)自动判级,**README 这张表虚标会直接让
CI 变红**。每个包还含事件模式、因果规则、本体和已知盲区清单
(`capability_boundary.yaml`),由 `scripts/check_knowledge.py` 校验。

**一起把你的机器人等级弄上去。**以上全部是 YAML,不用写 Python:
新增机型到 L0 就是复制一个目录改规则;L0→L1 是凑齐 8 条规则加一个样例事故;
L1→L2 是教会它你机器人的摔倒特征。每级的贡献清单见
[成熟度分级](../MATURITY.md)。有事故日志但不会写规则?
开 issue 贴脱敏日志片段,写规则是维护者最容易帮上忙的事。

## 多用户

| 场景 | 方式 |
|------|------|
| 共享经验库 | 设置 `MANASTONE_DATA_DIR` 环境变量指向共享目录 |
| 导入他人数据 | `python3 tools/import_tool.py` → 选择对方的 data 文件夹 |
| 命令行导入 | `python3 tools/experience_manager.py import <路径>` |

## 范围与边界

- **离线设计**:只消费导出的日志包,不连接机器人;不包含(私有的)Manastone
  runtime 内核代码。开源版唯一被许可的在线接口是 runtime 的公开 ledger 读
  API,当前版本未使用。详见 [SOURCES.md](../../SOURCES.md)。
- 机器人知识目前覆盖 **AgiBot X2 Ultra**(L2)与 **Unitree G1**(L1),
  等级含义见[机型覆盖](#机型覆盖);管线本身与机型无关,
  适配其他机器人见 [SPEC](../SPEC.md) 与[成熟度分级](../MATURITY.md)。

## 许可

本项目采用 [Apache License 2.0](../../LICENSE)（Apache-2.0）开源许可。

Copyright 2026 zengury。v2.x 改进(MCAP 关节解析、经验分片、归档面板)由
[thomastang237](https://github.com/thomastang237) 贡献。

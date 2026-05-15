# manastone-diag — 项目上下文

X2 Ultra 人形机器人离线故障诊断。通过 pi 与 LLM 对话完成诊断。

## 领域技能（启动时自动加载）

| 层 | 技能 | 说明 |
|----|------|------|
| universal | 热管理 · 通信故障 · 电源系统 · 传感器标定 · 平衡控制 | 跨机器人通用原理 |
| humanoid | 关节热管理 · 步态稳定 · 电源管理 · 传感器标定 · 通信故障 | 双足机器人共性 |
| instance/x2 | 关节过热 · 步态不稳 · 电源系统 · 通信故障 · 传感器标定 | X2 具体阈值 |

## 诊断工具（tools/ 目录）

| 工具 | 文件 | 调用方式 |
|------|------|---------|
| **LogIngestor** | `tools/log_ingestor.py` | `python3 -m tools.log_ingestor <log_dir> --robot agibot_x2 --output /tmp/out` |
| **McapReader** | `tools/mcap_reader.py` | `from tools.mcap_reader import McapReader` |
| **FaultLibrary** | `tools/fault_library.py` | `from tools.fault_library import FaultLibrary` |

LogIngestor 自动扫描 log/ bag/ info/ 目录，处理文本日志、MCAP bag、YAML、JSON，产出结构化事件流。

## 知识库（knowledge/ 目录，按需读取）

| 文件 | 用途 | 何时用 |
|------|------|--------|
| `knowledge/diagnostic_knowledge.yaml` | 14 条故障规则 | 第二轮，对照症状匹配 |
| `knowledge/capability_boundary.yaml` | 8 个已知盲区 | 第三轮，审核标注 |
| `knowledge/hardware.yaml` | 关节名、传感器 | 需精确查询硬件时 |
| `knowledge/interfaces.yaml` | ROS2 topic 清单 | 需知道数据在哪个 topic 时 |
| `knowledge/events.yaml` | 状态位、故障码语义 | 需解释 PMU bit 时 |
| `knowledge/actions.yaml` | 可执行动作 | 需验证操作合法性时 |

## 诊断方法

三轮审查法（详见 SYSTEM.md）：
1. 数据采集 — 运行 LogIngestor + McapReader
2. 诊断分析 — FaultLibrary 匹配 + 领域技能参考
3. 审核报告 — capability_boundary 盲区检查

## 约束
- 日志是现象不是原因
- 区分现场感知和真实故障
- 不确定时直接说「不确定」

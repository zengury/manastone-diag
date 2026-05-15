# manastone-diag

X2 Ultra 人形机器人离线故障诊断工具。

拖入日志包 → 对话描述故障 → 自动诊断出报告。

## 安装

```bash
git clone https://github.com/zengury/manastone-diag.git
cd manastone-diag
./install.sh
```

install.sh 会自动完成：
1. 安装 pi（npm）
2. 安装 Python 依赖（mcap、pyyaml）
3. 添加 manastone-diag 到 PATH

## 配置 LLM

```bash
# 任选一种，写入 ~/.zshrc 或 ~/.bashrc
export ANTHROPIC_API_KEY=sk-ant-...       # Claude
export OPENAI_API_KEY=sk-...              # OpenAI
export DEEPSEEK_API_KEY=sk-...            # DeepSeek

# 或首次启动后在对话中输入 /login 选择 provider
```

## 使用

```bash
manastone-diag
```

启动后看到引导框，三步完成诊断：

| 步骤 | 操作 | 说明 |
|------|------|------|
| ① | 拖入 tar 包或输入日志路径 | 支持 .tar 和目录 |
| ② | 描述故障现象 | 什么时间、机器人当时在做什么、有什么报错 |
| ③ | 逐轮确认 | 助手分三轮出报告，每轮等你确认 |

### 快捷操作

| 命令 | 功能 |
|------|------|
| `/hotkeys` | 查看所有快捷键 |
| `@` | 快速选择文件 |
| `Ctrl+C` | 取消当前操作 |

## 已内置

| 类别 | 内容 |
|------|------|
| **领域技能** | 15 份，三层架构（universal → humanoid → X2） |
| **故障知识库** | 14 条故障规则，覆盖关节、传感器、电源、通信、运动 |
| **能力盲区** | 8 个已知诊断局限 |
| **Ontology** | 硬件定义、接口清单、事件定义、动作列表 |
| **诊断工具** | LogIngestor（日志摄入）、McapReader（MCAP 回放）、FaultLibrary（故障匹配） |

## 分享经验

把故障案例写成 SKILL.md，放到 `.pi/skills/` 目录：

```markdown
---
name: 你的技能名称
description: 简要描述
---

# 技能标题

## 触发条件
- 症状 1
- 症状 2

## 诊断步骤
1. ...
2. ...

## 处理方案
- 立即: ...
- 短期: ...
```

下次启动自动加载。好的经验不该只留在一个人的脑子里。

## 依赖

- [pi](https://github.com/badlogic/pi-mono) — AI 编程助手（npm）
- Python 3.10+ — 诊断工具运行环境
- mcap + mcap-ros2-support — MCAP 文件读取
- pyyaml — 知识库解析

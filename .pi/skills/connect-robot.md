---
name: 实时连接机器人
description: 通过 SSH 连接到运行中的机器人 runtime，获取实时状态和硬件探针数据
---

# 实时连接机器人

当用户需要连接运行中的机器人进行实时诊断时使用。

## 前提

- 机器人上 runtime daemon 在运行
- 笔记本能 SSH 到机器人
- 用户提供了机器人 IP

## 连接命令

```bash
# 测试连通性
ssh agi@<机器人IP> "echo connected"

# 获取实时状态
ssh agi@<机器人IP> "cd ~/runtime && agent-runtime status"

# 单项查询
ssh agi@<机器人IP> "cd ~/runtime && agent-runtime get body.tilt_angle_deg"
ssh agi@<机器人IP> "cd ~/runtime && agent-runtime get system.battery_pct"
ssh agi@<机器人IP> "cd ~/runtime && agent-runtime get motion.mc_action"

# 四层硬件探针
ssh agi@<机器人IP> "cd ~/runtime && agent-runtime hardware-probe"
```

## 可用的实时查询

| 命令 | 用途 |
|------|------|
| `agent-runtime status` | 全部状态快照 |
| `agent-runtime get <资源ID>` | 单项查询 |
| `agent-runtime hardware-probe` | 硬件探针 |
| `agent-runtime intent get_all_joint_state` | 全关节状态 |

## 与离线诊断的关系

实时数据用于补充离线日志分析无法获取的信息：
- 当前关节温度（离线 MCAP 可能未录制）
- 硬件探针结果（只能在线获取）
- 电池、模式、姿态等即时状态

---
id: x2-gait-instability
name: X2 步态不稳处理
description: X2 步态不稳处理
layer: instance
category: mechanical
severity: critical
version: 1.0.0
author: roboonto-skills team
applies_to:
  robot: agibot_x2
  firmware: ">=0.8"
extends:
  - universal/balance-control-principles
  - humanoid/gait-stability
references:
  ontology:
    - robots/agibot_x2/ontology.yaml
  objects:
    - agibot_x2.hw.sensor.imu_chest
    - agibot_x2.hw.sensor.imu_torso
    - agibot_x2.if.topic.imu_chest
    - agibot_x2.if.topic.imu_torso
    - agibot_x2.action.set_forward_velocity
    - agibot_x2.action.set_lateral_velocity
    - agibot_x2.action.set_angular_velocity
    - agibot_x2.action.set_mc_action
---

# Skill: X2 步态不稳处理

## 引用上层 skill

- `universal/balance-control-principles`
- `humanoid/gait-stability`

## X2 vs G1 关键差异

| 项目 | G1 | X2 |
|---|---|---|
| IMU 数量 | 主 IMU | **双 IMU**(chest + torso) |
| IMU 频率 | 200Hz+ | 1000Hz max |
| 模式系统 | 简单 | 5 模式系统 |
| 步态参数 API | 直接调参 | 通过模式 + 速度 |

X2 的双 IMU 设计意味着:**冗余诊断**——两个 IMU 数据不一致时,可以确定是其中一个坏了。

## X2 数据查询

```bash
# 胸部 IMU
ros2 topic echo {{ ontology.if.topic.imu_chest }} --once

# 躯干 IMU
ros2 topic echo {{ ontology.if.topic.imu_torso }} --once

# 双 IMU 对比(关键诊断)
diff <(ros2 topic echo /aima/hal/imu/chest/state --once) \
     <(ros2 topic echo /aima/hal/imu/torso/state --once)
```

## X2 处置(模式优先,然后速度)

X2 的步态控制不直接调参数,而是通过**模式 + 速度**:

### 紧急稳定:切到 STAND_DEFAULT

```bash
# 立即停止运动,进入稳定站立
{{ ontology.action.set_mc_action }} STAND_DEFAULT my_agent
```

### 慢速行走

走跑模式下降速:

```bash
{{ ontology.action.set_forward_velocity }} 0.3 my_agent
```

注意 X2 启动门限:
- forward_velocity 静止起步必须 ≥ 0.09 m/s
- lateral_velocity 静止起步必须 ≥ 0.60 m/s
- angular_velocity 静止起步必须 ≥ 0.03 rad/s

低于门限会被 ontology precondition 拒绝。

### 紧急停止 + 失能

最严重情况(类似 humanoid 的紧急稳定):

```bash
# 切到 DAMPING 或 PASSIVE
{{ ontology.action.set_mc_action }} DAMPING_DEFAULT my_agent
```

## X2 双 IMU 诊断

如果两个 IMU 读数差异 > 5%,执行:

1. 不要重启估计器(可能用错误的数据初始化)
2. 静止机器人 10s
3. 看哪个 IMU 静态读数更接近物理值(g = 9.81 m/s²)
4. 标记另一个为可疑,准备替换

## X2 暂未建立的案例库

(占位)

## 引用资源

- AimDK 文档 §1.6 传感器
- AimDK 文档 §5.4.1 IMU 接口
- {{ ontology.schema.msg.imu }}

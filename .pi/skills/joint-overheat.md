---
id: x2-joint-overheat
name: X2 关节过热处理
layer: instance
category: thermal
severity: high
version: 1.0.0
author: roboonto-skills team
applies_to:
  robot: agibot_x2
  firmware: ">=0.8"
extends:
  - universal/thermal-management-principles
  - humanoid/joint-thermal-management
references:
  ontology:
    - robots/agibot_x2/ontology.yaml
  objects:
    - agibot_x2.hw.left_arm.*
    - agibot_x2.hw.right_arm.*
    - agibot_x2.hw.left_leg.*
    - agibot_x2.hw.right_leg.*
    - agibot_x2.hw.waist.*
    - agibot_x2.hw.head.*
    - agibot_x2.event.bms.*
    - agibot_x2.action.set_forward_velocity
    - agibot_x2.if.topic.joint_arm_state
    - agibot_x2.if.topic.joint_leg_state
triggers:
  - id: T1
    description: 关节温度警告
    ontology_field: agibot_x2.hw.joint.*.coil_temp
    operator: ">="
    value: 60
    severity: warning
  - id: T2
    description: 关节温度危险
    ontology_field: agibot_x2.hw.joint.*.coil_temp
    operator: ">="
    value: 70
    severity: critical
  - id: T3
    description: 电芯放电过温
    ontology_field: agibot_x2.event.bms.cell_discharge_overtemp
    operator: "=="
    value: true
    severity: error
---

# Skill: X2 关节过热处理

## 引用上层 skill

阅读本 skill 前请先理解:
- `universal/thermal-management-principles`
- `humanoid/joint-thermal-management`

本 skill 只覆盖 **X2 (灵犀) 特定**的内容。

## X2 vs G1 的差异(重要)

| 项目 | G1 | X2 |
|---|---|---|
| 扭矩档位 | 全部 120 Nm 一刀切 | **7 档**(0.6 / 2.6 / 4.8 / 24 / 36 / 48 / 120) |
| 温度报警阈值 | 45°C / 50°C | 60°C / 70°C(更高,主动降功率) |
| 关节命名 | `left_knee_joint` | `agibot_x2.hw.left_leg.knee` |
| 温度查询字段 | `motor_temperature` | `coil_temp` 与 `motor_temp`(分离) |
| 模式系统 | 简单 | 5 模式(passive/damping/joint/stand/locomotion) |

**关键差异**:X2 有 7 档真实 effort_limit(头关节最低 0.6 Nm),热设计裕度比 G1 大,
但**头部和手腕关节绝对不能按腿部那样过驱**——会瞬间烧电机。

## X2 阈值表

| 关节类型 | warning | critical | effort_limit (Nm) |
|---|---|---|---|
| 腿部主关节(hip pitch/roll/yaw, knee) | 60°C | 70°C | **120** |
| 踝关节(pitch) | 55°C | 65°C | 36 |
| 踝关节(roll) | 50°C | 60°C | 24 |
| 腰(pitch/roll) | 55°C | 65°C | 48 |
| 肩(pitch/roll) | 50°C | 60°C | 36 |
| 肘 / 肩 yaw / 腕 yaw / 踝 roll | 50°C | 60°C | 24 |
| 腕 pitch/roll | 45°C | 55°C | **4.8** |
| 头 yaw | 40°C | 50°C | **2.6** |
| 头 pitch | 40°C | 50°C | **0.6** |

## X2 数据查询命令

X2 关节按部位分组,用对应 topic:

```bash
# 全部手臂关节状态(14 关节)
ros2 topic echo {{ ontology.if.topic.joint_arm_state }} --once

# 全部腿部关节状态(12 关节)
ros2 topic echo {{ ontology.if.topic.joint_leg_state }} --once

# 头部 + 腰部
ros2 topic echo /aima/hal/joint/head/state --once
ros2 topic echo /aima/hal/joint/waist/state --once
```

## X2 处置 Action

**降速**(走跑模式下):
调用 {{ ontology.action.set_forward_velocity }},`forward_velocity = 0.3`(从 0.8 降),
注意 X2 启动门限 0.09 m/s,不能直接发更小的值。

**切换模式停止运动**:
调用 {{ ontology.action.set_mc_action }},切到 `DAMPING_DEFAULT` 进入安全状态。

## X2 特有的故障联动

X2 的 PMU 把电池过温和关节负载关联:

- 当 `agibot_x2.event.bms.cell_discharge_overtemp` 触发时,
  说明放电电流过大或电池本身过热。
- 此时即使关节本身温度正常,也应该降低关节负载——电池热失控会先于关节失控。
- **诊断顺序**:遇到关节温升先看电池状态,再看关节本身。这是 X2 特有的关联诊断,
  G1 由于电池散热设计不同,关联性较弱。

## X2 暂未建立的案例库

(占位,等待真实运维数据补充)

迁移自 G1 案例的等价 X2 推断:

### G1 CASE-001 → X2 等价场景
- G1 是"左膝过热"
- X2 等价:`agibot_x2.hw.left_leg.knee` 过热
- X2 阈值不同(60°C 而非 45°C),处置同(降速)
- X2 启动门限考量:不能盲目降到极慢速,会被 ontology precondition 拒绝

## 引用资源

- AimDK 文档 §1.7 关节活动范围
- {{ ontology.if.topic.pmu_state }} msg schema(包含 BMS 状态位)
- {{ ontology.priority.safety_l10 }} 用于过热预警 TTS

## 待补充

- [ ] X2 真实运维案例(等运维记录积累)
- [ ] X2 特有的关节维护周期(等厂商提供)
- [ ] X2 与温度相关的预设动作禁用列表

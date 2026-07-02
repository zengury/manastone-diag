---
id: x2-power-system
name: X2 电源系统故障处理
layer: instance
category: electrical
severity: critical
version: 1.0.0
author: roboonto-skills team
applies_to:
  robot: agibot_x2
  firmware: ">=0.8"
extends:
  - universal/power-system-principles
  - humanoid/power-management
references:
  ontology:
    - robots/agibot_x2/ontology.yaml
  objects:
    - agibot_x2.hw.power
    - agibot_x2.event.pmu.*
    - agibot_x2.event.bms.*
    - agibot_x2.if.topic.pmu_state
triggers:
  - id: T_PMU_OVERTEMP
    description: 48V 总线过温
    ontology_event: agibot_x2.event.pmu.bus48v_overtemperature
    severity: error
  - id: T_PMU_OVERCURRENT
    description: 48V 总线过流
    ontology_event: agibot_x2.event.pmu.bus48v_overcurrent
    severity: error
  - id: T_BMS_SHORT
    description: 电池短路
    ontology_event: agibot_x2.event.bms.short_circuit
    severity: fatal
  - id: T_BMS_CELL_OVERTEMP_DISCHARGE
    description: 电芯放电温度超上限
    ontology_event: agibot_x2.event.bms.cell_discharge_overtemp
    severity: error
  - id: T_BMS_CELL_OVERVOLT
    description: 电芯过压
    ontology_event: agibot_x2.event.bms.cell_overvoltage
    severity: warning
  - id: T_BMS_CELL_UNDERVOLT
    description: 电芯欠压
    ontology_event: agibot_x2.event.bms.cell_undervoltage
    severity: warning
---

# Skill: X2 电源系统故障处理

## 引用上层 skill

- `universal/power-system-principles`
- `humanoid/power-management`

## X2 电源架构(关键差异)

X2 的电源架构比 G1 更复杂,包括:

- **PMU**(Power Management Unit):管理 48V/12V/5V 三条主总线
- **BMS**(Battery Management System):管理电池组
- 以上两者通过 ontology 暴露 11 + 21 = 32 位状态位 → 可逐位定位故障

| 项目 | G1 | X2 |
|---|---|---|
| 状态报告粒度 | 通常几个汇总字段 | **32 位状态位** |
| 总线层级 | 单总线 | 48V / 12V / 5V 三层 |
| 故障定位 | 需要外部诊断 | ontology 内置位语义 |
| 电池容量 | 取决于型号 | **421 Wh** |
| 充电时间 | 2-3h | < 1.5h |

X2 电源系统的最大优势是**可观测性极高**——任何电源异常都能用 ontology 直接翻译。

## X2 阈值表

| 项目 | warning | critical |
|---|---|---|
| 电池电量 | < 20% | < 10% |
| 电池温度 | > 55°C | > 60°C |
| 充电温度窗口 | < 5 或 > 40°C | / |
| 持续放电电流 | / | 看 BMS 触发 |

## X2 优先级 1 红线动作

PMU/BMS 中以下事件触发,**立即 critical 响应**:

| 事件 | 立即动作 |
|---|---|
| `bms.short_circuit`(fatal) | 软件不可控,期待 BMS 自动断开,人工断电检查 |
| `bms.cell_discharge_overtemp`(error) | 立即 DAMPING 模式 + 通风 |
| `pmu.bus48v_overtemperature`(error) | 减小整机负载,排查热源 |
| `pmu.bus48v_overcurrent`(error) | 立即停止运动指令 |

## X2 PMU/BMS 状态位查询

X2 的优势在于位级查询,语法:

```bash
# 全部 PMU 状态(11 位)
ros2 topic echo {{ ontology.if.topic.pmu_state }} --once

# 把 raw bitmap 翻译成语义
# 查看 knowledge/events.yaml 中对应 status bit 的定义
# 或读取 knowledge/interfaces.yaml 找对应 topic
```

诊断时**先用语义翻译**,不要看 raw 数字。

## X2 充放电特性

X2 BMS 监控字段(可查 {{ ontology.schema.msg.pmu_state }}):

- `battery_voltage`(总电压)
- `battery_current`(充正放负)
- `battery_remaining_capacity_percentage`
- `battery_cycle_count`
- `battery_temperature`
- `battery_balance_line_resistance`(均衡线电阻)

## X2 与 G1 的处置差异

### 充电

X2 充电速度比 G1 快(< 1.5h vs 2-3h),但需要注意:
- X2 充电窗口比 G1 窄(5-40°C 而非 0-45°C)
- 北方场地冬季要预热到 5°C 才能开始充电

### 模式联动

X2 有 5 个模式,电源故障时模式选择:
- `bms.cell_discharge_overtemp` 触发 → 切到 `DAMPING_DEFAULT`(参考 ontology)
- `pmu.bus48v_overcurrent` 触发 → 切到 `PASSIVE_DEFAULT`(零力矩,最低功耗)

切换 action 见 {{ ontology.action.set_mc_action }}。

## X2 暂未建立的案例库

(占位,等运维数据)

## 引用资源

- AimDK 文档 §5.4.2 PMU + BMS
- {{ ontology.schema.msg.pmu_state }} 完整字段表

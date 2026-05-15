---
id: x2-sensor-calibration
name: X2 传感器标定
description: X2 传感器标定
layer: instance
category: software
severity: medium
version: 1.0.0
author: roboonto-skills team
applies_to:
  robot: agibot_x2
  firmware: ">=0.8"
extends:
  - universal/sensor-calibration-principles
  - humanoid/sensor-calibration
references:
  ontology:
    - robots/agibot_x2/ontology.yaml
  objects:
    - agibot_x2.hw.sensor.imu_chest
    - agibot_x2.hw.sensor.imu_torso
    - agibot_x2.if.topic.imu_chest
    - agibot_x2.if.topic.imu_torso
---

# Skill: X2 传感器标定

## 引用上层 skill

- `universal/sensor-calibration-principles`
- `humanoid/sensor-calibration`

## X2 vs G1 关键差异

| 项目 | G1 | X2 |
|---|---|---|
| IMU 数量 | 主 IMU | **双 IMU**(chest + torso) |
| IMU 标定方式 | 单个标定 | **双 IMU 协同标定** |
| 关节零位 | 机械标记对齐 | (待 SDK 文档明确) |
| 关节命名 | `left_knee_joint` | `agibot_x2.hw.left_leg.knee` |
| 标定 service 路径 | `/rt/calibration/*` | `/aima/calibration/*`(待文档确认) |

## X2 双 IMU 标定的特殊性

X2 的双 IMU 提供**冗余诊断能力**——这是 X2 比 G1 优越的地方,但也带来标定上的特殊考虑:

### 双 IMU 一致性验证

标定前 + 标定后,都应做"双 IMU 一致性测试":

```bash
# 静止 10 秒
# 同时记录两个 IMU
ros2 topic echo {{ ontology.if.topic.imu_chest }} --once
ros2 topic echo {{ ontology.if.topic.imu_torso }} --once

# 比较加速度向量(应基本一致,差异 < 1%)
# 比较角速度(应都接近 0)
```

如果两个 IMU 静止读数差异 > 1%:
- 不要做标定(会用错误数据初始化)
- 先排查物理安装问题(松动、变形)
- 再决定是否需要更换

### 双 IMU 协同初始化

X2 的状态估计器同时融合两个 IMU,标定时应:
1. 分别标定 chest 和 torso 各自的零偏
2. 标定相对外参(两 IMU 之间的安装关系)
3. 让估计器重新初始化融合参数

## X2 标定命令(占位,等 SDK 文档确认)

```bash
# 完整标定(待确认)
# ros2 service call /aima/calibration/full ...

# 单 IMU 标定
# ros2 service call /aima/calibration/imu/chest ...
# ros2 service call /aima/calibration/imu/torso ...
```

> ⚠️ X2 SDK 标定接口尚未在我们的 ontology 里完整登记。
> 这部分需要从 AimDK 文档第 §X 章补完后才能给出确定命令。
> 当前以**通用流程**指引,具体命令请查 AimDK。

## X2 标定的预热时间

X2 在工厂部署中,推荐:
- 上电后预热 5 分钟再标定
- 高温(夏季工厂)再多预热 5 分钟
- 低温(北方冬季)预热 10 分钟以上(参考 x2/power-system 充电温度窗口)

## X2 标定数据管理

参考 universal:标定参数是机器人个体身份。X2 多板架构需要注意:
- 各板的标定参数分散存储(PC1 关节、PC2 IMU、PC3 待定)
- 备份必须**全板一起做**,单板备份不完整
- 跨板恢复必须先停所有节点

## X2 暂未建立的案例库

(占位,等运维数据)

## 引用资源

- AimDK 文档 §1.6 传感器
- AimDK 文档 §X 标定接口(待补完后引用具体章节)

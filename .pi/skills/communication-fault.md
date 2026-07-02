---
id: x2-communication-fault
name: X2 通信故障处理
description: X2 通信故障处理
layer: instance
category: communication
severity: medium
version: 1.0.0
author: roboonto-skills team
applies_to:
  robot: agibot_x2
  firmware: ">=0.8"
extends:
  - universal/communication-fault-principles
  - humanoid/communication
references:
  ontology:
    - robots/agibot_x2/ontology.yaml
  objects:
    - agibot_x2.hw.compute.pc1
    - agibot_x2.hw.compute.pc2
    - agibot_x2.hw.compute.pc3
    - agibot_x2.if.topic.*
---

# Skill: X2 通信故障处理

## 引用上层 skill

- `universal/communication-fault-principles`
- `humanoid/communication`

## X2 vs G1 通信架构差异

X2 是**三计算单元**架构,通信复杂度比 G1 高一个量级:

```
PC1 运动控制(10.0.1.40)  ← 实时,禁部署二开程序
   │ Ethernet
PC2 开发(10.0.1.41,Jetson Orin NX)  ← 二开主战场
   │ Ethernet
PC3 交互(10.0.1.42,RK3588)  ← 媒体文件,语音
```

X2 的关键纪律(参考 humanoid/communication 第 2 点):

- **跨板 ROS service 不可靠** —— 文档明确说明,关键控制必须本板内闭环
- **大流量传感器(双目相机 90 MB/s)绝对不能跨板订阅**
- **媒体文件必须放 PC3**(且全员可读)

## X2 各 topic 跨板特性

参考 ontology 中各 topic 的 `cross_unit_safe` 字段,典型如:

| Topic | compute_unit | cross_unit_safe |
|---|---|---|
| `/aima/hal/sensor/lidar_chest_front/...` | PC2 | **false**(10MB/s) |
| `/aima/hal/sensor/stereo_head_front_left/...` | PC2 | **false**(90MB/s 不行) |
| `/aima/hal/imu/chest/state` | PC2 | true |
| `/aima/hal/pmu/state` | PC2 | true |
| `/aima/mc/locomotion/velocity` | PC1 订阅 | true(命令小) |

X2 诊断准则:**任何"为什么我从 PC2 订阅 PC1 的 topic 这么慢"的问题——
看 ontology 的 cross_unit_safe 字段,大概率是不该跨。**

## X2 数据查询(分三层)

### 物理层

```bash
# 测三板连通性
ping 10.0.1.40   # PC1
ping 10.0.1.41   # PC2
ping 10.0.1.42   # PC3
```

### 协议层

```bash
# 在每块板分别看 topic
ros2 topic list | grep aima

# 跨板订阅效果(在 PC1 看 PC2 发布的 topic)
ros2 topic hz /aima/hal/imu/chest/state
```

### 应用层

X2 的 msg 都用 aimdk_msgs 包,序列化版本应该一致(同一固件内)。
跨固件版本可能字段变,例如新版加 IMU 字段——参考 DIFF_REPORT 类工作。

## X2 处置

### 跨板控制问题

如果跨板 service 调不通(见 X2 已知特性):
- 改用 topic 通信(可靠性更好)
- 或者把客户端部署到 service 提供方所在板

### 流量过载问题

X2 高流量 topic(双目 90MB/s 等)优化:
- 使用 image_transport 压缩订阅(从 raw 改为 compressed)
- 降低分辨率或帧率
- 关键算法部署到数据所在板,避免远程订阅

## X2 完全通信中断应急

参考 universal 应急流程,X2 特定步骤:

1. 安全姿态:用紧急按钮或 PASSIVE_DEFAULT(若软件还能响应)
2. 优先恢复 PC1(运控)— 失去 PC1 = 完全失控
3. PC2/PC3 故障可暂时容忍

## X2 暂未建立的案例库

(占位,等运维数据)

## 引用资源

- AimDK 文档 §1.3 计算单元
- AimDK 文档 §5.4.1 各 topic 表(含 cross_unit_safe)

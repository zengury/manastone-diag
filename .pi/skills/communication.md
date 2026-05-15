---
id: humanoid-communication
name: 双足机器人通信特殊性
description: 双足机器人通信特殊性
layer: humanoid
category: communication
severity: medium
version: 1.0.0
author: roboonto-skills team
extends:
  - universal/communication-fault-principles
---

# Skill: 双足机器人通信特殊性

## 适用范围

双足人形机器人。

## 双足的通信特殊性

### 1. 关节通信高频高优先级

双足 30+ 关节的实时控制需要 **1kHz 级**的关节状态同步。**任何 5ms 以上的延迟**
都会引起平衡控制器的明显震荡。这是双足比四足/轮式更苛刻的地方。

实际意义:
- 双足绝对不能跑 WiFi(延迟和抖动太大)
- 双足绝对不能跨节点用普通 ROS QoS 默认值
- 关键控制 topic 必须 best_effort + 低延迟优先

### 2. 多板通信常见

人形机器人通常有多块计算板:
- 运控板(实时,处理关节)
- 主控板(应用,处理 LLM、规划)
- 交互板(感知、显示)

板间通信容易出问题:
- 跨板的 ROS service 几乎都不稳定
- 关键控制必须本板内闭环

### 3. 通信故障的"伪平衡问题"

双足平衡控制对通信极其敏感,**不稳的第一假设是通信**——
参考 humanoid/gait-stability,任何不稳问题都先看通信。

## 双足扩展 universal 三步

### 物理层补充

双足特有物理风险:
- 摔倒可能弄松接口
- 关节运动持续拉扯线缆(疲劳风险)
- 电池仓震动可能影响连接器

每周检查一次接口紧固度。

### 协议层补充

双足通信的**经验值**(各家略有不同,但量级一致):

- 关节状态 topic:1000Hz,数据量小,要求低延迟
- IMU topic:500-1000Hz,要求低延迟 + 时间戳精度
- 视觉/激光:10-30Hz,数据量大,可以忽略延迟
- 控制命令:100Hz 即可,但要可靠送达

## 不在本 skill 范围

- 具体的 IP / 端口配置
- 具体的 DDS 实现(FastDDS / CycloneDDS / 厂商私有)
- 具体的 ROS topic 名

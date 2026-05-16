# 机器人故障诊断报告

**报告编号**: DIAG-20260429-001  
**机器人**: X2 Ultra (SN: X220028C4Z0079)  
**故障时间**: 2026-04-29 10:38:22  
**日志来源**: X220028C4Z0079_soc0_20260429_1025_20260429_1155.tar  
**分析工具**: manastone-diag v0.1.0  
**方法论**: 三层审查诊断法  
**分析日期**: 2026-05-15

---

## 一、诊断结论

### 遥控器误操作触发 JOINT_DEFAULT（位控模式）导致站立摔倒

| 属性 | 值 |
|------|-----|
| **置信度** | ★★★★★★★★★☆ (9/10) |
| **严重度** | 🔴 CRITICAL |
| **根因** | 遥控器 L2+X 误触 → JOINT_DEFAULT 位控模式 → 失去主动平衡 → 摔倒 |

**一句话结论**: 操作员在 STAND_DEFAULT 站立状态下误触遥控器 L2+X，系统允许了 STAND_DEFAULT → JOINT_DEFAULT 的非法模式切换。进入位控模式后机器人失去主动平衡控制，约 1 秒内躯干倾斜至 80° 后摔倒。

### 工厂反馈对照

| 工厂反馈 | 日志证据 | 一致？ |
|---------|---------|:---:|
| 「越野模式切换到站立模式」 | 10:37:29 洪水式 STAND_DEFAULT 切换 | ✅ |
| 「然后又切换到为位控模式」 | 10:38:22 JOINT_DEFAULT 切换 | ✅ |
| 「失去平衡摔机」 | 10:38:23 Detect Falling (0.8→1.4 rad) | ✅ |
| 「误操作遥控误切了位控(L2+X)」 | 多线程并发 STAND_DEFAULT 请求 → 遥控器按键卡住特征 | ✅ |
| 「导致站立摔倒」 | 进入 JOINT_DEFAULT 后 1 秒内摔倒 | ✅ |

---

## 二、事件时间线

```
10:37:29  遥控器按键卡住 → STAND_DEFAULT 洪水式并发（多线程同时请求）
10:37:46  LOCOMOTION_STEP 洪水式并发
10:38:15  STAND_DEFAULT 再次洪水式并发
10:38:22  🔴 JOINT_DEFAULT 洪水式并发 ← L2+X 触发
10:38:22  StatusDecider fallback: STAND_DEFAULT → JOINT_DEFAULT
10:38:22  Current Action: JOINT_DEFAULT | Status: RUNNING
10:38:23  🚨 Detect Falling: torso 0.80 → 1.40 rad (< 1秒)
```

---

## 三、证据明细

### 3.1 遥控器误操作特征（洪水式并发）

```
10:37:29  设置ACTION切换, 目标Action STAND_DEFAULT  (线程2822)
10:37:29  设置ACTION切换, 目标Action STAND_DEFAULT  (线程2823)
10:37:29  设置ACTION切换, 目标Action STAND_DEFAULT  (线程2818)
10:37:29  设置ACTION切换, 目标Action STAND_DEFAULT  (线程2824)
... 同一毫秒内多个线程同时请求同一操作 → 按键卡住特征
```

### 3.2 JOINT_DEFAULT 切换

```
10:38:22  🏁 Current Action: JOINT_DEFAULT | Status: RUNNING
10:38:22  StatusDecider fallback: STAND_DEFAULT -> JOINT_DEFAULT
```

**注意**: StatusDecider 用了 "fallback" 而不是 "transition" —— 说明系统识别到这不是正常迁移路径，但仍执行了切换。

### 3.3 摔倒过程

```
10:38:23.778  Detect Falling: t_gyro:2.37, torso:0.80, chest:0.82
10:38:23.814  Detect Falling: t_gyro:2.49, torso:0.88, chest:0.90
10:38:23.914  Detect Falling: t_gyro:2.85, torso:1.13, chest:1.15
10:38:23.978  Detect Falling: t_gyro:2.90, torso:1.31, chest:1.32
10:38:24.014  Detect Falling: t_gyro:2.82, torso:1.40, chest:1.41
```

torso 从 0.80 rad (46°) 到 1.40 rad (80°) 仅用时约 200ms。

### 3.4 此前诊断中发现的独立问题

| 时间 | 事件 | 与本次事故关系 |
|------|------|:--:|
| 10:22:11 | EtherCAT crash #1 (wkc -1) | 无关 |
| 10:27:03 | PASSIVE→STAND 模式切换卡死 | 无关 |
| 11:04:18 | EtherCAT crash #2 (wkc -1) | 无关 |

EtherCAT 崩溃是独立事件，与摔倒无关。我第一轮诊断中误将其作为主因，审核轮修正。

---

## 四、安全建议

ontology (`behaviors.yaml`) 中已明确定义 JOINT_DEFAULT 只能从 PASSIVE_DEFAULT 进入，且要求「机器人已下降至地面双脚触地」。但运行时 StatusDecider 的 fallback 逻辑绕过了此约束。

已向 runtime 维护团队提交安全约束建议文档: `docs/SAFETY_CONSTRAINT_JOINT_DEFAULT.md`

---

## 五、审核备注

### 第一轮漏采的教训

本次诊断最初完全漏掉了摔倒事件和模式切换——因为 LogIngestor 只采集 error/warning 级别事件，而「Detect Falling」的 Warning 没有匹配模式，「设置ACTION切换」是 Info 级别被过滤。

**已修复**: LogIngestor 新增 `falling_event` 和 `mode_transition` 模式，提升至 critical 级别，永不截断。

### 能力盲区

| 盲区 | 影响 |
|------|------|
| mode_switch 已知假阳性 bug | StatusDecider fallback 可能与此相关 |

---

**报告完成。**

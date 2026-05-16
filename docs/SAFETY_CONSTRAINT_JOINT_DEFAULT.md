# 模式切换安全约束建议

**来源**: manastone-diag 诊断案例 X220028C4Z0079  
**日期**: 2026-04-29  
**提交给**: zengury/runtime 维护团队

---

## 事故概述

X2 Ultra (SN: X220028C4Z0079) 在 `STAND_DEFAULT` 站立状态下，操作员误触遥控器 L2+X，系统执行了 `STAND_DEFAULT → JOINT_DEFAULT` 切换。约 1 秒后机器人失去平衡摔倒。

### 日志证据

```
10:38:22.588  设置ACTION切换, 目标Action JOINT_DEFAULT
10:38:22.614  Current Action: JOINT_DEFAULT | Status: RUNNING
10:38:22.669  StatusDecider fallback: STAND_DEFAULT -> JOINT_DEFAULT
10:38:23.778  Detect Falling: t_gyro:2.37, torso:0.80, chest:0.82
10:38:23.914  Detect Falling: t_gyro:2.85, torso:1.13, chest:1.15
10:38:24.014  Detect Falling: t_gyro:2.82, torso:1.40, chest:1.41
```

**切换后约 1 秒内躯干倾斜从 0.8 → 1.4 rad（约 46° → 80°）。**

---

## 已确认：ontology 未覆盖此约束

`behaviors.yaml` 中 JOINT_DEFAULT 的迁移路径：

```yaml
# 唯一允许进入 JOINT_DEFAULT 的路径：
- type: transitions_to
  source: agibot_x2.mode.passive_default        # 仅允许从 PASSIVE_DEFAULT 进入
  target: agibot_x2.mode.joint_default
  properties:
    trigger: "遥控 L2+X"
    requires: "机器人已下降至地面双脚触地"

# STAND_DEFAULT → JOINT_DEFAULT 不在 ontology 中！
```

但运行时**不检查** ontology 的 `transitions_to` 约束。StatusDecider 执行了 `fallback: STAND_DEFAULT -> JOINT_DEFAULT`，绕过了 ontology 定义。`requires` 字段（「机器人已下降至地面双脚触地」）也没有被运行时强制执行。

---

## 待确认

| # | 问题 |
|---|------|
| 1 | 11 条安全检查中第 8 条「模式-关节匹配」是否可扩展为「模式进入条件」检查？ |
| 2 | StatusDecider fallback 为何绕过了 ontology 的 transitions_to 定义？是设计如此还是 bug？ |
| 3 | `requires` 字段目前是否有任何代码在执行时读取并验证？ |

---

## 建议修复

### 方案 A：在 ontology 的 transitions_to 被运行时强制执行前，加一条 safety check

`agent_runtime/safety_checks.py` 新增：

```python
# 12. JOINT_DEFAULT 进入条件
_mode_requires_ground = {"JOINT_DEFAULT", "SIT_JOINT_DEFAULT", "SIT_DOWN_DEFAULT"}
if intent.action in _mode_requires_ground:
    current = registry.get("motion.mc_action")
    if current and current.value in ("STAND_DEFAULT", "LOCOMOTION_DEFAULT", "LOCOMOTION_STEP"):
        return DENY, f"{intent.action} not allowed in standing/locomotion mode"
```

### 方案 B：运行时读取 ontology 的 transitions_to

让 safety_check 在运行时读取 `behaviors.yaml` 中的 `transitions_to` 规则，拒绝不在列表中的迁移路径。

---

## 相关 reference

- `behaviors.yaml`: JOINT_DEFAULT 定义 + transitions_to 规则
- `derived_links.yaml`: 补充的 allows/transitions_to 链接
- `safety_checks.py`: 11 条安全检查
- `capability_boundary.yaml`: mode_switch 已知 SetMcAction 假阳性 bug
- `PRODUCT_SPEC § 7`: 安全系统架构

---

*生成: manastone-diag v0.1.0*

---
applies_to: unitree_g1
---

# Skill: 通信故障处理

## 元信息

- **id**: communication-fault
- **name**: 通信故障
- **category**: communication
- **severity**: medium
- **version**: 1.0.0
- **author**: G1 Maintenance Team
- **related_components**: ["network", "dds", "ethernet", "can"]

---

## 触发条件

```yaml
triggers:
  - id: T1
    name: 话题延迟高
    condition: "topic.latency > 50ms"
    severity: notice
    
  - id: T2
    name: 话题丢失
    condition: "topic.lost_rate > 0.05"
    severity: warning
    
  - id: T3
    name: 心跳超时
    condition: "heartbeat.missed > 3"
    severity: critical
    
  - id: T4
    name: 数据包错误率高
    condition: "packet.error_rate > 0.01"
    severity: warning
```

---

## 通信架构概览

```
G1 通信拓扑
═══════════════════════════════════════════════════════════════

┌─────────────────────────────────────────────────────────────┐
│                     主控计算机                               │
│              (运行 MCP Server + ROS2)                       │
└──────────────────────┬──────────────────────────────────────┘
                       │ Ethernet (千兆)
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                    运动控制板                                │
│              (Unitree SDK2 控制器)                          │
└──────┬───────────────┬───────────────┬───────────────────────┘
       │               │               │
       ▼               ▼               ▼
  ┌─────────┐    ┌─────────┐    ┌─────────┐
  │ 左腿驱动 │    │ 右腿驱动 │    │ 躯干驱动 │
  │ (CAN)   │    │ (CAN)   │    │ (CAN)   │
  └────┬────┘    └────┬────┘    └────┬────┘
       │               │               │
       ▼               ▼               ▼
    [关节电机]      [关节电机]      [关节电机]
```

---

## 故障诊断

### 诊断命令

```bash
# 1. 检查网络连通性
ping 192.168.123.10  # 运动控制板IP

# 2. 检查话题发布频率
ros2 topic hz /rt/lowstate

# 3. 检查话题延迟
ros2 topic delay /rt/lowstate

# 4. 查看 DDS 连接状态
ros2 daemon status
ros2 node list
ros2 node info /g1_node

# 5. 网络带宽检查
iftop -i eth0

# 6. 查看丢包率
netstat -s | grep -i drop
```

---

## 常见故障

### A. 话题延迟高 (Latency High)

**正常值**: < 10ms (本机), < 30ms (局域网)

**可能原因**:
1. 网络带宽不足
2. 数据量过大 (如原始点云)
3. DDS配置不当
4. 系统负载高

**处理**:

```bash
# 1. 检查带宽占用
sudo nethogs

# 2. 检查CPU负载
top

# 3. 优化 DDS QoS
# 编辑 qos_profile.yaml
history:
  depth: 10  # 减小历史深度
reliability: best_effort  # 对实时性要求高的topic
```

**优化策略**:
- 降低非关键topic的发布频率
- 使用数据压缩
- 调整 DDS 缓冲区大小

---

### B. 话题丢失 (Topic Lost)

**症状**: 订阅端收不到消息，或消息不连续

**排查**:

1. **检查发布端**
   ```bash
   ros2 topic info /rt/lowstate
   # 确认Publisher数量
   ```

2. **检查网络连接**
   ```bash
   # 检查网线连接
   ethtool eth0 | grep "Link detected"
   
   # 检查IP配置
   ip addr show eth0
   ```

3. **检查防火墙**
   ```bash
   sudo ufw status
   # DDS使用随机端口，可能需要开放
   ```

4. **重启DDS守护进程**
   ```bash
   ros2 daemon stop
   ros2 daemon start
   ```

---

### C. 心跳超时 (Heartbeat Timeout)

**症状**: 控制板报告与上位机通信中断

**处理**:

1. **检查物理连接**
   - 网线是否插紧
   - 网口指示灯是否正常 (绿灯常亮，黄灯闪烁)

2. **检查IP配置**
   ```bash
   # 主控机IP应为 192.168.123.2
   # 控制板IP应为 192.168.123.10
   
   ping 192.168.123.10
   ```

3. **检查路由**
   ```bash
   ip route
   # 确保有到 192.168.123.0/24 的路由
   ```

4. **重启控制板** (如上述无效)
   - 断电重启运动控制板
   - 等待30秒启动完成

---

### D. 数据包错误 (Packet Error)

**症状**: 数据 CRC 错误，或解析异常

**可能原因**:
- 网线质量差
- 电磁干扰
- 接口氧化

**处理**:
1. 更换高质量网线 (Cat6以上)
2. 检查接地
3. 清洁网口

---

## 通信优化配置

### DDS 调优

```xml
<!-- dds_config.xml -->
<dds>
  <profiles>
    <profile name="G1Realtime">
      <transport_descriptors>
        <transport_descriptor>
          <transport_id>udp_realtime</transport_id>
          <type>UDPv4</type>
          <sendBufferSize>1048576</sendBufferSize>
          <receiveBufferSize>1048576</receiveBufferSize>
        </transport_descriptor>
      </transport_descriptors>
      
      <participant profile_name="realtime_participant">
        <rtps>
          <userTransports>
            <transport_id>udp_realtime</transport_id>
          </userTransports>
          <useBuiltinTransports>false</useBuiltinTransports>
        </rtps>
      </participant>
    </profile>
  </profiles>
</dds>
```

### 网络调优

```bash
# 增加网络缓冲区
sudo sysctl -w net.core.rmem_max=134217728
sudo sysctl -w net.core.wmem_max=134217728

# 调整MTU
sudo ip link set dev eth0 mtu 9000  # 开启巨帧
```

---

## 应急处理

### 完全通信中断

**症状**: 所有topic无数据，无法控制机器人

**步骤**:
1. **确保机器人安全姿态** (如还有低层级控制)
2. **检查网络硬件**
   - 网线连接
   - 交换机/路由器状态
3. **重启网络服务**
   ```bash
   sudo systemctl restart NetworkManager
   ros2 daemon restart
   ```
4. **重启控制板** (最后手段)
5. **如仍无效**: 使用急停按钮，人工介入

---

## 监控指标

建议持续监控的通信指标:

| 指标 | 正常范围 | 警告阈值 | 严重阈值 |
|-----|---------|---------|---------|
| 话题延迟 | < 20ms | 50ms | 100ms |
| 丢包率 | < 0.1% | 1% | 5% |
| 心跳间隔 | 10ms | 30ms | 100ms |
| 带宽占用 | < 50% | 70% | 90% |

---

## 相关案例

### CASE-2024-006: 高延迟导致控制滞后
- **现象**: 关节响应慢，走路不协调
- **诊断**: 网络延迟 > 100ms，发现是WiFi干扰
- **解决**: 改用有线连接，延迟降至5ms

### CASE-2024-017: DDS发现失败
- **现象**: 节点间无法通信，但网络连通
- **诊断**: 多网卡配置导致DDS使用错误接口
- **解决**: 配置 ROS_LOCALHOST_ONLY=0 并指定网卡

### CASE-2024-025: 交换机环路
- **现象**: 网络时断时续，广播风暴
- **诊断**: 网络拓扑有环路
- **解决**: 移除冗余连接，启用STP

---

## 参考资源

- ROS2 DDS 配置指南
- Fast DDS 文档
- 宇树SDK2网络配置说明

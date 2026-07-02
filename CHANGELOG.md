# Changelog

## v2.2.0 — 开源整备版 (2026-07)

面向公开发布的整备:正确性修复、内核边界清理、对外文档与 CI 门禁。

### 修复

- `verify_all.py` 去除硬编码 `D:\manastone-diag` 路径,任意干净 clone 可运行,
  失败时退出码 1(此前在非原作者机器上 25 项全挂)
- 关键词匹配改为忽略大小写(此前大写模式如 `OC` 永远匹配不到小写化文本);
  `symptoms_index` 补全中文症状词与 `JOINT_DEFAULT`/摔倒类关键词,
  主打的摔倒诊断场景此前完全匹配不到
- `FaultLibrary` 默认知识库路径不再探测外部 roboonto 仓库布局

### 内核边界(开两端、闭内核)

- 删除 `connect-robot` 技能(依赖 runtime 私有 CLI,超出公开接口面;
  开源版只允许依赖 ledger 读 API)
- `capability_boundary.yaml` 改写为仅描述外部可观察行为,移除内核源码
  行号与私仓 issue 引用
- 剔除含真实整机 SN 的诊断报告及内部开发日志/交接文档;
  示例统一使用 `X2EXAMPLE00001`

### 新增

- 许可证改为 **Apache-2.0** 开源(替代此前的 source-available 非商用许可)
- 英文 README / `docs/QUICKSTART.md` / `docs/SPEC.md`;中文文档移入 `docs/zh/`
- `examples/sample-incident/` 合成示例事故日志,五分钟可复现完整诊断链
- `SOURCES.md` 数据溯源清单、`pyproject.toml`
- CI(GitHub Actions):Linux/Windows × Python 3.10/3.12 全功能验证 +
  知识库一致性门禁 + 内核边界泄漏扫描,三道硬门禁

### 更正(旧版文档主张)

- 故障规则实际为 **11 条**(此前文档写 14 条)
- 经验库性能改为实测值:5000 条经验进程内检索约 15ms、CLI 冷启动 <100ms
  (此前"支持 100000+ 条经验,<20ms 检索"无运行数据支撑,不再主张)

---

## v1.1 — pi-agent 增强版 (2026-06)

基于 v1.0 的全面增强，保持 pi-agent 兼容。

---

### 新增：诊断流程编排器

`tools/diagnostic_orchestrator.py` — 三轮审查法状态机。

- 状态机管理三轮流程（round/validate/gate check）
- 检查清单自动生成
- 中间产物验证 + checkpoint 持久化
- 支持中断恢复

### 新增：诊断归档与可视化面板

`tools/session_archiver.py` — 结构化归档 + HTML 面板 + 验证闭环。

| 命令 | 功能 |
|------|------|
| `archive` | 归档诊断结论到 `data/archive/` |
| `export-html` | 生成对话 HTML 到 `data/records/`（含验证按钮） |
| `dashboard` | 生成归档面板 HTML（`data/archive/dashboard.html`） |
| `pending` | 列出待验证诊断 |
| `verify` | 提交实地验证（correct / partial / wrong） |
| `extract-skill` | 从案例生成技能草稿 |

面板入口：Linux 运行 `./manage.sh`，Windows 双击 `manage.bat`。

验证按钮直接复制命令，回到对话框粘贴即可触发经验修正。

### 新增：诊断经验库

`tools/experience_manager.py` — 经验沉淀与检索。

| 命令 | 功能 |
|------|------|
| `add` | 沉淀诊断经验 |
| `verify` | 验证后自动修正规则权重 |
| `search` | 中文相似度检索历史经验 |
| `stats` | 规则实战准确率统计 |
| `import` | 一键导入其他用户全部数据 |
| `merge` | 合并经验库分片 |

存储：分片（≤5MB/片）+ 索引 + WAL 写保护。支持 100000+ 条经验，<20ms 检索。

### 新增：统一配置模块

`tools/config.py` — 数据目录优先级管理。

优先级：环境变量 `MANASTONE_DATA_DIR` → 项目 `data/` → 用户目录。

### 新增：MCAP 关节数据解析

`tools/mcap_joint_parser.py` — 从 MCAP bag 直接解析关节位置/速度/力矩。

### 新增：数据导入工具

`tools/import_tool.py` — GUI 跨用户数据导入。导入内容：经验库 + 归档记录 + 对话记录。重复自动跳过。

### 新增：全功能验证

`tools/verify_all.py` — 一键端到端验证所有诊断工具。

### 新增：知识库规则外部化

| 文件 | 内容 |
|------|------|
| `knowledge/event_patterns.yaml` | 10 种事件匹配规则（YAML 可编辑，无需改代码） |
| `knowledge/causal_rules.yaml` | 6 条时序因果规则（如 JOINT_DEFAULT → 1s内摔倒） |

### 新增：诊断技能

| 技能 | 说明 |
|------|------|
| `auto-l2-x-joint-default.md` | L2 安全门触发 JOINT_DEFAULT |
| `auto-slave-1-can5-nodeid-5-sdo-motor-protocol.md` | CAN5 SDO 电机协议故障 |

### 修改：核心工具增强

| 文件 | 变更 |
|------|------|
| `tools/log_ingestor.py` | 修复 stats 序列化；MCAP 双通道解析（CDR + 二进制扫描） |
| `tools/fault_library.py` | 新增 `match_timeline()` 时序因果匹配 |
| `tools/atop_reader.py` | 优化解析逻辑 |
| `requirements.txt` | 新增 `mcap` `mcap-ros2-support` 依赖 |
| `AGENTS.md` | 新增完整工具箱文档、三轮流程、验证闭环指导 |
| `.pi/AGENTS.md` | 更新工具列表、补充 export-html + 验证流程 |
| `.gitignore` | 新增 `robot-logs/` `data/` 排除规则 |
| `README.md` | 更新项目说明 |

---

### 数据存储位置

| 目录 | 内容 |
|------|------|
| `data/archive/` | 归档记录（JSON）+ 索引 + 面板 HTML |
| `data/records/` | 诊断对话记录（`<SN>_full.html`） |
| `data/experience_shards/` | 经验库分片 |
| `data/sessions/` | 编排器状态 |

所有数据存项目内 `data/`，不依赖系统盘。可通过 `MANASTONE_DATA_DIR` 环境变量指向共享目录实现多用户协作。

### 文件变更统计

```
v1.0 → v1.1:
  Python 工具:   4 个 → 10 个
  知识库 YAML:   6 个 →  8 个 (+2)
  领域技能:     15 个 → 17 个 (+2)
  诊断规则:     14 条 (不变)
  因果规则:      0 条 →  6 条 (新增)
  事件模式:      0 (硬编码) → 10 条 (外部化)
```

---

### 从 v1.0 升级

```bash
# 1. 复制新文件到 v1.0 目录
#    对照上方"新增文件"列表复制

# 2. 安装新依赖
pip install -r requirements.txt

# 3. 启动
manastone-diag
```

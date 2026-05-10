# AlphaCore 决策中枢 · 功能增强预案

> **版本**: V1.1 · 日期: 2026-05-10 (V22.1 同步更新)
> **当前系统版本**: V22.1
> **预案性质**: 机构级量化终端的辅助决策功能演进路线图

---

## 目录

1. [当前系统能力评估](#1-当前系统能力评估)
2. [行业对标分析](#2-行业对标分析)
3. [差距分析矩阵](#3-差距分析矩阵)
4. [增强方案详述](#4-增强方案详述)
5. [优先级排序与实施路线](#5-优先级排序与实施路线)
6. [技术可行性与风险评估](#6-技术可行性与风险评估)
7. [资源估算](#7-资源估算)

---

## 1. 当前系统能力评估

### 1.1 已完成的核心能力 (V21.2)

AlphaCore 已构建起一套相当完整的量化决策基础设施。以下为已实现模块的客观评估：

| 模块 | 成熟度 | 评价 |
|:-----|:------|:-----|
| **AIAE 宏观仓位引擎** | ⭐⭐⭐⭐⭐ | 行业领先。Sigmoid 归一化、五档分界线、三维权重都是机构级设计。美/港/日/中四市场覆盖。 |
| **ERP 股权风险溢价引擎** | ⭐⭐⭐⭐ | 自适应权重 O10 + 多时间框架 O11 成熟。PE/利率/历史分位数多维度。 |
| **联合置信度 JCS** | ⭐⭐⭐⭐ | V17.0 加法模型替代旧版乘法是正确的。AIAE(35%)+ERP(25%)+VIX(20%)+MR(20%) 权重分配合理。 |
| **矛盾检测矩阵** | ⭐⭐⭐⭐ | 7 条规则覆盖 AIAE-ERP, VIX-AIAE, VIX-ERP, MR-CRASH 等关键冲突对，含严重度和行动建议。 |
| **全球市场温度** | ⭐⭐⭐ | 跨市场 AIAE 对比 + 推荐条。但缺乏更细粒度的跨市场风险传导分析。 |
| **波段守卫 Swing Guard** | ⭐⭐⭐⭐ | 7 大 ETF 的跟踪止盈机制，三色信号，生产级实现。 |
| **风控护栏** | ⭐⭐⭐ | 集中度 + AIAE 热度 + VIX 恐慌 + 策略重叠度 四个 KPI。尾部风险评分有加权子项。 |
| **情景模拟器** | ⭐⭐⭐ | 6 个核心情景，纯数学推演零 API 调用。但缺乏有向冲击传播。 |
| **持仓相关性热力图** | ⭐⭐⭐ | Pearson 120 日 + MCTR 边际风险贡献。已覆盖核心分析需求。 |
| **三通道预警** | ⭐⭐⭐⭐ | 浏览器 Toast + Server酱微信 + QQ SMTP 邮件，含 cooldown 机制。 |
| **投委会日报** | ⭐⭐⭐⭐ | 自动生成 Markdown，含复制/下载功能，每日 16:35 自动触发。 |
| **决策时间线 + 复盘日历** | ⭐⭐⭐ | 近 30 天 JCS 趋势 + 月度热力图，含信号准确率追踪 (T+5)。 |
| **绩效分析** | ⭐⭐⭐ | 7 基准 (沪深300/科创50/创业板50/标普500/纳指100/日经225/恒生科技)，月度热力图/回撤/滚动Sharpe。 |
| **个股深研** | ⭐⭐⭐ | 7 只标的 (中芯/紫金/比亚迪/东财/工业富联/沪电/深南) 独立审计页面。 |
| **数据新鲜度状态栏** | ⭐⭐⭐ | 按引擎显示缓存年龄 + 日期一致性检查，V21.2 新增。 |

### 1.2 当前架构优势

- **引擎驱动 + 缓存优先**: 决策中枢 100% 从缓存读取，不直接调用引擎，保证前端响应速度
- **SWR 三级缓存**: Stale-While-Revalidate (5min fresh / 1h stale / hard miss 同步刷新)
- **模块化前端**: `_infra.js → 6 模块 → 主入口` 的清晰依赖链
- **异步降级**: 8 秒超时 + 重试按钮的优雅降级模式
- **V20.0 缓存层**: risk-matrix 的 Tab1/Tab3 复用，消灭重复请求

### 1.3 当前架构局限性

| 局限 | 影响 |
|:-----|:-----|
| 决策中枢是"被动仪表板"，不是"主动工作流" | 用户必须打开浏览器才能获取信息 |
| 纯分析系统，无执行链路 | 发现信号后需手动下单，存在操作延迟和情绪干扰 |
| 6 个预设情景，无动态事件驱动 | 无法响应真实市场事件 (突发政策、地缘冲突) |
| 信号准确率追踪仅 T+5 | 无法区分"信号发出后被市场验证"和"信号发出后偶然吻合" |
| 无策略版本管理与回滚 | 参数调整后无法快速对比新旧版本表现 |
| AIAE 仓位建议无动态对冲建议 | 只给仓位百分比，不给具体减仓路径 |
| 无自动化合规检查 | 板块集中度仅做展示，不做硬阻断 |
| 仅中/美/港/日四市场 | 缺少新兴市场 (印度/越南)、大宗商品、债券的独立模块 |

---

## 2. 行业对标分析

### 2.1 对标基准

以下选取三个层级进行对标：

| 层级 | 代表产品 | 对标维度 |
|:-----|:--------|:--------|
| **机构级 (Tier 1)** | Bloomberg AIM + PORT Enterprise + MARS | 全链路覆盖、合规、风控 |
| **量化对冲基金 (Tier 2)** | 自研系统 (Marshall Wace + MAC3, Two Sigma, Citadel 等) | 策略回测 CI/CD、多因子风控 |
| **零售增强 (Tier 3)** | TradingView, Koyfin, 同花顺 iFinD | 可视化、社区、易用性 |

### 2.2 关键差距识别

参照 Bloomberg 2025 年架构 (EMSX + AIM + PORT + MARS + MAC3)，AlphaCore 对比如下：

| 能力维度 | Bloomberg 2025 | AlphaCore V21.2 | 差距等级 |
|:---------|:-------------|:---------------|:--------|
| **宏观配置择时** | PORT OP 多资产优化 | AIAE 引擎 (四市场覆盖) | 🟢 接近 |
| **估值分析** | 多资产风险因子模型 (MAC3, 3000+因子) | ERP 引擎 + O10/O11 | 🟡 中等 |
| **组合风险分解** | MCTR/Risk Contribution + 压力测试 | MCTR + 相关性热力图 | 🟡 中等 |
| **情景分析** | MARS: 历史+自定义+相关性预测+气候 | 6 大预设情景 + 纯数学推演 | 🔴 较大 |
| **交易执行** | EMSX + AIM OMS + 策略优化器 | 无 | 🔴 巨大 |
| **合规引擎** | 投资+监管+内部约束的事前/事后检查 | 仅警戒线展示，无硬阻断 | 🔴 巨大 |
| **AI 驱动分析** | AI Portfolio Commentary (2025.9) | 无 AI 生成内容 | 🔴 较大 |
| **策略回测 CI/CD** | BQuant + 标准化回测流水线 | 独立的 backtest_engine，无自动化管道 | 🔴 较大 |
| **工作流集成** | Slack/Teams/Email 推送 + PM<GO> 工作台 | 仅 Server酱/QQ SMTP 预警 | 🟡 中等 |
| **气候风险** | MARS Climate (2025.2) | 无 | 🟡 中等 |
| **数据治理** | PIT 双时间戳 + 统一证券主数据 | 无显式 PIT 模型 | 🟡 中等 |

### 2.3 2025-2026 行业趋势要点

1. **多智能体架构 (Multi-Agent)**: 彭博未公开，但头部量化基金 (Two Sigma, Marshall Wace) 和学术界 (2025-2026 论文) 已大规模采用。专业化 Agent 通过类型化合约协作。
2. **混合 AI (Hybrid)**: 确定性计算 (RSI/ERP) + ML 预测 + LLM 叙事生成的三层架构成为共识。
3. **CI/CD for Quant**: Git push → 标准化回测 → 影子交易 → 灰度上线 → 漂移监控的全自动化管道。
4. **嵌入式风控**: 不再是独立模块，而是织入每个决策环节。
5. **工作流优先 UX**: "不做另一个仪表板"，而是把智能推送到 Slack/微信/Teams。

---

## 3. 差距分析矩阵

### 3.1 功能差距总览

```
                        现有能力          行业标杆         差距
                        ────────          ────────        ────
宏观配置择时            ████████░░        ██████████      小
估值分析                ████████░░        ██████████      中
组合风险分解            ███████░░░        ██████████      中
情景模拟与压力测试      ████░░░░░░        ██████████      大
交易执行链路            ░░░░░░░░░░        ██████████      巨大
合规检查引擎            ██░░░░░░░░        ██████████      巨大
AI/LLM 集成             ░░░░░░░░░░        ██████░░░░      大
策略 CI/CD              ██░░░░░░░░        ████████░░      大
多资产覆盖 (商品/债)    ███░░░░░░░        █████████░      中
工作流推送              ███░░░░░░░        ████████░░      中
数据治理 (PIT)          ░░░░░░░░░░        ██████████      中
```

### 3.2 按用户旅程的缺失环节

以一个完整的投资决策闭环来看：

```
研究 ──→ 信号 ──→ 决策 ──→ 执行 ──→ 监控 ──→ 复盘
 ✅       ✅       ⚠️       ❌       ⚠️       ⚠️
```

- **研究 (✅)**: AIAE/ERP/VIX/MR 四引擎均已建成
- **信号 (✅)**: JCS + 矛盾矩阵 + 三通道预警完备
- **决策 (⚠️)**: 有执行建议但无仓位调整的具体路径、无对冲方案、无分批执行计划
- **执行 (❌)**: 完全缺失。无券商 API 对接、无订单管理、无算法交易
- **监控 (⚠️)**: 有尾部风险 + 集中度，但无实时偏离监控、无硬止损触发
- **复盘 (⚠️)**: 有 T+5 准确率 + 决策日志，但无系统性策略归因、无参数漂移检测

---

## 4. 增强方案详述

以下方案按"投入产出比"和"与现有架构的集成难度"排序，分为三个梯队。

---

### 4.1 第一梯队：快速见效 (1-4 周, 低风险)

这些方案在现有架构上做增量，不改动核心数据流。

#### 4.1.1 动态仓位调整路径生成器 (Position Path Planner) — ✅ 已交付 V22.0

**现状**: 决策面板给出目标仓位百分比 (如"建议仓位 35%")，但没有告诉用户如何从当前仓位安全过渡到目标仓位。

**方案**:
- 在后端 `decision_engine.py` 新增 `generate_position_path()` 函数
- 输入: 当前持仓 (从 portfolio_store.json 读取)、JCS 置信度、AIAE regime、单票集中度
- 输出: 分 3 步的仓位调整路径 (T / T+2 / T+5)，每步指定具体标的的增/减比例
- 前端: 在 `action-inline` 面板下方新增"执行路径"折叠卡片，展示分步操作表

**伪代码**:
```python
def generate_position_path(current_positions, target_cap, jcs_level, aiae_regime):
    steps = []
    current_total = sum(p["weight"] for p in current_positions)
    gap = target_cap - current_total
    step_size = gap / 3  # 分三批
    
    for step_i in range(3):
        step = {"day": f"T+{step_i * 2}", "actions": []}
        for pos in current_positions:
            # 按集中度风险 + 单票仓位超配程度排序
            adjustment = compute_adjustment(pos, step_size, aiae_regime)
            step["actions"].append(adjustment)
        steps.append(step)
    return steps
```

**投入**: 后端 1 天 + 前端 0.5 天
**价值**: 高 — 弥合"决策到执行"的关键断层

#### 4.1.2 策略参数版本对比器 (Strategy A/B Comparator) — ✅ 已交付 V22.1

**现状**: 参数中心 (`aiae_params.py`, `erp_params.py`) 有参数定义，但无版本管理。调整参数后无法快速对比新旧表现。

**方案**:
- 在 `config/` 下新建 `param_versions/` 目录，存储带时间戳的参数快照
- 新增 `GET /api/v1/decision/param-compare` 端点
- 前端: 在 `backtest.html` 新增"参数版本对比" Tab，双列展示新旧版本的策略信号对比
- 基于现有 `backtest_engine.py` 并行跑两组参数，生成对比报告

**核心数据结构**:
```json
{
  "version_id": "v20260506_aiae_v3.1",
  "timestamp": "2026-05-06T10:00:00",
  "params": {
    "aiae_weights": {"total_mv": 0.55, "fund_position": 0.20, "margin_heat": 0.25},
    "regime_thresholds": [12.5, 17, 23, 30],
    "position_matrix": [[90, 95], [70, 85], [50, 65], [25, 40], [0, 15]]
  },
  "backtest_metrics": {"sharpe": 1.25, "max_drawdown": -12.3, "win_rate": 68.5}
}
```

**投入**: 后端 1.5 天 + 前端 1 天
**价值**: 高 — 支持策略迭代的科学决策

#### 4.1.3 信号有效期的时效标记 (Signal Freshness Decay) — ✅ 已交付 V22.0

**现状**: JCS 值是一个瞬时快照，但不同引擎的数据新鲜度不同 (AIAE 月频、ERP 日频、VIX 日频、MR 日频)。用户无法直观判断信号"有多新鲜"。

**方案**:
- 在 JCS 环形图下方新增"信号半衰期指示器"，四个引擎各一个衰减条
- 后端在 hub 响应中新增 `signal_decay` 字段:
  ```json
  {
    "signal_decay": {
      "aiae": {"age_days": 12, "half_life_days": 15, "reliability": 0.62},
      "erp":  {"age_days": 1,  "half_life_days": 3,  "reliability": 0.95},
      "vix":  {"age_days": 0,  "half_life_days": 1,  "reliability": 1.0},
      "mr":   {"age_days": 0,  "half_life_days": 2,  "reliability": 1.0}
    }
  }
  ```
- `reliability = 0.5^(age_days / half_life_days)` — 经典的放射性衰变模型

**投入**: 后端 0.5 天 + 前端 0.5 天
**价值**: 中高 — 提升 JCS 的可解释性和信任度

#### 4.1.4 跨市场风险传染热度图 (Contagion Heatmap) — ✅ 已交付 V22.0

**现状**: 全球市场温度仪表板展示了各市场的独立 AIAE 读数，但没有展示市场间的风险传导关系。

**方案**:
- 新增小型 4×4 矩阵 (中/美/港/日)，每格展示 120 日收益率相关性
- 颜色编码: 蓝色 (负相关/对冲) → 白色 (独立) → 红色 (高度联动)
- 在 `global_analytics.js` 中新增 `renderContagionMatrix()` 函数
- 数据源: 复用现有 daily_prices parquet 缓存计算日收益率相关性

**投入**: 后端 0.5 天 + 前端 0.5 天
**价值**: 中 — 全球配置视角下的风险分散决策依据

---

### 4.2 第二梯队：能力跃升 (2-8 周, 中风险)

这些方案涉及新模块开发或现有模块的较大改版。

#### 4.2.1 有向冲击传播模拟器 (Directed Shock Simulator) — ✅ 已交付 V22.0

**现状**: 6 个预设情景，每个情景直接修改引擎读数后重新计算 JCS。这是一种"单点静态冲击"思路，无法表达冲击的传导。

**行业对标**: Bloomberg MARS 的压力测试覆盖历史情景、自定义情景、相关性预测压力测试。

**方案**:
- 实现一个基于 NetworkX 的有向冲击传播图
- 节点: VIX, ERP, AIAE, MR, 各市场指数, 利率, 汇率
- 边: 冲击传导系数 (基于历史数据回归估计)
- 用户选择一个"冲击源"(如 "美联储加息 50bp")，系统沿图传播:
  ```
  利率↑ ──[0.7]──→ ERP↓ ──[0.5]──→ AIAE↑
    │                │
    └──[0.8]──→ VIX↑ ──[0.6]──→ MR→BEAR
  ```
- 后端实现:
  ```python
  import networkx as nx
  
  class ShockPropagationGraph:
      def __init__(self):
          self.G = nx.DiGraph()
          # 定义节点和传导边
          self._init_edges()
      
      def propagate(self, source: str, shock_magnitude: float, steps: int = 3):
          """BFS 传播冲击，每步衰减"""
          results = {source: shock_magnitude}
          for step in range(steps):
              new_results = {}
              for node, mag in results.items():
                  for _, target, data in self.G.out_edges(node, data=True):
                      transmitted = mag * data["coefficient"] * (data.get("decay", 0.7) ** step)
                      new_results[target] = new_results.get(target, 0) + transmitted
              results.update(new_results)
          return results
  ```
- 前端: 在情景模拟器卡片下方新增"冲击传播路径图"(ECharts Sankey 图或力导向图)

**投入**: 后端 3 天 + 前端 2 天 + 历史系数校准 2 天
**价值**: 高 — 从"单点思维"升级到"系统思维"

#### 4.2.2 动态事件驱动信号引擎 (Event-Driven Signal Override) — ✅ 已交付 V22.2

**现状**: 情景模拟器是手动触发的。真实市场的重大事件 (政策变动、地缘冲突、突发数据) 不会自动触发重新评估。

**方案**:
- 新增 `EventMonitor` 后台任务，轮询以下数据源的事件:
  - 财经日历 API (预知事件: FOMC, CPI, GDP 等)
  - VIX 跳变检测 (日内 >20% 跳变)
  - 汇率跳变检测 (CNY/USD >1% 日内)
  - 新闻高频词检测 (基于标题关键词匹配)
- 当检测到事件时:
  1. 自动匹配最接近的情景模板
  2. 执行冲击传播模拟
  3. 如果 JCS 跨越阈值边界 (如从 high→medium 或 medium→low)，触发预警
- 新增 APScheduler 任务: `event_monitor` (每 5 分钟)

```python
EVENT_TRIGGERS = {
    "fomc_decision": {
        "keywords": ["FOMC", "联邦基金利率", "加息", "降息"],
        "scenario_template": "rate_change",
        "severity": "high",
    },
    "vix_spike": {
        "condition": lambda snap: snap.get("vix_val", 20) > 30,
        "scenario_template": "vix_spike_35",
        "severity": "extreme",
    },
    "cny_devaluation": {
        "condition": lambda snap: abs(snap.get("cny_change_pct", 0)) > 1.0,
        "scenario_template": "currency_shock",
        "severity": "high",
    },
}
```

**投入**: 后端 4 天 + 前端 1 天 (事件卡片)
**价值**: 高 — 从"被动仪表板"向"主动工作流"的关键一步

#### 4.2.3 交易执行研究接口 (Execution Research Bridge) — ✅ 已交付 (OMS Slippage Attribution)

**现状**: 决策中枢输出仓位建议，但没有连接到任何交易执行系统。这是整个闭环中最大的缺口。

**说明**: 本方案不涉及真实交易执行 (涉及合规和券商对接，不是 2-8 周能完成的)，而是做"执行研究"——模拟执行效果、计算交易成本、生成执行计划。

**方案**:
- 新增 `ExecutionResearch` 模块:
  - **TWAP/VWAP 模拟器**: 基于历史 tick 数据估计执行滑点
  - **冲击成本估算**: Almgren-Chriss 模型的简化版
    ```
    冲击成本 = σ × sqrt(Q / V) × η
    其中 Q=订单规模, V=日均成交量, σ=波动率, η=市场参与率
    ```
  - **最优执行计划生成**: 给定目标调仓规模，输出分时执行建议
- 新增页面: `execution.html`，挂入导航"策略实验室"
- 前端展示: 执行成本分解饼图 + 最优执行时间线

**投入**: 后端 5 天 + 前端 2 天
**价值**: 中高 — 量化决策的最后一步，虽不真执行但能评估执行可行性

#### 4.2.4 智能日报升级：AI 驱动的叙事生成 — ✅ 已交付 V22.2

**现状**: 投委会日报是模板化的数据填充，无分析叙事。

**行业对标**: Bloomberg PORT Enterprise 2025.9 推出的 AI Portfolio Commentary。

**方案**:
- 日报生成器在当前模板基础上增加 LLM 生成的"叙事分析"段落
- 输入: JCS 数值 + 矛盾矩阵 + AIAE 趋势 + VIX 状态 + 持仓变动
- 输出: 2-3 段自然语言分析，包含:
  - 当前市场状态一句话总结
  - 矛盾信号的解读和权重建议
  - 未来 1-2 周的关键关注点
- 技术选型: 使用 LLM API (如 Claude API) 或本地部署小模型
- 该模块需可独立关闭 (配置开关)，避免依赖外部 API

```python
def generate_ai_commentary(hub_data: dict) -> str:
    """生成 AI 驱动的日报叙事 (仅在配置启用时)"""
    if not config.ENABLE_AI_COMMENTARY:
        return ""
    
    prompt = f"""
    你是 AlphaCore 量化系统的投资分析师。请根据以下数据生成一段专业简报:
    
    - JCS: {hub_data['jcs']['score']} ({hub_data['jcs']['level']})
    - AIAE Regime: R{hub_data['snapshot']['aiae_regime']} 
    - ERP Score: {hub_data['snapshot']['erp_score']}
    - VIX: {hub_data['snapshot']['vix_val']}
    - 矛盾信号: {hub_data['conflicts']['matrix_summary']}
    
    要求: 不超过 200 字, 专业但易懂, 包含一个明确的操作倾向。
    """
    return call_llm(prompt)
```

**投入**: 后端 2 天 + 前端 0.5 天 (日报 modal 新增 AI 标签段落)
**价值**: 中高 — 提升日报的可读性和决策参考价值

---

### 4.3 第三梯队：架构演进 (8-16 周, 高风险高回报)

这些方案涉及系统架构层面的改动，需要更长的规划和验证周期。

#### 4.3.1 多智能体决策架构 (Multi-Agent Decision Framework)

**现状**: `decision_engine.py` 是单一 Python 模块，所有逻辑集中在一个文件。

**行业趋势**: 2025-2026 年量化投资领域最重要的架构范式。

**方案**:
- 将当前的 `decision_engine.py` 重构为 Agent 架构:
  ```
  Orchestrator (决策中枢已有)
      ├── MacroAgent (AIAE 引擎)  → 输出: RegimeAssessment
      ├── ValuationAgent (ERP 引擎) → 输出: ValuationReport  
      ├── SentimentAgent (VIX + 新增情绪) → 输出: SentimentSnapshot
      ├── TechnicalAgent (MR 引擎 + 波段守卫) → 输出: TechnicalView
      ├── RiskAgent (风控护栏 + 尾部风险) → 输出: RiskAssessment
      └── SynthesisAgent (JCS + 矛盾检测 + 执行建议) → 输出: DecisionBrief
  ```
- 每个 Agent 通过 Pydantic v2 模型进行通信:
  ```python
  from pydantic import BaseModel
  
  class RegimeAssessment(BaseModel):
      regime: int  # 1-5
      v1: float
      confidence: float  # 数据新鲜度衰减后的置信度
      warnings: list[str]
      suggested_cap: tuple[int, int]  # (min, max)
  
  class DecisionBrief(BaseModel):
      jcs: float
      action: str  # "加仓" | "减仓" | "持有" | "观望"
      reasoning: str
      risk_flags: list[str]
      position_path: list[dict]
  ```
- 前端: 在决策概览页新增"Agent 活动日志"折叠区，展示各 Agent 的判断和依据
- 注意: 此重构应在保持 API 兼容性的前提下渐进式进行

**投入**: 后端 15 天 + 前端 3 天 + 测试 5 天
**价值**: 极高 — 架构层面的代际升级，为未来 AI Agent 集成铺路

#### 4.3.2 预交易合规检查引擎 (Pre-Trade Compliance Engine) — ✅ 已交付 V22.0 (超前完成)

**现状**: 风控护栏是"展示层"，没有硬阻断能力。

**行业对标**: Bloomberg AIM 的 Compliance 模块 (投资+监管+内部约束)。

**方案**:
- 新增 `engines/compliance_engine.py`:
  ```python
  class ComplianceRule:
      name: str
      check_fn: Callable  # 返回 (passed: bool, reason: str)
      severity: str  # "hard_block" | "soft_warn" | "info"
  
  RULES = [
      ComplianceRule("single_stock_cap", check_single_stock_cap, "hard_block"),
      ComplianceRule("sector_concentration", check_sector_concentration, "soft_warn"),
      ComplianceRule("aiae_overheat_restriction", check_aiae_overheat, "hard_block"),
      ComplianceRule("jcs_minimum_threshold", check_jcs_threshold, "hard_block"),
      ComplianceRule("vix_emergency_brake", check_vix_emergency, "hard_block"),
      ComplianceRule("wash_sale_30day", check_wash_sale, "info"),
  ]
  ```
- 规则覆盖:
  - **单票上限 20%** (硬阻断)
  - **单板块上限 40%** (软警告)
  - **AIAE ≥ R4 时禁止新建仓** (硬阻断)
  - **JCS < 40 时禁止加仓** (硬阻断)
  - **VIX > 35 时全组合降至 30% 以下** (硬阻断)
- 前端: 在 `action-inline` 面板中新增合规状态徽章 (🟢 审查通过 / 🔴 被阻断)
- 被阻断的操作在 UI 中灰显，并附阻断原因

**投入**: 后端 5 天 + 前端 2 天 + 测试 3 天
**价值**: 极高 — 从"展示风控"升级到"执行风控"

#### 4.3.3 策略 CI/CD 管道 (Strategy CI/CD Pipeline)

**现状**: 独立的回测引擎 (`backtest_engine.py`, `erp_backtest_optimizer.py`)，通过 Python 脚本手动触发。

**行业对标**: 量化对冲基金的 git push → 回测 → 影子交易 → 灰度上线管道。

**方案**:
- 新增 `services/strategy_pipeline.py`:
  ```
  Git Push (参数变更)
    → Trigger Detection (config/param_versions/ 变更)
      → Automated Backtest (2021-2025 五年历史)
        → Metrics Computation (Sharpe, MaxDD, WinRate, Calmar)
          → Quality Gate (Sharpe > 1.0, MaxDD > -15%, WinRate > 55%)
            → [PASS] → Shadow Trading (7 天实时信号对比)
              → Shadow Report → 人工审批
            → [FAIL] → 阻止合并 + 通知开发者
  ```
- 新增 API 端点:
  - `POST /api/v1/strategy/ci/trigger` — 手动触发管道
  - `GET /api/v1/strategy/ci/status/{run_id}` — 查询管道状态
- 新增页面: `ci.html` — CI 管道仪表板，显示最近运行和结果

**投入**: 后端 10 天 + 前端 3 天 + 测试 5 天
**价值**: 高 — 策略工程化的标志性能力

#### 4.3.4 策略漂移监控 (Strategy Drift Monitor)

**现状**: 信号准确率追踪是 T+5 的简单方向统计，无法识别策略是否在持续退化。

**行业对标**: MLOps 的模型漂移监控 (性能漂移 + 数据分布漂移)。

**方案**:
- 新增 `engines/drift_monitor.py`:
  - **信号衰减率**: 最近 20 次信号的准确率 vs 历史基准 (预警: 连续 5 次低于基准)
  - **参数敏感度**: 关键参数 ±5% 扰动对 Sharpe 的影响 (参数稳定性检测)
  - **市场环境偏移**: 当前市场状态 (AIAE regime + VIX 区间) 的训练集覆盖度
  - **换手率异常**: 策略信号换手率偏离历史均值 >2σ 时预警
- 在 APScheduler 中新增周度任务: `drift_monitor` (每周六 09:00)
- 前端: 在策略中心页面新增"策略健康度"卡片

```python
class DriftMonitor:
    def check_performance_drift(self, recent_accuracy: list[float]) -> dict:
        baseline = self._load_baseline_accuracy()
        recent_avg = sum(recent_accuracy[-20:]) / min(len(recent_accuracy), 20)
        drift = baseline - recent_avg
        return {
            "drift_detected": drift > 0.05,
            "drift_magnitude": drift,
            "severity": "warning" if drift > 0.05 else ("critical" if drift > 0.10 else "ok"),
            "recommendation": "建议检查近期市场环境是否发生结构性变化" if drift > 0.05 else ""
        }
```

**投入**: 后端 4 天 + 前端 1 天
**价值**: 高 — 预防策略无声失效的关键机制

---

### 4.4 存量优化 (可穿插进行)

以下是基于代码审查发现的现有模块改进点：

| 编号 | 模块 | 问题 | 优化建议 | 工作量 |
|:----|:-----|:-----|:--------|:------|
| O1 | `decision_engine.py` | JCS 矛盾惩罚中 `all_neutral` 规则会被 `compute_conflict_matrix` 计入 info 级别，但 `compute_jcs` 已排除 info。逻辑分散在两处易出错 | 将冲突过滤逻辑统一到 `compute_conflict_matrix` 中，加一个 `actionable_only=True` 参数 | 0.5 天 |
| O2 | `hub_core.js` | `renderAIAEHub` 中手动设置 `--regime-color` CSS 变量，内联 hexToRgb。可复用的逻辑散落在 JS 中 | 提取 `_hexToRgb()` 到 `_infra.js` 作为共享工具函数 | 0.3 天 |
| O3 | `risk_alerts.js` | `renderFreshnessBar` 中的 `age_min` 字段可能为负 (当数据日期在未来时) | 后端正则化: `max(0, age_min)` | 0.2 天 |
| O4 | `simulation.js` | `runSimulation` 中 fallback 检查 `typeof AC === 'undefined'`，但未在 DOMContentLoaded 时确保加载顺序 | 在 `_infra.js` 中添加 `AC_READY` 事件，`decision.js` 监听后再调用 | 0.5 天 |
| O5 | 前端全局 | 多个 ECharts 实例通过 `_chartInstances` 管理，但 `global_analytics.js` 中的 `_globalTempCharts` 有独立的 resize handler | 统一到 `_infra.js` 的 `_chartInstances` 集中管理 | 1 天 |
| O6 | `decision_engine.py` | `SCENARIOS` 字典硬编码在发动机中，新增情景需改代码 | 移到 `config/scenarios.json` 配置文件，支持热加载 | 1 天 |
| O7 | `aiae_engine.py` | `_cache` 字典无 TTL，仅靠手动清理。长时间运行可能内存膨胀 | 改用 `cachetools.TTLCache` 或 Redis 统一缓存层 | 1 天 |
| O8 | `erp_signal_enhancer.py` | `multi_timeframe_confirmation` 中 `erp_median` 每次都从 `tail(252)` 计算 | 缓存周级别中位数，减少重复计算 | 0.5 天 |

---

## 5. 优先级排序与实施路线

### 5.1 排序原则

1. **价值密度优先**: 单位工作量产生的决策质量提升
2. **架构友好**: 不改动核心数据流，降低引入 bug 的风险
3. **用户可感知**: 能快速在前端看到效果
4. **独立性**: 不依赖其他未完成的方案

### 5.2 实施路线图

```
Phase 1 (第 1-2 周): 快速见效 ─────────────────────────────
├── O1-O8 存量优化 (穿插进行)
├── 4.1.3 信号有效期时效标记
├── 4.1.1 动态仓位调整路径生成器
└── 4.1.2 策略参数版本对比器

Phase 2 (第 3-6 周): 能力跃升 ─────────────────────────────
├── 4.1.4 跨市场风险传染热度图
├── 4.2.1 有向冲击传播模拟器
├── 4.2.2 动态事件驱动信号引擎
└── 4.2.4 AI 驱动日报叙事生成

Phase 3 (第 7-12 周): 架构演进 ─────────────────────────────
├── 4.2.3 交易执行研究接口
├── 4.3.2 预交易合规检查引擎
└── 4.3.4 策略漂移监控

Phase 4 (第 13-20 周): 代际升级 ───────────────────────────
├── 4.3.1 多智能体决策架构
└── 4.3.3 策略 CI/CD 管道
```

### 5.3 优先级决策矩阵

```
                    高价值
                      │
      4.1.1 路径生成   │   4.3.2 合规引擎
      4.1.2 参数对比   │   4.2.1 冲击传播
      4.1.3 信号时效   │   4.3.1 多智能体
                      │
  ──────────────────────┼──────────────────────
    低投入             │              高投入
                      │
      O1-O8 存量优化   │   4.3.4 漂移监控
      4.1.4 传染热度   │   4.3.3 CI/CD
                      │   4.2.3 执行研究
                      │
                    低价值
```

**第一优先级 (立即启动)**: 4.1.1, 4.1.2, 4.1.3, O1-O8
**第二优先级 (Phase 2)**: 4.2.1, 4.2.2, 4.1.4
**第三优先级 (Phase 3-4)**: 其余

---

## 6. 技术可行性与风险评估

### 6.1 依赖风险

| 方案 | 外部依赖 | 风险 | 缓解措施 |
|:-----|:--------|:-----|:--------|
| 4.2.4 AI 日报 | LLM API (Claude/OpenAI) | API 不可用或成本过高 | 配置开关 + 本地 fallback 模板 |
| 4.2.2 事件驱动 | 财经日历 API + 新闻源 | 数据源不稳定 | 多源冗余 + VIX/汇率可自算 |
| 4.2.3 执行研究 | 历史 tick 数据 | Tushare 可能不提供 tick 级 | 用分钟线近似 + 明确标注精度限制 |
| 4.3.3 CI/CD | Git hooks + CI runner | 服务器资源受限 (2GB 内存) | 回测在非交易时段运行 + 采样优化 |

### 6.2 性能风险

| 方案 | 潜在性能影响 | 缓解措施 |
|:-----|:-----------|:--------|
| 4.2.1 冲击传播 | NetworkX 图遍历 (毫秒级) | 图规模小 (约 20 节点)，性能无忧 |
| 4.2.2 事件监控 | 每 5 分钟轮询多个数据源 | ThreadPoolExecutor 并行 + 缓存去重 |
| 4.3.3 CI/CD | 回测计算密集 (可能数分钟) | 后台任务 + 非阻塞 API |
| 4.3.1 多智能体 | 模块拆分后调用链变长 | Pydantic 序列化开销极小 (<1ms) |

### 6.3 兼容性风险

- **API 兼容**: 所有第一/第二梯队方案均为增量 API 端点，不修改现有端点签名
- **数据库兼容**: 不新增数据库表 (除 4.3.2 合规日志可能需要独立的 audit_log 表)
- **前端兼容**: 现有 CSS 变量体系和模块化 JS 架构可支撑增量开发

---

## 7. 资源估算

### 7.1 总工作量估算

| 梯队 | 方案数 | 后端 (人天) | 前端 (人天) | 测试 (人天) | 小计 |
|:-----|:------|:----------|:----------|:----------|:----|
| 存量优化 | 8 | 2.5 | 2.5 | 0.5 | 5.5 |
| 第一梯队 | 3 | 2.0 | 2.0 | 1.0 | 5.0 |
| 第二梯队 | 4 | 14.0 | 5.5 | 4.0 | 23.5 |
| 第三梯队 | 4 | 34.0 | 9.0 | 13.0 | 56.0 |
| **合计** | **19** | **52.5** | **19.0** | **18.5** | **90.0** |

### 7.2 推荐的 MVP 范围 (4 周交付)

选择以下组合可在 4 周内交付一个有感知价值的增强版本:

1. O1-O8 存量优化 (穿插)
2. 4.1.1 仓位调整路径生成器
3. 4.1.2 参数版本对比器
4. 4.1.3 信号时效标记
5. 4.1.4 跨市场传染热度图

**MVP 工作量**: 约 10 人天

### 7.3 服务器资源增量

当前阿里云轻量服务器配置 (2GB 内存, 单核) 对第一/第二梯队方案足够。第三梯队方案 (特别是 CI/CD 管道) 可能需要升级到 4GB 内存实例，或在非交易时段运行。

---

## 8. 决策建议

### 8.1 立即执行 (本周)

- **O1-O4 存量优化** (2 人天): 零风险，提升代码质量
- **4.1.3 信号时效标记** (1 人天): 最小的投入，直接提升 JCS 可信度

### 8.2 本月目标 (5 月)

- **4.1.1 + 4.1.2 + 4.1.4** (6 人天): 三个快速见效方案，覆盖"决策→执行"断层

### 8.3 季度目标 (Q2 2026)

- **4.2.1 有向冲击传播** (7 人天): 情景分析代际升级
- **4.2.2 事件驱动信号引擎** (5 人天): 从被动到主动

### 8.4 年度目标 (2026 H2)

- **4.3.2 合规引擎 + 4.3.4 漂移监控** (15 人天): 风控闭环
- **4.3.1 多智能体架构** (23 人天): 为 AI 时代做好准备

---

> **预案总结**: AlphaCore V21.2 的决策中枢已经建立起优秀的"分析层"——多引擎信号、矛盾检测、JCS 合成、情景模拟。当前的关键短板是从"分析"到"行动"的断层，以及从"静态仪表板"到"动态工作流"的范式转换。本预案提出的 19 个增强方案覆盖了这条演进路径上的所有关键节点，建议先从 MVP 范围入手 (4 周 / 10 人天)，快速验证价值后再逐步推进架构层面的升级。

---

> **维护备忘**: 本预案对应 2026-05-06 的代码审计结果。后续如架构或行业趋势发生重大变化，请同步更新本文件。

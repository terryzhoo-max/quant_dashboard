# Mean Reversion Parameter Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用冻结样本外证据管理均值回归参数的验证、失效、拒绝和发布，并在当前市场状态的参数不可用时仅阻止新开仓、继续执行止损与退出。

**Architecture:** `config/strategy_runtime.json` 是唯一生产参数源；`services/mr_validation.py` 负责无前视的同口径 incumbent/challenger 比较；流水线只发布通过证据门槛的 challenger 或重新验证的 incumbent；引擎、审计、API 和前端均消费同一份生命周期状态。所有发布沿用带 revision、备份和原子替换的运行时配置机制。

**Tech Stack:** Python 3.11、FastAPI、NumPy、Pandas、pytest、原生浏览器 JavaScript、JSON

---

## 决策不变量

- 参数“新鲜”必须由冻结样本外验证证明，不能通过重写时间戳获得。
- 样本外起点固定为 `2026-03-28`；验证终点取本地行情共同可用的最新交易日，并写入 `data_through`。
- incumbent 与 challenger 必须使用同一标的池、成本、基准、市场状态分类和日期区间。
- challenger 只有同时通过绝对质量门槛和相对回归门槛时才能替换 incumbent。
- incumbent 通过绝对门槛但 challenger 无显著改进时，允许只更新 incumbent 的验证证据，不改参数。
- `stale`、`rejected`、`insufficient_evidence` 都不得触发新买入；已有持仓的止损、RSI 卖出和减仓仍必须运行。
- 生命周期按 `BEAR`、`RANGE`、`BULL` 独立管理；全局 `published_at` 不能替代单状态证据。

## Task 1: 建立生命周期配置契约

**Files:**
- Modify: `services/strategy_params.py`
- Modify: `config/strategy_runtime.json`
- Modify: `tests/test_strategy_runtime.py`

- [ ] **Step 1: 写入生命周期读取行为的失败测试**

在 `tests/test_strategy_runtime.py` 增加测试，覆盖：合法状态、过期的 `validated` 动态降级为 `stale`、非 validated 状态禁止新开仓，以及三个市场状态缺一时报错。

```python
def test_get_mr_lifecycle_marks_expired_validation_stale(monkeypatch):
    cfg = _runtime_config_with_lifecycle(
        "BEAR",
        status="validated",
        next_validate_after="2026-09-26T00:00:00+08:00",
    )
    monkeypatch.setattr(strategy_params, "load_runtime_config", lambda: cfg)

    lifecycle = strategy_params.get_mr_lifecycle(
        "BEAR", as_of=datetime(2026, 10, 13, tzinfo=ZoneInfo("Asia/Shanghai"))
    )

    assert lifecycle["configured_status"] == "validated"
    assert lifecycle["status"] == "stale"
    assert lifecycle["allow_new_entries"] is False
    assert lifecycle["reason"] == "validation_expired"
```

- [ ] **Step 2: 运行定向测试并确认失败原因正确**

Run: `python -m pytest tests/test_strategy_runtime.py -q`

Expected: FAIL，提示 `get_mr_lifecycle` 或生命周期校验尚不存在，而不是导入错误。

- [ ] **Step 3: 实现生命周期验证和有效状态计算**

在 `services/strategy_params.py` 增加：

```python
MR_LIFECYCLE_STATUSES = {
    "validated", "stale", "rejected", "insufficient_evidence"
}

def get_mr_lifecycle(regime: str, *, as_of: datetime | None = None) -> dict:
    config = load_runtime_config()
    raw = dict(config["strategies"]["mr"]["lifecycle"][regime.upper()])
    configured = raw["status"]
    effective = configured
    reason = f"lifecycle_{configured}"
    now = as_of or datetime.now(ZoneInfo("Asia/Shanghai"))
    if configured == "validated" and now > _parse_runtime_datetime(raw["next_validate_after"]):
        effective = "stale"
        reason = "validation_expired"
    raw.update(
        configured_status=configured,
        status=effective,
        allow_new_entries=effective == "validated",
        reason=reason,
    )
    return raw

def get_all_mr_lifecycle(*, as_of: datetime | None = None) -> dict[str, dict]:
    return {regime: get_mr_lifecycle(regime, as_of=as_of) for regime in REGIMES}
```

扩展运行时配置校验，要求三个状态均包含 `status`、`validated_at`、`data_through`、`validation_run_id`、`next_validate_after`，并校验状态枚举及 ISO 日期格式。

- [ ] **Step 4: 迁移现有配置为诚实的 stale 状态**

在 `config/strategy_runtime.json` 的 `strategies.mr` 下新增 `lifecycle`。用已存在的历史验证证据初始化，不伪造新验证：

```json
"lifecycle": {
  "BEAR": {
    "status": "stale",
    "validated_at": "2026-07-28T00:00:00+08:00",
    "data_through": "2024-04-30",
    "validation_run_id": "legacy-mr-20260728",
    "next_validate_after": "2026-09-26T00:00:00+08:00"
  },
  "RANGE": {
    "status": "stale",
    "validated_at": "2026-07-28T00:00:00+08:00",
    "data_through": "2024-09-23",
    "validation_run_id": "legacy-mr-20260728",
    "next_validate_after": "2026-09-26T00:00:00+08:00"
  },
  "BULL": {
    "status": "stale",
    "validated_at": "2026-07-28T00:00:00+08:00",
    "data_through": "2026-03-27",
    "validation_run_id": "legacy-mr-20260728",
    "next_validate_after": "2026-09-26T00:00:00+08:00"
  }
}
```

- [ ] **Step 5: 运行测试并提交**

Run: `python -m pytest tests/test_strategy_runtime.py -q`

Expected: PASS。

Run: `git add services/strategy_params.py config/strategy_runtime.json tests/test_strategy_runtime.py && git commit -m "feat: add mean reversion parameter lifecycle"`

## Task 2: 实现冻结样本外验证器

**Files:**
- Create: `services/mr_validation.py`
- Create: `tests/test_mr_validation.py`
- Read/reuse: `strategies/mr_backtest_engine.py`
- Read/reuse: `engines/mean_reversion_engine.py`

- [ ] **Step 1: 写入无前视和共同区间的失败测试**

用小型确定性价格矩阵覆盖以下契约：

```python
def test_regime_labels_do_not_change_when_future_prices_are_appended():
    prefix = _benchmark_series(180)
    extended = pd.concat([prefix, _future_shock(20)])
    assert classify_regimes(prefix).tolist() == classify_regimes(extended).iloc[:180].tolist()

def test_validation_compares_both_candidates_on_identical_window():
    result = compare_incumbent_and_challenger(
        prices=_prices(), benchmark=_benchmark(),
        incumbent=_incumbent(), challenger=_challenger(),
        oos_start=date(2026, 3, 28), costs=_costs(),
    )
    assert result["incumbent"]["oos_start"] == result["challenger"]["oos_start"]
    assert result["incumbent"]["data_through"] == result["challenger"]["data_through"]
```

同时测试：信号至少滞后一日、交易成本同时施加于两组参数、状态样本天数和交易数不足时结论为 `insufficient_evidence`。

- [ ] **Step 2: 运行测试并确认红灯**

Run: `python -m pytest tests/test_mr_validation.py -q`

Expected: FAIL，模块尚不存在。

- [ ] **Step 3: 实现逐日前缀市场状态分类**

`classify_regimes` 必须对每个交易日只传入截至当日的基准数据，复用生产引擎的分类规则：

```python
def classify_regimes(benchmark: pd.Series) -> pd.Series:
    labels: list[str] = []
    for end in range(1, len(benchmark) + 1):
        history = benchmark.iloc[:end].to_numpy(dtype=float)
        if len(history) < 120:
            labels.append("RANGE")
        else:
            labels.append(_classify_regime_from_series(history)["regime"])
    return pd.Series(labels, index=benchmark.index, name="regime")
```

若生产分类器没有稳定的可复用入口，先将其提取为同文件的纯函数，生产路径和验证路径共同调用，避免复制两套阈值。

- [ ] **Step 4: 实现动态参数组合回测**

在 `services/mr_validation.py` 中实现 `run_parameter_set`：预先计算所有候选周期的 MA/RSI；当日只选当前 regime 的参数；在 `t` 日收盘生成信号，最早于 `t+1` 日进入收益；止损、退出和手续费遵循 `mr_backtest_engine` 的现有定义。

返回结构固定为：

```python
{
    "oos_start": "2026-03-28",
    "data_through": "2026-10-12",
    "portfolio": {"sharpe": 0.0, "max_drawdown": 0.0, "calmar": 0.0},
    "by_regime": {
        "BEAR": {
            "sharpe": 0.0, "max_drawdown": 0.0, "calmar": 0.0,
            "coverage": 0.0, "trades": 0, "regime_days": 0
        }
    }
}
```

关键实现约束：

```python
executed_position = desired_position.shift(1).fillna(0.0)
turnover = executed_position.diff().abs().fillna(executed_position.abs())
net_return = executed_position * asset_return - turnover * total_cost_rate
```

- [ ] **Step 5: 实现证据和比较判定**

```python
MIN_REGIME_DAYS = 60
MIN_TRADES = 5

def compare_regime(incumbent: dict, challenger: dict) -> dict:
    if min(incumbent["regime_days"], challenger["regime_days"]) < MIN_REGIME_DAYS:
        return {"decision": "INSUFFICIENT_EVIDENCE", "reason": "regime_days"}
    if incumbent["trades"] < MIN_TRADES and challenger["trades"] < MIN_TRADES:
        return {"decision": "INSUFFICIENT_EVIDENCE", "reason": "trades"}
    incumbent_passes = passes_absolute_gates(incumbent)
    challenger_passes = passes_absolute_gates(challenger)
    if challenger_passes and no_material_regression(incumbent, challenger):
        return {"decision": "ACCEPT_CHALLENGER", "reason": "all_gates_passed"}
    if incumbent_passes:
        return {"decision": "REVALIDATE_INCUMBENT", "reason": "incumbent_remains_valid"}
    return {"decision": "REJECT", "reason": "absolute_gates_failed"}
```

绝对门槛复用流水线常量：Sharpe ≥ 0.5、最大回撤 ≥ -25%、Calmar ≥ 0.3、覆盖率 ≥ 15%、交易数 ≥ 5。相对门槛为 challenger 的核心指标不得比 incumbent 恶化超过 10%。

- [ ] **Step 6: 运行测试并提交**

Run: `python -m pytest tests/test_mr_validation.py -q`

Expected: PASS，且测试输出没有 warning 被误当成功。

Run: `git add services/mr_validation.py tests/test_mr_validation.py engines/mean_reversion_engine.py && git commit -m "feat: add frozen OOS validation for mean reversion"`

## Task 3: 把证据门槛接入 CI 发布

**Files:**
- Modify: `services/strategy_pipeline.py`
- Modify: `services/strategy_params.py`
- Modify: `tests/test_strategy_pipeline.py`
- Modify: `tests/test_strategy_runtime.py`

- [ ] **Step 1: 写入禁止无证据发布的失败测试**

覆盖四条路径：

```python
@pytest.mark.parametrize("decision", ["REJECT", "INSUFFICIENT_EVIDENCE"])
def test_mr_publication_refuses_non_publishable_validation(decision):
    run = _mr_run(validation={"decision": decision})
    with pytest.raises(ValueError, match="not publishable"):
        publish_ci_parameters(run)

def test_revalidate_incumbent_updates_only_lifecycle(): ...
def test_accept_challenger_updates_params_and_lifecycle_atomically(): ...
```

还要断言 `data_through`、`validation_run_id`、`validated_at` 和 `next_validate_after` 在一次 revision 中共同落盘。

增加 `run_mr_ci(dry_run=True)` 测试，断言它返回完整验证结果但不调用 `publish_ci_parameters`、不写 CI 数据库；默认 `dry_run=False` 保持定时任务兼容。

- [ ] **Step 2: 运行测试并确认失败**

Run: `python -m pytest tests/test_strategy_pipeline.py tests/test_strategy_runtime.py -q`

Expected: FAIL，旧发布器仍允许只凭 `ACCEPT` 和旧指标发布。

- [ ] **Step 3: 修改流水线决策**

`run_mr_ci` 的每个 regime 使用当前运行时参数构造 incumbent，并仅替换对应 regime 构造 challenger。调用冻结样本外验证器后，将以下内容写入 CI 运行记录：

```python
run["validation"] = {
    "method": "frozen_oos",
    "oos_start": validation["oos_start"],
    "data_through": validation["data_through"],
    "decision": comparison["decision"],
    "reason": comparison["reason"],
    "incumbent": validation["incumbent"]["by_regime"][regime],
    "challenger": validation["challenger"]["by_regime"][regime],
}
```

状态映射固定为：`ACCEPT_CHALLENGER → ACCEPT`、`REVALIDATE_INCUMBENT → REVALIDATED`、`INSUFFICIENT_EVIDENCE → INSUFFICIENT_EVIDENCE`、`REJECT → REJECT`。

给 `run_mr_ci` 增加仅关键字参数 `dry_run: bool = False`。`dry_run=True` 时仍执行优化与验证，但跳过参数发布和 `ac_db.save_ci_run`，从而提供真正只读的预演路径；返回对象加入 `dry_run: true`。

- [ ] **Step 4: 修改原子发布器**

`publish_ci_parameters` 只允许 MR 的 `ACCEPT` 和 `REVALIDATED`。`_apply_ci_update` 的规则：

- `ACCEPT`：写入 challenger 参数和止损，再更新该 regime 生命周期为 `validated`。
- `REVALIDATED`：保留 incumbent 参数，只更新该 regime 生命周期证据。
- 其他状态：抛出 `ValueError`，不得提升 revision。

`next_validate_after` 由 `validated_at + 60 days` 计算；必须保留原子临时文件替换和 `.bak` 备份。

- [ ] **Step 5: 运行测试并提交**

Run: `python -m pytest tests/test_strategy_pipeline.py tests/test_strategy_runtime.py tests/test_mr_validation.py -q`

Expected: PASS。

Run: `git add services/strategy_pipeline.py services/strategy_params.py tests/test_strategy_pipeline.py tests/test_strategy_runtime.py && git commit -m "feat: require OOS evidence for MR publication"`

## Task 4: 运行时失效保护且不影响退出

**Files:**
- Modify: `engines/mean_reversion_engine.py`
- Create: `tests/test_mr_runtime_lifecycle.py`

- [ ] **Step 1: 写入买入被阻止、退出仍执行的失败测试**

```python
def test_stale_lifecycle_blocks_new_buy(monkeypatch):
    _mock_lifecycle(monkeypatch, status="stale", allow_new_entries=False)
    signal = engine.generate_signal(_oversold_buy_indicators(), score=90)
    assert signal["action"] == "no_entry"
    assert signal["reason"] == "validation_expired"

@pytest.mark.parametrize("exit_case", ["stop_loss", "rsi_sell", "sell_half", "sell_weak"])
def test_stale_lifecycle_does_not_block_exit(monkeypatch, exit_case):
    _mock_lifecycle(monkeypatch, status="stale", allow_new_entries=False)
    assert engine.generate_signal(_exit_indicators(exit_case), score=90)["action"].startswith("sell")
```

- [ ] **Step 2: 运行测试并确认红灯**

Run: `python -m pytest tests/test_mr_runtime_lifecycle.py -q`

Expected: FAIL，旧引擎会在 stale 状态继续买入或在过早返回时吞掉退出。

- [ ] **Step 3: 把生命周期加入指标结果**

状态识别完成后调用 `get_mr_lifecycle(regime)`，并在返回对象中加入：

```python
{
    "parameter_lifecycle": lifecycle["status"],
    "allow_new_entries": lifecycle["allow_new_entries"],
    "lifecycle_reason": lifecycle["reason"],
    "parameter_data_through": lifecycle["data_through"],
}
```

`needs_reoptimize` 改为查询有效生命周期，不再只比较全局 `next_optimize_after`。`get_all_regime_params` 的 `optimized_at` 改取各 regime 的 `validated_at`，不得伪装成全局 `published_at`。

- [ ] **Step 4: 调整信号判断顺序**

固定顺序为：灾难性数据保护 → 止损 → RSI/趋势退出 → 减仓 → 买入候选 → 生命周期准入。只有“本来会买入”的路径在不可用状态下转换为 `no_entry`；普通 hold 不需要伪装成生命周期错误。

- [ ] **Step 5: 运行测试并提交**

Run: `python -m pytest tests/test_mr_runtime_lifecycle.py tests/test_mean_reversion_engine.py -q`

若仓库没有 `tests/test_mean_reversion_engine.py`，运行 `python -m pytest tests -q -k "mean_reversion or mr_runtime"`。

Expected: PASS。

Run: `git add engines/mean_reversion_engine.py tests/test_mr_runtime_lifecycle.py && git commit -m "fix: fail closed on stale MR entry parameters"`

## Task 5: 让审计和 API 使用同一事实源

**Files:**
- Modify: `engines/audit_engine.py`
- Modify: `routers/params_api.py`
- Create: `tests/test_mr_lifecycle_api_audit.py`

- [ ] **Step 1: 写入审计/API 失败测试**

```python
def test_strategy_config_api_exposes_effective_mr_lifecycle(client):
    payload = client.get("/api/v1/params/strategy-config").json()
    assert payload["mr"]["lifecycle"]["BEAR"]["allow_new_entries"] is False

def test_audit_ignores_legacy_mr_artifact_timestamp(monkeypatch):
    _mock_runtime_lifecycle(monkeypatch, all_status="validated")
    _make_legacy_result_very_old(monkeypatch)
    check = _mr_optimization_check(audit_strategy_health())
    assert check["status"] == "pass"
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `python -m pytest tests/test_mr_lifecycle_api_audit.py -q`

Expected: FAIL，API 不含 lifecycle，审计仍读取 `mr_optimization_results.json` 的年龄。

- [ ] **Step 3: 替换审计数据源**

从 `OPTIMIZATION_FILES` 去掉 MR 的旧结果文件年龄检查，增加 `_audit_mr_lifecycle`。结果至少包含：三个 regime 的有效状态、`data_through`、距下次验证天数、可否新开仓，以及 `validated_count/3`。

评分固定化以便测试：全部有效为 100；有 stale 为 40；有 insufficient evidence 为 35；有 rejected 为 20；字段缺失或配置非法为 0。任何非全部有效状态均不得报告 pass。

- [ ] **Step 4: 扩展参数 API**

在 `/api/v1/params/strategy-config` 的 `mr` 响应中加入 `lifecycle: get_all_mr_lifecycle()`；现有字段保持兼容。

- [ ] **Step 5: 运行测试并提交**

Run: `python -m pytest tests/test_mr_lifecycle_api_audit.py tests/test_strategy_runtime.py -q`

Expected: PASS。

Run: `git add engines/audit_engine.py routers/params_api.py tests/test_mr_lifecycle_api_audit.py && git commit -m "fix: audit MR lifecycle from runtime evidence"`

## Task 6: 消除前端回测参数漂移

**Files:**
- Modify: `static/js/backtest.js`
- Create: `tests/test_backtest_runtime_params.py`

- [ ] **Step 1: 写入前端参数来源的失败测试**

由于项目没有 JavaScript 单元测试框架，先用静态契约测试锁定数据源、转换和错误降级：

```python
def test_backtest_loads_mr_presets_from_runtime_api():
    source = Path("static/js/backtest.js").read_text(encoding="utf-8")
    assert "/api/v1/params/strategy-config" in source
    assert "applyRuntimeMrParams" in source
    assert "bias_buy * 10" in source
    assert "stop_loss * 100" in source
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `python -m pytest tests/test_backtest_runtime_params.py -q`

Expected: FAIL，页面仍只使用硬编码 preset。

- [ ] **Step 3: 实现运行时参数水合**

在页面初始化时请求 `/api/v1/params/strategy-config`。`applyRuntimeMrParams` 将 `BEAR/RANGE/BULL` 写回前端 preset；后端 `bias_buy` 转换为 UI 的十倍整数刻度，`stop_loss` 转换为百分比。默认表单使用 RANGE 的生产值。

请求失败时保留当前表单值并显示非阻断警告；不得悄悄用另一套硬编码“生产 preset”。为避免闪烁，参数请求完成后再首次渲染 MR 默认表单。

- [ ] **Step 4: 运行测试并提交**

Run: `python -m pytest tests/test_backtest_runtime_params.py -q`

Expected: PASS。

Run: `git add static/js/backtest.js tests/test_backtest_runtime_params.py && git commit -m "fix: source MR backtest presets from runtime config"`

## Task 7: 运行真实验证并按结果科学发布

**Files:**
- Modify if publication succeeds: `config/strategy_runtime.json`
- Create/update: `data_lake/ci_runs/mr_*.json`
- Create/update: `data_lake/strategy_runtime_backups/*`

- [ ] **Step 1: 先运行只读 dry-run**

Run: `python -c "from services.strategy_pipeline import run_mr_ci; import json; print(json.dumps(run_mr_ci(dry_run=True), ensure_ascii=False, indent=2, default=str))"`

Expected: 每个 regime 输出共同的 `oos_start`、`data_through`、incumbent/challenger 指标、证据计数和明确 decision。任何缺数据、NaN 或日期不一致都应返回非发布状态，而不是异常吞掉后继续发布。

- [ ] **Step 2: 人工核对科学不变量**

确认：

- `data_through` 不晚于本地真实行情最新日。
- incumbent/challenger 日期完全相同。
- 交易数、状态日数、覆盖率不是由全样本伪装成单 regime 证据。
- 日 `t` 的信号从日 `t+1` 才计入收益。
- 费用在两组参数中相同且非零。

- [ ] **Step 3: 执行正式 CI 发布**

Run: `python -c "from services.strategy_pipeline import run_mr_ci; import json; print(json.dumps(run_mr_ci(), ensure_ascii=False, indent=2, default=str))"`

Expected:

- `ACCEPT_CHALLENGER`：参数与生命周期在同一 revision 原子更新。
- `REVALIDATE_INCUMBENT`：参数不变，仅证据和 revision 更新。
- `REJECT` 或 `INSUFFICIENT_EVIDENCE`：不发布该 regime，保持或写明不可开新仓的有效状态；不得刷新为 validated。

- [ ] **Step 4: 验证配置修订与备份**

Run: `python -c "from services.strategy_params import load_runtime_config,get_all_mr_lifecycle; c=load_runtime_config(); print(c['revision']); print(get_all_mr_lifecycle())"`

Expected: revision 单调递增；只有可发布结果是 `validated`；每个 validated 状态的 `validation_run_id` 都能定位到 CI 运行记录；备份保留发布前配置。

- [ ] **Step 5: 提交真实验证产物**

仅添加项目原本跟踪且对可复现性必要的配置/CI 摘要；不添加大量行情或临时文件。

Run: `git status --short`

Run: `git add config/strategy_runtime.json data_lake/ci_runs && git commit -m "chore: validate production MR parameters on frozen OOS data"`

若所有 regime 都因证据不足而未发布，跳过空提交，并在最终报告中明确这是安全成功而非优化失败。

## Task 8: 全量验证与生产就绪检查

**Files:**
- Verify only unless a regression is found

- [ ] **Step 1: 运行全量测试**

Run: `python -m pytest tests -q`

Expected: PASS。若存在环境依赖导致的已知无关失败，必须单独列出原命令、错误和为什么不影响本变更；不得把定向测试通过等同于全量通过。

- [ ] **Step 2: 运行生产就绪检查**

Run: `python engines/production_check.py --code-only`

Expected: 退出码 0，运行时配置和代码契约检查通过。

Run: `python engines/production_check.py`

Expected: 记录真实服务器数据就绪结果；如果数据健康检查有告警或失败，将其与本变更代码回归分开报告。

- [ ] **Step 3: 运行审计快照**

Run: `python -c "from engines.audit_engine import run_full_audit; import json; print(json.dumps(run_full_audit(), ensure_ascii=False, indent=2, default=str))"`

Expected: MR 项明确列出三种市场状态的证据和准入状态；分数与状态映射一致。

- [ ] **Step 4: 检查差异和仓库状态**

Run: `git diff --check`

Expected: 无空白错误。

Run: `git status --short --branch`

Expected: 只有明确说明的验证产物；源代码和测试均已提交。

- [ ] **Step 5: 处理验证阶段产生的必要修复**

若验证暴露本计划范围内的回归，先为该回归添加失败测试，再修复，并仅对 `git status --short` 中逐项确认过的具体文件执行 `git add 文件名`，提交信息使用 `test: verify MR parameter lifecycle readiness`。如果没有源代码变化，不创建空提交。不得使用 `git add .`，避免纳入用户文件或大体积生成数据。

## 完成判据

- 任何代码路径都不能只更新时间戳来让参数恢复“新鲜”。
- 当前 regime 生命周期非 validated 时，真实引擎不能产生新买入，但退出测试全部通过。
- 审计、API、引擎和前端均以 `strategy_runtime.json` 的生命周期为事实源。
- challenger 的发布能追溯到冻结样本外 CI 记录；incumbent 重验证不会悄悄改参数。
- 全量测试、生产就绪检查、审计快照和 `git diff --check` 均有新鲜输出证据。

# Operator Guide

## 目标

这份文档不是介绍“模块是什么”，而是告诉你：

- 平时应该从哪里进入这个系统
- 应该按什么顺序熟练它
- 每天怎么操作、看什么、怎么排查

如果只记一件事，记这句：

**先把它当成“观察和演练系统”，再把它当成“交易系统”。**

不要一上来就想自动实盘。

## 先建立正确认识

当前项目已经具备的能力：

- 多交易所 REST / WS 适配
- 资金费率扫描
- 同所 `spot + perp` 套利主服务
- 跨所 `perp spread` 主服务
- 执行、订单跟踪、自动落库、风控、控制面、飞书、supervisor
- 回测数据抓取和回测示例

当前最适合的使用方式：

1. 先离线理解模块和数据流
2. 再跑 fake runtime / dry-run
3. 再跑真实交易所只读连通
4. 最后才考虑下真实单

## 真正的入口

你应该优先使用这些入口，而不是先研究所有源码：

- `uv run pytest -q`
- `PYTHONPATH=src uv run python scripts/run_funding_arb_dry_run.py`
- `PYTHONPATH=src uv run python scripts/fetch_backtest_dataset.py ...`
- `PYTHONPATH=src uv run python examples/<name>.py`

要特别注意：

- [cli.py](/home/longcoding/dev/project/delta_stable/src/arb/cli.py) 现在还是“参数解析壳”，不是默认的生产主入口
- 真正更有操作价值的是 `scripts/` 和 `examples/`

## 建议学习顺序

### 第 1 阶段：先会看

先跑这些，不接真实交易所：

```bash
uv run pytest -q
PYTHONPATH=src uv run python examples/single_exchange_scan.py
PYTHONPATH=src uv run python examples/multi_exchange_scan.py
PYTHONPATH=src uv run python examples/strategy_spot_perp.py
PYTHONPATH=src uv run python examples/pair_execution.py
PYTHONPATH=src uv run python examples/portfolio_and_risk.py
```

这一阶段你要看懂 5 件事：

- `snapshot` 长什么样
- `opportunity` 是怎么排出来的
- 策略什么时候 `OPEN / HOLD / CLOSE / REBALANCE`
- 双腿执行失败时怎么补单和回滚
- 风控信号长什么样

### 第 2 阶段：先会演练

这一阶段的核心入口是：

```bash
PYTHONPATH=src uv run python scripts/run_funding_arb_dry_run.py \
  --exchange binance \
  --symbol BTC/USDT \
  --iterations 3 \
  --funding-sequence 0.001 0.0008 -0.0002
```

然后再跑带守护的版本：

```bash
PYTHONPATH=src uv run python scripts/run_funding_arb_dry_run.py \
  --exchange binance \
  --symbol BTC/USDT \
  --iterations 3 \
  --supervised \
  --max-restarts 2 \
  --funding-sequence 0.001 0.0008 -0.0002
```

这一阶段你要确认 4 件事：

- funding 为正时会开仓
- funding 转弱或转负时会平仓
- `workflow_state` 会按 `opening -> open -> closing -> closed` 变化
- supervisor 遇到异常会有限次重启

### 第 3 阶段：接真实环境，但先只读

先看：

- [live-exchange-onboarding.md](/home/longcoding/dev/project/delta_stable/docs/live-exchange-onboarding.md)
- [funding-arb-runbook.md](/home/longcoding/dev/project/delta_stable/docs/funding-arb-runbook.md)
- [operations-checklist.md](/home/longcoding/dev/project/delta_stable/docs/operations-checklist.md)

先做这些：

```bash
PYTHONPATH=src uv run python examples/runtime_smoke.py
PYTHONPATH=src uv run python examples/live_binance_smoke.py
```

如果你要批量准备回测数据：

```bash
PYTHONPATH=src uv run python scripts/fetch_backtest_dataset.py \
  --symbol BTCUSDT ETHUSDT SOLUSDT \
  --start 2024-01 \
  --end 2024-12 \
  --output-dir data/backtest/binance
```

这一阶段的原则：

- 只接 `1` 家交易所
- 只看 `BTC/USDT`
- 只读优先
- 先确认连通、权限、日志、告警、落库都正常

### 第 4 阶段：再学会控制和接管

重点看：

```bash
PYTHONPATH=src uv run python examples/control_api.py
PYTHONPATH=src uv run python examples/feishu_integration.py
```

你要熟练 4 件事：

- 查看当前 `positions`
- 查看 `orders`
- 查看 `workflows`
- 知道 `manual_open / manual_close / cancel_workflow / close_all` 这些命令走的链路

## 日常操作路径

如果你每天只想知道“先干什么”，按这个顺序：

1. 跑测试，确认当前代码状态没坏
2. 跑单所扫描，看当前 funding 排行
3. 跑 dry-run，看主服务是否还能稳定开平仓
4. 看控制面和飞书链路是否可用
5. 需要时再接真实只读 runtime

推荐命令：

```bash
uv run pytest -q
PYTHONPATH=src uv run python examples/backtest_report.py
PYTHONPATH=src uv run python examples/backtest_threshold_strategy.py
PYTHONPATH=src uv run python examples/single_exchange_scan.py
PYTHONPATH=src uv run python examples/multi_exchange_scan.py
PYTHONPATH=src uv run python scripts/run_funding_arb_dry_run.py --exchange binance --symbol BTC/USDT --iterations 3 --funding-sequence 0.001 0.0008 -0.0002
PYTHONPATH=src uv run python examples/control_api.py
PYTHONPATH=src uv run python examples/feishu_integration.py
```

## 回测参数怎么解读

如果你打算先用回测熟悉这个系统，先盯这 7 个参数：

- `open_threshold`：只有 funding 厚到值得做时才开仓。这个值应该覆盖你预估的手续费、借币和执行不确定性。
- `close_threshold`：资金费率走弱到这个水平以下就退出。它通常低于 `open_threshold`。
- `hysteresis`：当你没显式给 `close_threshold` 时，用来自动留出开平仓间隔，避免频繁抖动。
- `open_fee_rate`：开仓时扣一次。
- `close_fee_rate`：平仓时扣一次。
- `rebalance_fee_rate`：只有发生再平衡时才扣。
- `borrow_rate`：每个 funding 周期都计入持仓成本。

一个更稳的起步方式是：

1. 先只配置 `open_threshold`、`close_threshold`
2. 再补 `open_fee_rate` 和 `close_fee_rate`
3. 最后再补 `rebalance_fee_rate`、`rebalance_threshold_bps`、`borrow_rate`

你真正要看的不是只有 `total_return`，还要一起看：

- `trade_count`
- `capital_utilization`
- `average_trade_return`
- 每笔交易的 `funding_pnl / fee / borrow / rebalance`

如果 `capital_utilization` 很高但 `average_trade_return` 很低，说明你基本一直在持仓，但 carry 不够厚；这种参数通常不适合实盘。

## 你真正要盯的对象

熟练使用这个系统，不是记住每个类名，而是知道这 6 类输出怎么看：

### 1. `snapshots`

看：

- `ticker`
- `funding`
- `liquidity_usd`
- `view`（如果有 spot/perp 同步视图）

### 2. `opportunities`

看：

- `gross_rate`
- `net_rate`
- `annualized_net_rate`
- `spread_bps`
- `liquidity_usd`

### 3. `workflow_state`

看：

- 有没有卡在 `opening`
- 有没有卡在 `closing`
- 状态切换是否完整

### 4. `orders`

看：

- 是否出现长时间未成交
- 是否出现部分成交后未补单
- 是否出现单腿成交

### 5. `positions`

看：

- 数量是否平衡
- 是否有裸腿
- 是否和你预期的交易所、币种一致

### 6. 风控信号

重点看：

- `funding_reversal`
- `naked_leg`
- `basis_out_of_range`
- `liquidation_buffer_low`

## 什么时候该用哪个文档

- 想快速跑起来：看 [simple-usage-manual.md](/home/longcoding/dev/project/delta_stable/docs/simple-usage-manual.md)
- 想日常熟练使用：看这份文档
- 想知道主服务怎么运行：看 [funding-arb-runbook.md](/home/longcoding/dev/project/delta_stable/docs/funding-arb-runbook.md)
- 想看上线前检查：看 [operations-checklist.md](/home/longcoding/dev/project/delta_stable/docs/operations-checklist.md)
- 想看架构主链：看 [funding-arb-architecture-overview.md](/home/longcoding/dev/project/delta_stable/docs/funding-arb-architecture-overview.md)
- 想按调用链读懂代码：看 [project-analysis-guide.md](/home/longcoding/dev/project/delta_stable/docs/project-analysis-guide.md)

## 最容易犯的错

- 把 `cli.py` 当成已经完全接好的生产入口
- 还没跑 dry-run 就想连真实执行
- 同时接太多交易所
- 一开始就做跨所实盘
- 只看 funding，不看 `spread_bps`、流动性和执行闭环
- 只看策略，不看 `workflow_state` 和 `orders`

## 一个最稳的熟练路径

如果你想在一周内把这个系统用熟，建议这样：

### Day 1

- 跑完整测试
- 跑 `single_exchange_scan.py`
- 跑 `strategy_spot_perp.py`

### Day 2

- 跑 `pair_execution.py`
- 跑 `portfolio_and_risk.py`
- 看懂执行和风控

### Day 3

- 跑 `run_funding_arb_dry_run.py`
- 看 `opened / closed / active` 的变化

### Day 4

- 跑 `control_api.py`
- 跑 `feishu_integration.py`
- 看命令和确认链路

### Day 5

- 跑 `runtime_smoke.py`
- 准备真实交易所只读联调

### Day 6+

- 再开始 live/testnet runtime 装配
- 再决定是否接真实执行

## 结论

如果你想“熟练使用”这个系统，顺序应该是：

**观察 -> 演练 -> 控制 -> 只读 live -> 小规模执行**

不要反过来。

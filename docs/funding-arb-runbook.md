# Funding Arb Runbook

## 目标

这份 runbook 只覆盖当前仓库已经具备的能力：

- 资金费率扫描
- spot/perp 开平仓工作流
- 工作流状态持久化
- 手动控制与飞书交互
- 本地 dry-run 验证

不要把它当成“直接上生产的说明书”。当前更适合先跑 `dry-run`，再接少量真实交易所。

## 最小运行顺序

1. 安装依赖
2. 跑测试
3. 跑 `scripts/run_funding_arb_dry_run.py`
4. 检查工作流状态、订单状态、告警
5. 再把 runtime 替换成真实交易所
6. 如果要模拟守护进程异常恢复，开启 `--supervised`

## dry-run 命令

```bash
PYTHONPATH=src uv run python scripts/run_funding_arb_dry_run.py \
  --exchange binance \
  --symbol BTC/USDT \
  --iterations 3 \
  --supervised \
  --max-restarts 2 \
  --funding-sequence 0.001 0.0008 -0.0002
```

默认行为：

- 前两次迭代 funding 为正，主服务会尝试开仓
- 当 funding 转负时，主服务会触发平仓

输出示例：

```text
iteration=1 opened=1 closed=0 active=1
iteration=2 opened=0 closed=0 active=1
iteration=3 opened=0 closed=1 active=0
supervisor completed=3 restarts=0 healthy=True
```

## 建议环境变量

- `ARB_EXCHANGE`
- `ARB_SYMBOL`
- `ARB_ITERATIONS`
- `ARB_FUNDING_SEQUENCE`
- `ARB_CONTROL_TOKEN`
- `BINANCE_KEY`
- `BINANCE_SECRET`
- `OKX_KEY`
- `OKX_SECRET`
- `OKX_PASSPHRASE`

## 上线前检查

- 只接 `1` 家交易所
- 只跑 `BTC/USDT`
- 先开 `dry-run`
- 确认订单状态历史有落库
- 确认 workflow_state 有 `opening -> open -> closing -> closed`
- 确认控制 API 能看到 `orders` 和 `workflows`
- 确认飞书卡片按钮能触发 `confirm / cancel`
- 确认 supervisor 在异常时会有限次重启，而不是无限重试

## 限额建议

- 单币种 notional 上限：先从很小的限额开始
- 单交易所同时只开一个同币种实例
- kill switch 默认启用 `reduce-only`

## 告警建议

至少保留：

- snapshot 拉取失败
- order tracking timeout
- naked leg
- liquidation buffer low
- workflow 长时间停留在 `opening` 或 `closing`

## 手动接管步骤

1. 通过控制 API 或飞书查看当前 `orders`
2. 查看 `workflows`
3. 如果工作流卡在待确认，先 `confirm` 或 `cancel`
4. 如果仓位异常，启用 kill switch 的 `reduce-only`
5. 手动触发平仓命令
6. 用 `workflow_state` 和 `order_status_history` 复盘

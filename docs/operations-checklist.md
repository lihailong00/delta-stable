# Operations Checklist

## 启动前

- 确认只启用了计划接入的交易所和币种
- 确认 `read-only` / `dry-run` / `testnet` 开关符合当前环境
- 确认 API key 权限最小化
- 确认 `workflow_state`、`orders`、`positions` 存储可写
- 确认告警渠道正常

## 启动时

- 先跑 `uv run pytest -q`
- 先跑 `scripts/run_funding_arb_dry_run.py --supervised`
- 观察至少一轮 `opened -> closed` 或稳定 `hold`
- 观察 supervisor 输出的 `restart_count`

## 运行中

- 看 `workflow_state` 是否长时间停在 `opening` / `closing`
- 看 `order_status_history` 是否持续更新
- 看是否出现重复 `manual_open_pending`
- 看 supervisor 是否频繁重启
- 看 funding board 是否还有足够容量和净收益

## 异常处理

- 如果出现裸腿，优先 `reduce-only`
- 如果出现频繁超时，暂停策略并检查网络 / 限频
- 如果 workflow 卡死，先 `cancel_workflow`，再检查持仓对账
- 如果 supervisor 连续重启达到上限，停止主循环并人工接管

## 回滚

- 关闭自动开仓
- 保留只读监控和 funding board
- 通过控制面逐个关闭未完成 workflow
- 导出最近的 `workflow_state`、`orders`、`positions` 做复盘

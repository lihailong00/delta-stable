# Operator Guide

## 这份文档负责什么

这份文档现在是 `docs/` 下唯一的操作入口文档，负责合并原来的：

- quick start
- onboarding
- runbook
- operations checklist

如果你只是想把系统跑起来、接交易所、做日常排查，先看这里；如果你想理解模块结构和代码阅读路径，再看 [funding-arb-architecture-overview.md](/home/longcoding/dev/project/delta_stable/docs/funding-arb-architecture-overview.md)。

## 推荐使用顺序

1. 先看仓库根目录的 [README.md](/home/longcoding/dev/project/delta_stable/README.md)，确认项目定位和主能力。
2. 安装依赖并跑测试，先保证本地环境正常。
3. 跑一遍 `dry-run` 或最小 CLI，先把系统当成“可观察、可演练的系统”。
4. 再去接真实交易所公有/私有接口。
5. 稳定后才考虑长期运行和自动执行。

## 最小启动路径

### 1. 安装依赖

```bash
uv sync --group dev
```

### 2. 跑测试

```bash
uv run pytest -q
```

### 3. 跑 dry-run

```bash
PYTHONPATH=src uv run python scripts/run_funding_arb_dry_run.py
```

如果你要顺便验证 supervisor/recovery 路径，可以加：

```bash
PYTHONPATH=src uv run python scripts/run_funding_arb_dry_run.py --supervised
```

### 4. 跑几个常用入口

```bash
PYTHONPATH=src .venv/bin/python -m arb.cli scan --exchange binance --symbol BTC/USDT
PYTHONPATH=src .venv/bin/python -m arb.cli backtest --dataset funding.csv --strategy spot_perp
```

## 交易所接通顺序

建议先接 `Binance` 或 `OKX`，原因是这两家在当前仓库里覆盖面最完整，也最适合先验证：

1. 公有 REST 能通
2. 公有 WS 能通
3. 私有鉴权能通
4. `dry-run` 能跑出完整扫描/工作流链路

不要一上来就直接开自动执行。

## 接通真实交易所时要做的检查

- API key 权限最小化，先只开读权限和必要的交易权限
- `testnet` / `dry-run` / `read-only` 开关符合当前环境
- 公有 `public_ping` 正常
- 私有 `validate_private_access` 正常
- `workflow_state`、`orders`、`positions` 存储可写
- 告警通道和日志输出正常

## 日常观察点

- `workflow_state` 是否长时间停在 `opening` / `closing`
- `orders`、`positions` 是否持续更新
- `order_status_history` 是否断流
- supervisor 的 `restart_count` 是否异常增长
- funding board 是否还有足够容量和净收益
- 是否出现重复 `manual_open_pending`

## 常见排查顺序

### 鉴权失败

先看：

- 环境变量是否加载
- API key 权限是否完整
- 交易所时间戳/签名是否漂移
- 当前环境是不是把 `testnet` 和 live endpoint 混用了

### 工作流卡住

先看：

- `workflow_state`
- `orders`
- `positions`
- 执行日志里是否出现一腿成交、一腿补单、回滚失败

### 重启频繁

先看：

- supervisor/recovery 日志
- 私有 WS 是否频繁断开
- 控制面/告警是否有重复异常
- 交易所接口是否触发 rate limit

## 什么时候该看别的文档

- 想理解系统模块和主链路：看 [funding-arb-architecture-overview.md](/home/longcoding/dev/project/delta_stable/docs/funding-arb-architecture-overview.md)
- 想改建模和类型门禁：看 [pydantic-modeling-guide.md](/home/longcoding/dev/project/delta_stable/docs/pydantic-modeling-guide.md)
- 想看 transport 抽离和兼容层：看 [typed-transport-guide.md](/home/longcoding/dev/project/delta_stable/docs/typed-transport-guide.md)

## 当前建议

把这个项目先当成：

- 可测试的核心部件集合
- 可演练的 `dry-run` 系统
- 后续实盘系统的骨架

不要把它当成“已经完全配置好、直接能长期自动实盘的服务”。

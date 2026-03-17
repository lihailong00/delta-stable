# Delta Stable

一个面向 CEX 资金费率套利的模块化项目骨架。当前仓库已经把核心链路拆出来了：交易所适配、行情采集、机会扫描、策略、执行、仓位资金、风控、PnL、监控、回测、控制 API，以及飞书集成。

这套代码的定位不是“已经能直接实盘跑的完整服务”，而是“实盘系统的可测试核心部件”。现在每个模块都能单独测试、单独替换，后续你可以按自己的部署方式把它们串成一个长期运行的进程或多个服务。

简单使用手册见 [simple-usage-manual.md](/home/longcoding/dev/project/delta_stable/docs/simple-usage-manual.md)。
日常操作和熟练使用路径见 [operator-guide.md](/home/longcoding/dev/project/delta_stable/docs/operator-guide.md)。
Pydantic 建模约束和类型门禁见 [pydantic-modeling-guide.md](/home/longcoding/dev/project/delta_stable/docs/pydantic-modeling-guide.md) 与 [type-checking-guide.md](/home/longcoding/dev/project/delta_stable/docs/type-checking-guide.md)。

## 阈值回测怎么用

资金费率回测现在支持“`funding >= open_threshold` 才开仓，`funding < close_threshold` 就平仓”的状态机，不再默认整段历史一直持仓。

- `open_threshold`：只有 funding 厚到足以覆盖手续费、借币和执行风险时才进场
- `close_threshold`：持仓后 funding 变弱到这个阈值以下就退出
- `hysteresis`：如果你不显式给 `close_threshold`，就用 `open_threshold - hysteresis`，避免阈值附近频繁开平
- `open_fee_rate / close_fee_rate`：只在开仓和平仓时扣一次
- `rebalance_fee_rate / rebalance_threshold_bps`：只有价格偏离到需要再平衡时才扣
- `borrow_rate`：持仓期间每个 funding 周期都计入
- `threshold_interval_hours`：阈值比较使用的统一周期。`1h/2h/4h/8h` funding 必须先归一化到同一周期再比较，不能直接拿原始值横向看。

可以直接跑两个离线例子：

```bash
PYTHONPATH=src uv run python examples/backtest_report.py
PYTHONPATH=src uv run python examples/backtest_threshold_strategy.py
```

## 当前包含什么

- 交易所适配：`Binance`、`OKX`、`Bybit`、`Gate`
- 市场数据：快照采集、标准化、事件路由
- 扫描器：资金费率净收益、年化收益、流动性过滤
- 策略：同所 `现货多 + 永续空`，跨所永续 spread
- 执行：双腿联动、部分成交补单、失败回滚
- 组合管理：仓位聚合、净敞口、资金分配
- 风控：爆仓距离、基差异常、funding 反转、kill switch
- 账本：PnL 归因、日报、导出
- 监控：健康检查、告警去重、指标输出
- 回测：funding 回放与结果报告
- 控制平面：控制 API、命令分发、审计
- 飞书：token、卡片、事件回调、按钮动作解析

## 快速开始

### 1. 环境

- Python `3.12+`
- 推荐使用 `uv`

```bash
uv sync --group dev
```

### 2. 运行测试

```bash
uv run pytest -q
```

当前仓库完整测试结果是 `153 passed`。

### 3. 运行 CLI

```bash
PYTHONPATH=src .venv/bin/python -m arb.cli scan --exchange binance --symbol BTC/USDT
PYTHONPATH=src .venv/bin/python -m arb.cli execute --strategy spot_perp --confirm
PYTHONPATH=src .venv/bin/python -m arb.cli backtest --dataset funding.csv --strategy spot_perp
PYTHONPATH=src .venv/bin/python -m arb.cli report --date 2026-03-16
```

当前 CLI 是轻量入口，主要用于统一参数解析和后续系统集成。

## 怎么用

### 1. 接交易所

交易所适配器都设计成“注入 transport”的模式，方便你在测试里 mock，也方便你后续替换成真实 HTTP 客户端。

```python
from decimal import Decimal

from arb.exchange.binance import BinanceExchange
from arb.models import MarketType


async def transport(request: dict) -> dict:
    # 这里替换成真实 HTTP 请求
    return {
        "symbol": "BTCUSDT",
        "bidPrice": "100.0",
        "askPrice": "101.0",
        "bidQty": "1.0",
        "askQty": "2.0",
    }


client = BinanceExchange("api-key", "api-secret", transport=transport)
ticker = await client.fetch_ticker("BTC/USDT", MarketType.SPOT)
print(ticker)
```

对应模块：

- `src/arb/exchange/`
- `src/arb/ws/`

### 2. 采集行情并扫描机会

```python
from decimal import Decimal

from arb.market.collector import MarketDataCollector
from arb.models import MarketType
from arb.scanner.funding_scanner import FundingScanner


collector = MarketDataCollector({"binance": client})
snapshot = await collector.collect_snapshot("binance", "BTC/USDT", MarketType.PERPETUAL)

scanner = FundingScanner(
    trading_fee_rate=Decimal("0.0002"),
    slippage_rate=Decimal("0.0001"),
    min_net_rate=Decimal("0.0001"),
    min_liquidity_usd=Decimal("1000"),
)

opportunities = scanner.scan([snapshot])
print(opportunities)
```

对应模块：

- `src/arb/market/`
- `src/arb/scanner/`

### 3. 用策略引擎生成动作

```python
from decimal import Decimal

from arb.strategy.engine import StrategyEngine, StrategyState
from arb.strategy.spot_perp import SpotPerpInputs, SpotPerpStrategy


strategy = SpotPerpStrategy(min_open_funding_rate=Decimal("0.0005"))
state = StrategyState()

decision = strategy.evaluate(
    SpotPerpInputs(
        symbol="BTC/USDT",
        funding_rate=Decimal("0.0008"),
        spot_price=Decimal("100"),
        perp_price=Decimal("100.1"),
    ),
    state=state,
)

engine = StrategyEngine()
engine.transition(state, decision)
print(decision, state)
```

对应模块：

- `src/arb/strategy/`

### 4. 执行双腿订单

```python
from decimal import Decimal

from arb.execution.executor import ExecutionLeg, PairExecutor
from arb.execution.guards import GuardContext
from arb.models import MarketType


context = GuardContext(
    available_balance=Decimal("10000"),
    max_notional=Decimal("5000"),
    supported_symbols={"BTC/USDT"},
)

executor = PairExecutor()
result = await executor.execute_pair(
    ExecutionLeg(client_spot, "BTC/USDT", MarketType.SPOT, "buy", Decimal("1"), Decimal("100"), context=context),
    ExecutionLeg(client_perp, "BTC/USDT", MarketType.PERPETUAL, "sell", Decimal("1"), Decimal("100"), context=context),
)
print(result.status)
```

对应模块：

- `src/arb/execution/`
- `src/arb/portfolio/`
- `src/arb/risk/`

### 5. 落库、报表、回测

```python
from pathlib import Path

from arb.storage.db import Database
from arb.storage.repository import Repository


database = Database(Path("var/data/arb.sqlite3"))
database.initialize()
repository = Repository(database)
```

对应模块：

- `src/arb/storage/`
- `src/arb/pnl/`
- `src/arb/backtest/`

### 6. 控制 API 和飞书

控制 API 目前支持：

- `/health`
- `/positions`
- `/strategies`
- `/commands`

如果环境里装了 `FastAPI`，可以直接把 app 跑起来；如果没装，也可以先直接使用服务对象本身做集成测试。

```python
from arb.control import ApiContext, create_app


context = ApiContext(
    positions_provider=lambda: [],
    strategies_provider=lambda: [],
    command_handler=lambda command: {"accepted": True, "command_id": "cmd-1", **command},
    auth_token="secret-token",
)

app = create_app(context)
```

飞书集成目前提供：

- tenant access token 获取和缓存
- 消息/卡片发送
- challenge 响应
- 回调验签
- 按钮动作解析

```python
from arb.integrations.feishu.client import FeishuClient
from arb.integrations.feishu.cards import build_positions_card


client = FeishuClient("app_id", "app_secret", transport=my_transport)
card = build_positions_card(
    [{"exchange": "binance", "symbol": "BTC/USDT", "direction": "long", "quantity": "1"}]
)
client.send_card(receive_id="ou_xxx", card=card)
```

对应模块：

- `src/arb/control/`
- `src/arb/integrations/feishu/`

## 目录说明

```text
src/arb/
  exchange/      # REST 交易所适配器
  ws/            # WebSocket 适配器
  market/        # 行情采集、标准化、路由
  scanner/       # 资金费率机会扫描
  strategy/      # 策略引擎
  execution/     # 执行引擎
  portfolio/     # 仓位和资金管理
  risk/          # 风控
  pnl/           # PnL 归因和报表
  monitoring/    # 健康检查、告警、指标
  backtest/      # 回测
  storage/       # SQLite 持久化
  control/       # 控制 API、命令、审计
  integrations/  # 飞书等外部集成
tests/           # 单元测试
current_tasks/   # 任务台账（已全部完成）
```

## 当前限制

- 现在是“模块齐全”的状态，不是“已经接好真实网络和调度器”的状态。
- 交易所适配器需要你自己接入真实 HTTP/WS 客户端。
- 控制 API 目前做了 `FastAPI` 可选集成，但仓库没有强制安装 Web 依赖。
- 飞书回调验签和消息发送已经有基础实现，但正式上线前建议按你的企业应用配置再核一遍。
- 目前没有单一的长期运行守护进程；你需要把扫描、策略、执行、监控、控制平面按自己的部署方式编排起来。

## 建议的下一步

如果你要把它推进到“可用 MVP”，建议按这个顺序：

1. 接通 `1-2` 家真实交易所 HTTP/WS 客户端
2. 把 `MarketDataCollector -> FundingScanner -> Strategy -> PairExecutor` 串成单进程
3. 把 `Repository` 和 `Monitoring` 接上
4. 用 `ControlAPI + CommandDispatcher + Feishu` 接手动平仓和暂停策略
5. 再考虑多策略、多交易所并行

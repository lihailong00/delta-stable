# Simple Usage Manual

## 1. 先理解当前项目是什么

这个仓库现在更像一套“可组装的资金费率套利组件”，不是已经完全组装好的实盘服务。

当前已经有：

- 六家交易所的 REST / WS 适配器
- live runtime
- 多交易所实时扫描器
- smoke 检查工具
- 存储、风控、执行、PnL、飞书等模块

当前还没有完全组装好的部分：

- 一个默认可直接执行真实扫描的 CLI 应用
- 一个默认可直接实盘下单的长期运行进程

所以最稳的用法是：

1. 先安装依赖
2. 先跑测试确认环境正常
3. 再写一个很小的脚本，把你需要的 runtime 和 scanner 组装起来

## 2. 安装依赖

在项目根目录执行：

```bash
uv sync --group dev
```

这会安装运行和测试当前仓库需要的依赖，包括 `pytest`。

## 3. 先确认项目是好的

执行：

```bash
uv run pytest -q
```

如果测试通过，说明你本地的 Python 环境、依赖和当前代码状态基本正常。

## 4. 最常见的两种用法

### 用法 A：先做连通性检查

如果你只是想确认交易所 API 是否能接通，先用 `SmokeRunner`。

最小示例：

```python
import asyncio

from arb.net.http import HttpTransport
from arb.runtime import BinanceRuntime, SmokeRunner


async def main() -> None:
    runtime = BinanceRuntime.build(
        api_key="your_key",
        api_secret="your_secret",
        http_transport=HttpTransport(),
        ws_connector=lambda endpoint: None,
    )
    runner = SmokeRunner({"binance": runtime})
    results = await runner.run_many(["binance"], private=False)
    for line in runner.summarize(results):
        print(line)


asyncio.run(main())
```

注意：

- 这类检查只适合先做 REST 连通验证
- 如果你要检查 private 权限，把 `private=False` 改成 `private=True`
- `ws_connector=lambda endpoint: None` 只是最小占位，真正用 WS 时要换成真实 connector

### 用法 B：做一次资金费率扫描

如果你想从代码里跑一次扫描，核心对象是：

- `LiveExchangeManager`
- `FundingScanner`
- `OpportunityPipeline`
- `RealtimeScanner`

最小示例：

```python
import asyncio
from decimal import Decimal

from arb.models import MarketType
from arb.net.http import HttpTransport
from arb.runtime import (
    BinanceRuntime,
    LiveExchangeManager,
    OpportunityPipeline,
    RealtimeScanner,
    ScanTarget,
)
from arb.scanner.funding_scanner import FundingScanner


async def main() -> None:
    runtime = BinanceRuntime.build(
        api_key="your_key",
        api_secret="your_secret",
        http_transport=HttpTransport(),
        ws_connector=lambda endpoint: None,
    )

    manager = LiveExchangeManager({"binance": runtime})
    scanner = FundingScanner(
        trading_fee_rate=Decimal("0.0002"),
        slippage_rate=Decimal("0.0001"),
        min_net_rate=Decimal("0.0001"),
    )
    pipeline = OpportunityPipeline()
    realtime = RealtimeScanner(manager, scanner, pipeline)

    result = await realtime.scan_once(
        [ScanTarget("binance", "BTC/USDT", MarketType.PERPETUAL)],
        dry_run=True,
    )

    print(result["output"])


asyncio.run(main())
```

这会走完整链路：

- runtime 拉交易所快照
- scanner 计算净 funding 收益
- pipeline 输出结果

### 用法 C：跑完整资金费率套利 dry-run

如果你想直接验证“扫描 -> 开仓 -> 持仓 -> 平仓”的主服务，而不是只看扫描结果，直接跑：

```bash
PYTHONPATH=src uv run python scripts/run_funding_arb_dry_run.py \
  --exchange binance \
  --symbol BTC/USDT \
  --iterations 3 \
  --funding-sequence 0.001 0.0008 -0.0002
```

这个脚本默认不连真实交易所，作用是验证：

- 主服务能根据 funding 信号开仓
- funding 反转后能触发平仓
- active workflow 数量是否按预期变化

如果这个脚本都跑不通，不要直接接真实执行。

## 5. 如果你要接真实交易所

建议按这个顺序：

1. 先只接 `Binance` 或 `OKX`
2. 先做 public smoke
3. 再做 private smoke
4. 再做 `dry-run` 扫描
5. 最后才考虑接执行模块

接真实交易所前，建议先读：

- [live-exchange-onboarding.md](/home/longcoding/dev/project/delta_stable/docs/live-exchange-onboarding.md)
- [funding-arb-runbook.md](/home/longcoding/dev/project/delta_stable/docs/funding-arb-runbook.md)

## 6. 如果你想快速看懂代码

建议阅读顺序：

1. [cli.py](/home/longcoding/dev/project/delta_stable/src/arb/cli.py)
2. [realtime_scanner.py](/home/longcoding/dev/project/delta_stable/src/arb/runtime/realtime_scanner.py)
3. [exchange_manager.py](/home/longcoding/dev/project/delta_stable/src/arb/runtime/exchange_manager.py)
4. [binance_runtime.py](/home/longcoding/dev/project/delta_stable/src/arb/runtime/binance_runtime.py)
5. [collector.py](/home/longcoding/dev/project/delta_stable/src/arb/market/collector.py)
6. [funding_scanner.py](/home/longcoding/dev/project/delta_stable/src/arb/scanner/funding_scanner.py)
7. [binance.py](/home/longcoding/dev/project/delta_stable/src/arb/exchange/binance.py)
8. [http.py](/home/longcoding/dev/project/delta_stable/src/arb/net/http.py)
9. [ws.py](/home/longcoding/dev/project/delta_stable/src/arb/net/ws.py)

如果你想按“从入口一层层往里”分析，再看：

- [project-analysis-guide.md](/home/longcoding/dev/project/delta_stable/docs/project-analysis-guide.md)

## 7. 现在不要直接做的事

当前阶段，不建议你一上来就做这些：

- 直接自动下真实单
- 同时接六家交易所跑实盘
- 一开始就做跨所自动资金调度
- 还没做 smoke 和 dry-run 就上飞书手动平仓

先把“连通、扫描、日志、告警”跑稳，再往执行走。

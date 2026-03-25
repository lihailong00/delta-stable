# Funding Arb Architecture Overview

## 这份文档负责什么

这份文档现在同时承担两件事：

- 解释当前资金费率套利系统的主链路
- 给出推荐的代码阅读路径

如果你想知道“系统怎么用”，看 [operator-guide.md](/home/longcoding/dev/project/delta_stable/docs/operator-guide.md)。如果你想知道“系统由哪些模块组成、以后该从哪里改”，看这里。

## 当前最完整的业务主链

同所 `spot + perp` 资金费率套利当前的主链可以按这个顺序理解：

1. `RealtimeScanner`
2. `FundingScanner`
3. `FundingArbService`
4. `OpenPositionWorkflow` / `ClosePositionWorkflow`
5. `PairExecutor + OrderTracker`
6. `Repository / monitoring / control`

跨所链路也已经有骨架，但成熟度次于同所主链。

## 模块分层

### 1. 协议和接入层

- `src/arb/exchange/`: REST 适配器
- `src/arb/ws/`: WS 适配器
- `src/arb/net/`: 项目内兼容 transport 层
- `src/typed_transport/`: 正在收敛出来的通用 transport 能力

### 2. 市场数据层

- `src/arb/market/`: 快照采集、标准化、事件路由
- `src/arb/scanner/`: funding 机会筛选和成本模型

### 3. 策略与执行层

- `src/arb/strategy/`: 策略决策
- `src/arb/workflows/`: 开平仓工作流
- `src/arb/execution/`: 双腿联动、订单跟踪、回滚

### 4. 组合、风控、状态层

- `src/arb/portfolio/`
- `src/arb/risk/`
- `src/arb/storage/`
- `src/arb/pnl/`

### 5. 运行时与控制层

- `src/arb/runtime/`: 交易所 runtime、scanner/service/supervisor
- `src/arb/bootstrap/`: runtime 装配
- `src/arb/control/`: 控制 API / command dispatch
- `src/arb/monitoring/`: board、health、alerts、metrics

## 为什么 runtime 现在是“共享基类 + 显式差异”

`src/arb/runtime/` 里的各交易所 runtime 结构相似，但并不适合彻底压成一个统一模板。

当前做法是：

- 公共装配逻辑收在 `base_runtime.py`
- 交易所特有行为仍留在各自 runtime 文件

原因很直接：

- 有的只有 public WS，有的有 public/private 两套 WS
- 有的是 `login`，有的是 `auth`
- 频道名、endpoint、私有会话流程都不同

所以这里追求的是“去掉重复样板”，而不是“把所有差异抽象掉”。

## 推荐代码阅读顺序

1. [README.md](/home/longcoding/dev/project/delta_stable/README.md)
2. `src/arb/bootstrap/live_runtime_factory.py`
3. `src/arb/runtime/base_runtime.py` 和 `src/arb/runtime/*_runtime.py`
4. `src/arb/market/` 与 `src/arb/scanner/`
5. `src/arb/strategy/` 与 `src/arb/workflows/`
6. `src/arb/execution/`
7. `src/arb/storage/`, `src/arb/control/`, `src/arb/monitoring/`

这个顺序的好处是：你会先看到“系统怎么被装起来”，再看到“数据怎么流动”，最后再看“外围能力”。

## 常见改动应该从哪里下手

### 加一个交易所

先看：

- `src/arb/exchange/`
- `src/arb/ws/`
- `src/arb/runtime/`
- `src/arb/bootstrap/live_runtime_factory.py`

### 改 funding 机会筛选规则

先看：

- `src/arb/scanner/funding_scanner.py`
- `src/arb/scanner/cost_model.py`

### 改开平仓策略

先看：

- `src/arb/strategy/`
- `src/arb/workflows/open_position.py`
- `src/arb/workflows/close_position.py`

### 改执行和补单逻辑

先看：

- `src/arb/execution/executor.py`
- `src/arb/execution/order_tracker.py`
- `src/arb/execution/router.py`

### 改风控或状态恢复

先看：

- `src/arb/risk/`
- `src/arb/runtime/recovery.py`
- `src/arb/runtime/supervisor.py`

## 当前项目的边界

这个仓库已经具备：

- 多交易所接入
- 市场快照与 funding 扫描
- 同所和跨所套利主服务骨架
- 执行、回滚、状态持久化、监控、控制面、回测

这个仓库还不等于：

- 一个默认就能直接长期自动实盘运行的成品服务
- 一个完全收敛完 transport/public API 的稳定 SDK

理解这一点，比继续往下翻更多细节更重要。

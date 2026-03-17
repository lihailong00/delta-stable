# Funding Arb Architecture Overview

## 这份文档解决什么问题

这不是使用手册，也不是运维 runbook。

它主要回答 4 个问题：

1. 当前资金费率套利系统由哪些核心模块组成
2. 一次完整运行时，数据和控制流怎么走
3. 哪些模块已经能组成闭环，哪些还是需要你后续替换成真实环境
4. 你以后要改策略、执行、风控或控制面，应该先动哪里

---

## 当前系统的主链路

现在项目里，最完整的一条业务主链是：

1. `RealtimeScanner`
2. `FundingScanner`
3. `FundingArbService`
4. `OpenPositionWorkflow`
5. `PairExecutor + OrderTracker`
6. `ClosePositionWorkflow`
7. `Repository + OpportunityPipeline`
8. `Control API / Feishu`

用一句话概括：

**先扫 funding 机会，再按单实例约束选择机会，再开仓，持仓期间继续扫描并判断是否该平，最后把状态落库并暴露给人工控制层。**

---

## 按层看系统

### 1. 协议与网络层

目录：

- `src/arb/exchange/`
- `src/arb/ws/`
- `src/arb/net/`

职责：

- 封装各交易所 REST/WS 协议
- 统一签名、鉴权、符号转换
- 把原始响应转换成统一模型

你应该把这一层理解成“外部世界适配器”。

如果这里出问题，常见现象是：

- smoke 失败
- funding 拉不到
- 私有 WS 没订单回报
- 订单状态查不到

---

### 2. 市场数据层

目录：

- `src/arb/market/`
- `src/arb/runtime/snapshots.py`
- `src/arb/runtime/streaming.py`
- `src/arb/runtime/private_streams.py`

职责：

- 拉 ticker / orderbook / funding 快照
- 归一化 WS 事件
- 把交易所差异收口成统一的内部数据结构

这一层的输出，是后面 scanner 和 workflow 的公共输入。

---

### 3. 扫描层

目录：

- `src/arb/scanner/cost_model.py`
- `src/arb/scanner/filters.py`
- `src/arb/scanner/funding_scanner.py`
- `src/arb/runtime/realtime_scanner.py`

职责：

- 计算净 funding 收益
- 过滤掉不值得做的机会
- 选择当前可尝试的机会

这里有两个关键点：

- `FundingScanner` 只负责“机会值不值得做”
- `RealtimeScanner` 负责“周期性扫描”和“选择不与当前活跃实例冲突的机会”

---

### 4. 策略与主服务层

目录：

- `src/arb/strategy/spot_perp.py`
- `src/arb/runtime/funding_arb_service.py`

职责：

- 定义 open / hold / close / rebalance 的状态机
- 在“扫描结果”和“当前持仓状态”之间做决策

`FundingArbService` 是当前最接近实盘主程序的模块。

它做的事情是：

1. 调 `RealtimeScanner.scan_once`
2. 读取 opportunities
3. 跳过已有活跃实例
4. 调 `OpenPositionWorkflow`
5. 对已开仓实例继续评估
6. 满足关闭条件时调 `ClosePositionWorkflow`
7. 通过 `OpportunityPipeline.record_workflow_state` 落状态

---

### 5. 开平仓工作流层

目录：

- `src/arb/workflows/open_position.py`
- `src/arb/workflows/close_position.py`
- `src/arb/execution/router.py`
- `src/arb/execution/executor.py`
- `src/arb/execution/order_tracker.py`

职责：

- 把策略动作变成实际订单
- 控制 maker / taker
- 处理部分成交、超时、回滚、reduce-only

这里是资金费率套利系统里最关键的工程层。

因为策略本身不复杂，真正容易出事故的是：

- 第二条腿没跟上
- 订单超时后没有及时回滚
- 平仓失败导致裸露
- 已经 reduce-only 了还允许继续开仓

---

### 6. 仓位、风控与恢复层

目录：

- `src/arb/portfolio/`
- `src/arb/risk/`
- `src/arb/runtime/recovery.py`

职责：

- 聚合仓位和净敞口
- 识别 funding 反转、naked leg、holding timeout
- 进程重启后恢复未完成工作流
- 对账本地状态和交易所真实状态

如果你以后要做“服务崩了以后自动恢复”，这层就是入口。

---

### 7. 存储与控制平面

目录：

- `src/arb/storage/`
- `src/arb/control/`
- `src/arb/integrations/feishu/`

职责：

- 保存订单、成交、持仓、workflow_state、order_status_history
- 通过 API 暴露 positions / orders / workflows
- 通过飞书做查看、确认、取消和人工命令

当前控制层的定位很明确：

- **不直接下交易所单**
- 只发命令
- 真正执行仍然回到 workflow / execution 层

这是对的，不然后期排障会非常难。

---

## 一次运行的真实调用顺序

如果你要顺着代码往里读，建议按这个顺序追：

1. `src/arb/runtime/funding_arb_service.py`
2. `src/arb/runtime/realtime_scanner.py`
3. `src/arb/runtime/exchange_manager.py`
4. 某个具体 runtime，例如 `src/arb/runtime/binance_runtime.py`
5. `src/arb/scanner/funding_scanner.py`
6. `src/arb/workflows/open_position.py`
7. `src/arb/execution/executor.py`
8. `src/arb/execution/order_tracker.py`
9. `src/arb/workflows/close_position.py`
10. `src/arb/storage/repository.py`
11. `src/arb/control/api.py`

这样读的好处是：

- 你看到的是“系统如何运行”
- 不是“目录长什么样”

---

## 当前已经形成闭环的部分

现在已经能形成一条完整闭环：

- 扫描
- 选机会
- 开仓工作流
- 订单跟踪
- 持仓后继续扫描
- funding 反转触发平仓
- workflow 状态落库
- API / 飞书侧查看与人工确认

配套还有：

- 对账
- 重启恢复
- dry-run 脚本
- 端到端测试

---

## 当前仍然需要你自己注意的边界

虽然链路已经完整，但下面这些仍然要谨慎：

- `scripts/run_funding_arb_dry_run.py` 默认是本地 dry-run，不是实盘入口
- `FundingArbService` 当前默认按“单交易所同所 spot/perp”组织
- snapshot 到真实现货/永续双市场报价的细分还可以继续增强
- 控制 API 和飞书是控制面，不应该直接取代 workflow 层

所以更准确地说：

**这个仓库现在已经有完整的资金费率套利工程骨架和本地闭环，但距离直接稳定跑真实多所实盘，还需要你继续做环境接入和真实交易所联调。**

---

## 以后改功能该从哪一层下手

### 想改机会筛选

先看：

- `src/arb/scanner/funding_scanner.py`
- `src/arb/scanner/filters.py`
- `src/arb/scanner/cost_model.py`

### 想改开平仓规则

先看：

- `src/arb/strategy/spot_perp.py`
- `src/arb/workflows/open_position.py`
- `src/arb/workflows/close_position.py`

### 想改成交跟踪和回滚

先看：

- `src/arb/execution/order_tracker.py`
- `src/arb/execution/executor.py`

### 想改人工控制

先看：

- `src/arb/control/api.py`
- `src/arb/control/dispatcher.py`
- `src/arb/integrations/feishu/cards.py`
- `src/arb/integrations/feishu/events.py`

### 想做崩溃恢复和对账

先看：

- `src/arb/runtime/recovery.py`
- `src/arb/portfolio/reconciler.py`
- `src/arb/storage/repository.py`

---

## 最后一个建议

以后你再分析这个项目，不要再从 `cli.py` 开始猜。

当前更值得当成“业务入口”的是：

- `FundingArbService`
- `RealtimeScanner`
- `OpenPositionWorkflow`
- `ClosePositionWorkflow`

`cli.py` 现在仍然只是一个命令分发壳，不是整个资金费率套利系统的真正组装入口。

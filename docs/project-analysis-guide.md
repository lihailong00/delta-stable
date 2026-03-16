# 如何分析这个项目

这份文档不是在解释“资金费率套利是什么”，而是在告诉你：面对这个仓库，你应该用什么顺序去看，才能尽快建立完整心智模型，并且知道以后要改功能该去哪里下手。

如果你只是顺着目录一个个点文件，很容易迷路。这个项目更适合按“分层 + 数据流 + 控制流”的方式来读。

---

## 先建立一个总认识

这个仓库当前是一个**模块化的套利系统骨架**，不是一个已经全部串成线上实盘服务的单体程序。

它已经把核心能力拆出来了：

1. 交易所接入
2. 行情采集和标准化
3. 机会扫描
4. 策略决策
5. 执行与回滚
6. 仓位资金管理
7. 风控
8. 持久化、PnL、监控、回测
9. 控制平面和飞书交互

所以你在分析时，不应该问“主程序从哪开始跑”，而应该问：

- 数据是怎么从交易所进来的？
- 中间怎么被标准化？
- 怎么变成策略决策？
- 决策怎么变成执行动作？
- 执行后怎么被风控、存储、监控和人工控制接住？

---

## 推荐阅读顺序

### 第 1 步：先看顶层说明和任务台账

先看这两个位置：

- `README.md`
- `current_tasks/`

你要从这一步得到两个信息：

- 这个项目打算覆盖哪些能力
- 当前每一层的文件边界是怎么拆的

`README.md` 解决“这个项目是什么”。  
`current_tasks/` 解决“这个项目为什么会长成现在这样”。

如果你以后要判断某个模块是不是“设计出来但还没真正接实盘”，看 `current_tasks` 会很快。

---

### 第 2 步：看最底层的公共约定

先看这些文件：

- `src/arb/models.py`
- `src/arb/config.py`
- `src/arb/errors.py`
- `src/arb/utils/symbols.py`

这一层决定了全项目的“基本语言”。

你要重点看：

- `Ticker`、`OrderBook`、`FundingRate`、`Order`、`Position`
- `MarketType`、`Side`、`OrderStatus`、`PositionDirection`
- 符号标准化规则，比如 `BTCUSDT`、`BTC-USDT`、`BTC_USDT` 最后都会收敛成什么

为什么这一步重要：

- 后面所有交易所适配器都要把自己的原始返回值，落到这些统一模型上
- 后面所有策略、执行、风控逻辑都默认你已经理解这些统一字段

如果你没先看这一层，后面看具体模块时会一直分不清“这是交易所特有字段”还是“系统内部统一字段”。

---

### 第 3 步：看抽象层，再看具体交易所

先看：

- `src/arb/exchange/base.py`
- `src/arb/ws/base.py`

再看：

- `src/arb/exchange/binance.py`
- `src/arb/exchange/okx.py`
- `src/arb/exchange/bybit.py`
- `src/arb/exchange/gate.py`
- `src/arb/ws/binance.py`
- `src/arb/ws/okx.py`
- `src/arb/ws/bybit.py`
- `src/arb/ws/gate.py`

你在这一层要回答的问题是：

1. 统一 REST 抽象要求交易所适配器必须实现哪些能力？
2. 各家交易所的签名、路径、符号映射差异怎么被包住？
3. WS 原始消息怎么被转换成统一事件？

建议读法：

- 先看 `base.py` 里的抽象方法名
- 再选一个最熟悉的交易所，比如 `binance.py`
- 最后对比 `okx.py` / `bybit.py` / `gate.py`

这样你会看出这个项目的真正意图不是“写四份完全不同的交易所代码”，而是“用统一接口包住交易所差异”。

---

### 第 4 步：看数据流怎么进入系统

看这几个文件：

- `src/arb/market/collector.py`
- `src/arb/market/normalizer.py`
- `src/arb/market/router.py`

这一层是“市场数据入口”。

你要重点理解：

- 快照数据怎么采集
- ticker / orderbook / funding 怎么变成统一结构
- WS 事件怎么被路由出去

你可以把这一层理解成“总线”：

- 交易所模块负责把外部世界接进来
- `market/` 负责把数据整理成内部可消费格式
- 后面的 scanner、strategy、monitoring 都依赖这里

如果你以后要接入真实网络客户端，通常会从这一层开始串第一个可运行链路。

---

### 第 5 步：看机会扫描，不要先看策略

看：

- `src/arb/scanner/cost_model.py`
- `src/arb/scanner/filters.py`
- `src/arb/scanner/funding_scanner.py`

为什么先看 scanner：

- scanner 解决的是“值不值得做”
- strategy 解决的是“什么时候开、什么时候平、什么时候再平衡”

如果你先看 strategy，很容易把“开仓规则”和“净收益估算”混在一起。

这一层你要抓住三个问题：

1. gross funding 是怎么扣掉手续费、滑点、借币和转账成本的？
2. 流动性、白名单、黑名单是怎么过滤的？
3. 最终机会是按什么排序的？

---

### 第 6 步：看策略层，理解决策是怎么形成的

看：

- `src/arb/strategy/spot_perp.py`
- `src/arb/strategy/perp_spread.py`
- `src/arb/strategy/engine.py`

这里建议不要逐行看，先抓“状态机”。

这个项目里的策略逻辑本质上是四种动作：

- `OPEN`
- `HOLD`
- `CLOSE`
- `REBALANCE`

也就是说，它不是一个“无限自由”的策略系统，而是一个很明确的仓位状态机。

你要重点看：

- 开仓条件
- 平仓条件
- 对冲比例怎么计算
- 什么情况下触发再平衡

当你理解了这一层，你就会知道：

- scanner 给的是候选机会
- strategy 给的是动作建议

这两层职责是分开的。

---

### 第 7 步：看执行、仓位和风控，这三层要一起看

按这个顺序看：

- `src/arb/execution/`
- `src/arb/portfolio/`
- `src/arb/risk/`

原因很简单：

- 执行层负责“怎么下”
- 组合层负责“下完以后系统里怎么看仓位和资金”
- 风控层负责“哪些动作根本不该下，哪些仓位必须立刻处理”

重点看这些概念：

#### 执行层

- 双腿联动
- 部分成交补单
- 第二条腿失败时的回滚
- maker / taker 路由
- 下单前校验

#### 组合层

- 原始仓位怎么聚合成净敞口
- 可用保证金怎么计算
- 单币、单所、组合级资金限制怎么分配

#### 风控层

- 爆仓距离
- 基差异常
- funding 反转
- 裸腿风险
- kill switch / reduce only

你真正想理解这个项目是否“能做实盘”，关键就在这三层，而不是在交易所适配器本身。

---

### 第 8 步：看“系统会不会失控”

这一部分看：

- `src/arb/storage/`
- `src/arb/pnl/`
- `src/arb/monitoring/`
- `src/arb/backtest/`

这四层分别回答：

- 数据是否能落下来
- 收益是否能解释清楚
- 系统异常能不能被发现
- 参数改动前有没有历史验证手段

如果你是站在“项目 owner”的角度看代码，这一层和策略层一样重要。

很多套利项目不是死在“策略不赚钱”，而是死在：

- 出问题没日志
- 盈亏归因说不清
- 没法复盘
- 没有回测基准

---

### 第 9 步：最后再看控制平面和飞书

看：

- `src/arb/control/`
- `src/arb/integrations/feishu/`

这里不是交易主逻辑，而是“运维和人工干预入口”。

你要重点看：

- API 怎么查仓位和策略状态
- 人工命令怎么入队
- 幂等怎么保证
- 敏感操作怎么二次确认
- 审计日志怎么留
- 飞书卡片只是展示层还是直接触发执行

正确理解是：

- 飞书不是交易核心
- 飞书是控制平面入口
- 真正的下单仍然应该经过 command dispatcher 和执行层

如果你以后要接“手动平仓”“暂停策略”“只减仓”这类操作，这一层就是你应该改的地方。

---

## 最好的分析方法：用测试反推设计

这个仓库最适合“边看实现，边看对应测试”。

推荐一一对应地看：

- `src/arb/exchange/` 对应 `tests/test_exchange/`
- `src/arb/ws/` 对应 `tests/test_ws/`
- `src/arb/market/` 对应 `tests/test_market/`
- `src/arb/scanner/` 对应 `tests/test_scanner/`
- `src/arb/strategy/` 对应 `tests/test_strategy/`
- `src/arb/execution/` 对应 `tests/test_execution/`
- `src/arb/portfolio/` 对应 `tests/test_portfolio/`
- `src/arb/risk/` 对应 `tests/test_risk/`
- `src/arb/storage/` 对应 `tests/test_storage/`
- `src/arb/pnl/` 对应 `tests/test_pnl/`
- `src/arb/monitoring/` 对应 `tests/test_monitoring/`
- `src/arb/backtest/` 对应 `tests/test_backtest/`
- `src/arb/control/` 对应 `tests/test_control/`
- `src/arb/integrations/feishu/` 对应 `tests/test_integrations/`

为什么这样看最快：

- 测试会直接告诉你“作者认为这个模块应该怎么用”
- 测试比实现更容易看出边界条件
- 你改代码时也能第一时间知道是不是改坏了行为

---

## 你可以按这 3 条主线分析

### 主线一：从市场到下单

按这个顺序看：

1. `exchange/` 和 `ws/`
2. `market/`
3. `scanner/`
4. `strategy/`
5. `execution/`
6. `risk/`
7. `portfolio/`

这是“交易主链路”。

---

### 主线二：从下单到复盘

按这个顺序看：

1. `execution/`
2. `storage/`
3. `pnl/`
4. `monitoring/`
5. `backtest/`

这是“交易后链路”。

---

### 主线三：从人工控制到命令落地

按这个顺序看：

1. `integrations/feishu/`
2. `control/api.py`
3. `control/dispatcher.py`
4. `control/audit.py`
5. `execution/`

这是“控制平面链路”。

---

## 如果你想改代码，应该怎么下手

### 想加一个新交易所

先看：

- `src/arb/exchange/base.py`
- 任意一个现有适配器，比如 `src/arb/exchange/binance.py`
- 对应的 `src/arb/ws/*.py`
- `tests/test_exchange/` 和 `tests/test_ws/`

不要先去改 scanner 或 strategy。

---

### 想改策略逻辑

先看：

- `src/arb/scanner/funding_scanner.py`
- `src/arb/strategy/spot_perp.py`
- `src/arb/strategy/perp_spread.py`
- `tests/test_strategy/test_strategy_engine.py`

注意把“收益估算”和“状态机动作”分开改。

---

### 想改风控

先看：

- `src/arb/risk/checks.py`
- `src/arb/risk/limits.py`
- `src/arb/risk/killswitch.py`
- `tests/test_risk/test_risk.py`

不要把风控直接塞进执行器或飞书回调里。

---

### 想接飞书手动平仓

先看：

- `src/arb/integrations/feishu/cards.py`
- `src/arb/integrations/feishu/events.py`
- `src/arb/control/api.py`
- `src/arb/control/dispatcher.py`
- `src/arb/control/audit.py`

重点不是“按钮怎么画”，而是“按钮点下去后怎么安全地进入命令分发链路”。

---

## 建议的实操分析流程

如果你今天第一次接手这个项目，我建议按下面节奏：

### 30 分钟版本

1. 看 `README.md`
2. 看 `current_tasks/`
3. 看 `src/arb/models.py`
4. 看 `src/arb/exchange/base.py`、`src/arb/ws/base.py`
5. 看 `src/arb/market/collector.py`
6. 看 `src/arb/scanner/funding_scanner.py`
7. 看 `src/arb/strategy/engine.py`
8. 看 `src/arb/execution/executor.py`

目标：知道主链路怎么走。

### 2 小时版本

在上面的基础上继续看：

1. 各家交易所适配器
2. `portfolio/`
3. `risk/`
4. `storage/`
5. `pnl/`
6. `monitoring/`
7. `control/`
8. `integrations/feishu/`
9. 对应全部测试

目标：知道每层边界和可改动点。

### 真正准备动手改功能

建议固定动作：

1. 先找对应模块的测试
2. 再读实现
3. 确认改动会影响哪条链路
4. 只在这一层改，不要一上来跨层乱改
5. 改完跑全量测试

---

## 读这个项目时最容易犯的错

### 1. 把它当成一个完整实盘服务去找“main”

不是。它现在更像一套已经拆好的系统部件。

### 2. 先看飞书或控制 API

这会让你误以为“人工操作入口”是核心。  
真正核心还是市场数据、扫描、策略、执行、风控。

### 3. 直接看具体交易所实现，不先看统一模型

这样你会陷在 API 细节里，看不出项目结构。

### 4. 不看测试

这个仓库的测试就是最好的行为说明书。

---

## 一条最重要的结论

如果你只记住一句话，那就是：

**分析这个项目时，要先看“统一抽象和数据流”，再看“具体交易所和控制入口”。**

顺序反了，你会觉得这个项目很碎；顺序对了，你会发现它其实就是一条很清楚的链：

**交易所 -> 市场数据 -> 扫描 -> 策略 -> 执行 -> 风控/仓位 -> 存储/PnL/监控 -> 控制平面/飞书**

当你能把这条链在脑子里顺一遍时，这个项目你就算真正看懂了。

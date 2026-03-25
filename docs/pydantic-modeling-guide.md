# Pydantic Modeling Guide

## 目标

这份文档现在同时覆盖两件事：

- 项目里的 Pydantic 建模约束
- 类型门禁和本地检查方式

不再单独拆一份类型检查文档。

## 默认基类

- 不可变领域对象：`ArbFrozenModel`
- 可变服务状态对象：`ArbModel`

两者都默认：

- `extra="forbid"`
- 显式字段定义
- 允许统一 `to_dict()`

对应实现见 [base.py](/home/longcoding/dev/project/delta_stable/src/arb/schemas/base.py)。

## 什么地方必须建模

- 领域对象：订单、仓位、PnL、风控状态
- API / command 输入输出
- runtime / workflow / storage 的跨模块边界
- transport 层的请求与响应边界

只有在最外层交易所原始 JSON 边界，才允许短暂保留原始 mapping。

## 建模时的默认原则

- 不新增 `dict[str, Any]`、`list[dict[str, Any]]` 作为主链返回值
- 不把原始交易所字段名一路传到业务层
- 一旦某个结构被两个模块以上共享，就升成模型
- 如果一个对象需要被修改，才用可变模型；否则优先不可变模型

## 与 transport 层的关系

- `src/arb/schemas/base.py` 负责业务模型
- `src/typed_transport/types.py` 负责通用 transport 模型
- `src/arb/net/schemas.py` 目前只保留兼容字段，例如交易所侧还在使用的 `market_type`、`signed`

业务模型不要直接依赖交易所原始请求/响应字段。

## 本地类型门禁

推荐最少跑这两步：

```bash
uv run pytest -q
uv run mypy src
```

如果你只改了局部模块，也至少要保证对应测试和受影响的 mypy 范围能通过。

## 什么时候该补类型

- 新增公共 schema
- 把某段 `dict` 逻辑抽成共享组件
- 从一个模块把数据交给另一个模块
- 给 transport / storage / control 新增边界

如果你发现一个接口已经开始写字段文档、写字段约定、写示例 payload，通常就该建模了。

## 什么时候不要过度建模

- 单个函数内部、只用一次的临时变量
- 紧贴交易所原始响应、马上就会被 normalize 的中间数据
- 只在测试里临时拼的最小 fake payload

原则是：边界显式，内部适度。

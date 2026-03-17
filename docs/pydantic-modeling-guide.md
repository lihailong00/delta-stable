# Pydantic Modeling Guide

这个仓库后续的类型收敛，统一按下面几条执行。

## 目标

- 模块边界都用显式 `BaseModel`
- 主链上不再新增 `dict[str, Any]`、`list[dict[str, Any]]`、`Any`
- 原始交易所 JSON 只允许停留在最外层协议边界

## 默认基类

- 不可变领域对象：`ArbFrozenModel`
- 可变服务状态对象：`ArbModel`

两者都默认：

- `extra="forbid"`
- 明确字段定义
- 支持统一 `to_dict()`

## 必须用模型的边界

- 市场快照
- WS 标准化事件
- scanner 输出
- workflow 状态
- 控制 API 请求/响应
- 飞书回调和卡片数据
- CLI 和 bootstrap 的对外配置对象

## 可以保留原始映射的边界

- 交易所 REST/WS 收到的最原始 JSON
- 网络层 connector 的极薄适配接口

这些原始载荷一旦进入系统，必须尽快转成模型。

## 禁止项

- 新增 `Any` 作为 service、runtime、control 主链参数或返回值
- 用 `dict[str, str]` 表示其实已经有固定字段的业务对象
- 在测试里用松散 dict 伪造复杂业务对象，而不是使用工厂或显式模型

## 迁移原则

1. 先定义模型，再迁移调用点
2. 兼容层只作为过渡，不长期保留
3. 优先收紧主链，再处理边角模块

## 配套检查

- 建模规范看这里
- 类型门禁和本地/CI 检查命令看 [type-checking-guide.md](/home/longcoding/dev/project/delta_stable/docs/type-checking-guide.md)

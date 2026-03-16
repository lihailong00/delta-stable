# Runtime Composition Guide

## 为什么 runtime 使用组合而不是继承

`src/arb/runtime/` 下的六个交易所 runtime 看起来结构很像，但它们并不是一个适合深继承的稳定层级。

共同点只有这些：

- 都要 `public_ping`
- 都要 `validate_private_access`
- 都要 `fetch_public_snapshot`
- 都可能暴露若干 `stream_*`

真正的差异却很多：

- 有的只有 public WS，有的有 public/private 两套 WS
- 有的是 `login`，有的是 `auth`
- 有的主要订阅 `orderbook`，有的还需要 `ticker`、`funding`
- endpoint、订阅 payload、private 会话流程都不一样

如果把这些差异塞进一个 `BaseRuntime`，最后通常会演变成：

- 父类里大量模板方法
- 很多 hook
- 大量 `if exchange == ...`
- 很难单独测试 WS/public/private 各段逻辑

所以当前设计改成了“薄协议 + 组合 helper”。

## 现在的分层

### 1. 协议层

见 [protocols.py](/home/longcoding/dev/project/delta_stable/src/arb/runtime/protocols.py)：

- `SnapshotRuntimeProtocol`
- `SmokeRuntimeProtocol`
- `LiveRuntimeProtocol`

上层编排层只依赖协议，不依赖具体交易所类。

### 2. 组合 helper

见：

- [snapshots.py](/home/longcoding/dev/project/delta_stable/src/arb/runtime/snapshots.py)
- [streaming.py](/home/longcoding/dev/project/delta_stable/src/arb/runtime/streaming.py)

这里把公共重复逻辑拆出来：

- `SnapshotService`
- `PublicStreamService`
- `PrivateSessionService`

### 3. 交易所 runtime

交易所 runtime 现在只负责“装配”：

- 绑定 exchange adapter
- 绑定 WS client
- 绑定 snapshot helper
- 绑定 public/private WS helper
- 暴露交易所特有的方法名，比如 `build_private_login_message`

也就是说，runtime 现在更像 facade，而不是逻辑密集的父类子类体系。

## 这种结构的好处

- 更容易扩展新交易所
- 更容易单测 helper，而不是每次都测整套 runtime
- 上层只依赖协议，替换实现更轻
- 某个交易所 private WS 流程变化时，只需要改装配和该交易所 client

## 什么时候才适合继承

只有在这些条件同时成立时，才值得引入更重的继承：

- 大部分 runtime 的方法名和参数都稳定一致
- public/private WS 流程差异很小
- 父类抽象出的模板方法不会出现大量特例分支

当前这个项目还没到那个阶段，所以组合更稳。

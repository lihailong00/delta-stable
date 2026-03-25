# typed-transport Guide

## 这份文档负责什么

这份文档合并了原来的：

- 使用手册
- 抽离/打包说明

它只回答 3 个问题：

1. `typed_transport` 提供什么能力
2. 当前仓库怎么使用它
3. 如果以后要独立打包，需要遵守什么边界

## 它解决什么问题

`typed_transport` 不是新的底层 HTTP/WS 库。它建立在 `httpx` 和 `websockets` 之上，提供：

- 统一 HTTP 请求模型
- 统一错误模型
- retry / timeout / rate limit / signer 扩展点
- 带重连和订阅恢复的 WebSocket 会话

公开核心能力保持很薄：

- `HttpTransport`
- `AsyncRateLimiter`
- `WebSocketSession`
- `HttpRequest`
- transport errors

## 当前仓库里的关系

当前代码里有两层：

- `src/typed_transport/`: 通用 transport 能力
- `src/arb/net/`: 兼容层

其中：

- `arb.net.http` / `arb.net.ws` / `arb.net.errors` 基本已经是 re-export
- `arb.net.schemas` 仍保留了交易所适配器需要的兼容字段，例如 `market_type`、`signed`

这意味着 transport 正在迁移，但还没有完全退役 `arb.net`。

## 在项目里怎么用

### 通用 transport

适合直接看：

- `src/typed_transport/http.py`
- `src/typed_transport/ws.py`
- `src/typed_transport/types.py`

### 业务项目里的兼容入口

如果你在 `arb` 业务层改代码，短期内仍可能看到：

- `arb.net.http`
- `arb.net.ws`
- `arb.net.schemas`

这不是新的设计目标，而是为了避免一次性改掉所有导入。

## 以后继续收口时的原则

- 内部代码优先直接依赖 `typed_transport`
- `arb.net` 只保留必要兼容层，不新增新能力
- transport 包不要依赖 `arb` 的业务模型、工作流、交易所协议
- 如果某个能力只服务具体业务，就留在 `arb`，不要塞回 `typed_transport`

## 如果以后独立打包

当前仓库里已经有对应的包骨架：

- `src/typed_transport/`
- `packages/typed-transport/`

独立打包时要守住几个边界：

- 不依赖 `arb.schemas.base`
- 不依赖 `arb.ws.schemas`
- 不引入具体交易所逻辑
- 只保留 transport 抽象、请求模型、错误模型和基础会话能力

## 当前判断

`typed_transport` 已经适合作为独立子包继续收敛，但在主仓库里还处在“兼容层并存”的阶段。

所以现在最合理的做法不是继续扩展 `arb.net`，而是逐步把内部调用迁到 `typed_transport`，最后再删掉 `arb.net` 的剩余兼容页。

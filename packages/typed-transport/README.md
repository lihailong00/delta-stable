# typed-transport

`typed-transport` 是一个很薄的异步网络封装层，定位不是替代 `httpx` / `websockets`，而是在它们之上提供更稳定的项目级 transport 抽象。

## 安装

```bash
pip install typed-transport
```

## 提供的能力

- `HttpTransport`
  - 统一 `HttpRequest`
  - 超时、重试、signer、rate limiter
  - `request_json()` / `request_text()` / `request_bytes()` / `request_raw()`
- `WebSocketSession`
  - 连接、重连、订阅恢复
  - 可插拔 connector
- 显式错误类型
  - `NetworkError`
  - `HttpStatusError`
  - `WebSocketClosedError`

## 适合的场景

- REST / JSON API 适配器
- 机器人/服务端对多个 API 的统一调用
- 需要 fake client / 假 websocket 做测试注入的项目

## 不适合的场景

- 想直接替代底层 HTTP/WS 客户端
- 需要完整 streaming HTTP、multipart、高级连接池定制但不想接触底层库

## 示例

```python
from typed_transport import HttpRequest, HttpTransport

transport = HttpTransport()
payload = await transport.request_json(
    HttpRequest(method="GET", url="https://example.com/api/ping")
)
```

```python
from typed_transport import WebSocketSession

session = WebSocketSession("wss://example.com/ws")
session.add_subscription({"op": "subscribe", "channel": "ticker"})
messages = await session.run_forever(max_messages=1)
```

包内还带了两个离线可运行示例：

- `packages/typed-transport/examples/http_json_request.py`
- `packages/typed-transport/examples/websocket_reconnect.py`

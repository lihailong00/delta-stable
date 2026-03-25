# typed_transport Usage

这份手册放在源码目录里，目的是让你打开 `src/typed_transport/` 时，不用先跳转到别的文档，就能知道这个库怎么用。

## 这个库是什么

`typed_transport` 是一个很薄的异步 transport 封装层，建立在 `httpx` 和 `websockets` 之上。

它负责：

- HTTP 请求发送
- 超时、重试、限频
- WebSocket 连接、重连、订阅恢复
- 统一错误类型
- 方便 fake client / fake websocket 测试注入

它不负责：

- 某个具体 API 的路径和参数约定
- 某个具体服务的鉴权或签名细节
- 业务协议解析
- 上层应用工作流

## 核心 API

最常用的入口在 `__init__.py`：

- `HttpRequest`
- `HttpTransport`
- `AsyncRateLimiter`
- `WebSocketSession`
- `NetworkError`
- `HttpStatusError`
- `WebSocketClosedError`

## 最简单的 HTTP 用法

```python
from typed_transport import HttpRequest, HttpTransport


async def main() -> None:
    transport = HttpTransport()
    payload = await transport.request_json(
        HttpRequest(
            method="GET",
            url="https://example.com/api/ping",
            headers={"X-App": "demo"},
            params={"limit": 10},
        )
    )
    print(payload)
    await transport.aclose()
```

也可以直接传一个字典：

```python
payload = await transport.request_json(
    {
        "method": "GET",
        "url": "https://example.com/api/ping",
        "params": {"limit": 10},
    }
)
```

## HTTP 可用接口

- `request()`：默认等价于 `request_json()`
- `request_json()`
- `request_text()`
- `request_bytes()`
- `request_raw()`
- `aclose()`

## HTTP 常见扩展点

### 1. 超时和重试

```python
transport = HttpTransport(timeout=5.0, retries=2)
```

### 2. 限频

```python
from typed_transport import AsyncRateLimiter, HttpTransport

limiter = AsyncRateLimiter(requests_per_second=5)
transport = HttpTransport(rate_limiter=limiter)
```

### 3. signer

适合在发送前统一补 header、query 或鉴权信息。

```python
from typed_transport import HttpRequest, HttpTransport


def signer(request: HttpRequest) -> HttpRequest:
    headers = dict(request.headers)
    headers["X-API-KEY"] = "demo-key"
    return request.model_copy(update={"headers": headers})


transport = HttpTransport(signer=signer)
```

### 4. 注入自定义 client

```python
class MyClient:
    async def request(self, method: str, url: str, **kwargs: object) -> object:
        ...

    async def aclose(self) -> None:
        ...


transport = HttpTransport(client=MyClient())
```

## 最简单的 WebSocket 用法

```python
from typed_transport import WebSocketSession


async def main() -> None:
    session = WebSocketSession("wss://example.com/ws")
    session.add_subscription({"op": "subscribe", "channel": "ticker"})
    messages = await session.run_forever(max_messages=1)
    print(messages)
    await session.aclose()
```

## WebSocket 设计重点

- `add_subscription()` 保存订阅消息
- `connect()` 时会自动重发这些订阅
- `run_forever()` 遇到断开后会重连
- `connector` 可注入，方便测试

## 错误处理

常见错误类型定义在 `errors.py`：

- `NetworkError`
- `HttpStatusError`
- `WebSocketClosedError`

示例：

```python
from typed_transport import HttpStatusError, NetworkError

try:
    payload = await transport.request_json({"method": "GET", "url": "https://example.com"})
except HttpStatusError as exc:
    print(exc.status_code, exc.message)
except NetworkError as exc:
    print(str(exc))
```

## 推荐接入方式

推荐分层如下：

- `typed_transport`
  - 负责网络传输
- `your_project.client_layer.*`
  - 负责路径、签名、参数和解析
- `your_project.service_layer.*`
  - 负责业务流程和编排

不要把某个具体产品 API 的路径、鉴权和业务解析直接写进 `typed_transport`。

## 测试方式

这个库的设计目标之一就是易测试。

参考：

- `tests/test_typed_transport/test_http_transport.py`
- `tests/test_typed_transport/test_ws_transport.py`
- `tests/test_typed_transport/test_types.py`

推荐策略：

- HTTP 测试用 fake client
- WebSocket 测试用 fake connector
- 尽量不要在单测里依赖公网

## 离线示例

包级离线示例在：

- `packages/typed-transport/examples/http_json_request.py`
- `packages/typed-transport/examples/websocket_reconnect.py`

运行：

```bash
PYTHONPATH=src uv run --no-sync python packages/typed-transport/examples/http_json_request.py
PYTHONPATH=src uv run --no-sync python packages/typed-transport/examples/websocket_reconnect.py
```

## 如果你要把它单独拆出去

至少迁移这几块：

- `src/typed_transport/`
- `packages/typed-transport/`
- `tests/test_typed_transport/`

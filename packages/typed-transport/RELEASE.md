# Release Checklist

## 发布前

1. 检查 `LICENSE`、`README.md`、`pyproject.toml` 里的包名和仓库链接是否一致。
2. 确认 GitHub 仓库地址与 `project.urls` 一致。
3. 运行：

```bash
PYTHONPATH=src:. UV_CACHE_DIR=.uv-cache uv run --no-sync pytest -q tests/test_typed_transport tests/test_net
PYTHONPATH=src UV_CACHE_DIR=.uv-cache uv run --no-sync mypy src/typed_transport
uv build packages/typed-transport --out-dir dist/typed-transport
PYTHONPATH=src uv run --no-sync python packages/typed-transport/examples/http_json_request.py
PYTHONPATH=src uv run --no-sync python packages/typed-transport/examples/websocket_reconnect.py
```

4. 检查产物：

- `*.whl`
- `*.tar.gz`

## 发布到 GitHub

1. 把 `packages/typed-transport/`、`src/typed_transport/` 和测试拆到独立仓库。
2. 保留 `src/arb/net/` 兼容层，或在主仓库中改为依赖 PyPI 版本。

## 发布到 PyPI

1. 先上传到 TestPyPI
2. 验证安装：

```bash
pip install -i https://test.pypi.org/simple typed-transport
```

3. 验证示例
4. 再上传正式 PyPI

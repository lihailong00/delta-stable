# Type Checking Guide

这个文档补的是“怎么把 Pydantic 约束变成可执行门禁”，不是重复讲模型规范本身。建模规范先看 [pydantic-modeling-guide.md](/home/longcoding/dev/project/delta_stable/docs/pydantic-modeling-guide.md)。

## 当前门禁范围

当前 `mypy` 先收紧这些已经完成 Pydantic 化的边界模块：

- `src/arb/schemas`
- `src/arb/bootstrap/schemas.py`
- `src/arb/control/schemas.py`
- `src/arb/integrations/feishu/schemas.py`
- `src/arb/market/schemas.py`
- `src/arb/net/schemas.py`
- `src/arb/ws/schemas.py`
- `tests/factories`

这是第一阶段门禁，不是全仓库一次性 `strict`。原因很简单：主链边界必须先稳定，旧模块再逐步迁移。

## 本地怎么跑

先安装开发依赖：

```bash
uv sync --group dev
```

本地最小检查命令：

```bash
PYTHONPATH=src UV_CACHE_DIR=.uv-cache uv run mypy
PYTHONPATH=src:. UV_CACHE_DIR=.uv-cache uv run pytest -q
```

如果你只改了某一层，优先跑对应子集；但提交前至少跑一次 `mypy` 门禁范围。

## 当前规则

`pyproject.toml` 里的 `mypy` 规则当前重点是：

- `disallow_untyped_defs = true`
- `disallow_any_generics = true`
- `warn_return_any = true`
- `no_implicit_optional = true`
- `strict_equality = true`

这套规则的目标不是把整个仓库立刻变成“零历史负债”，而是防止主链再新增新的松散边界。

## 新代码要求

新增代码如果落在上述门禁范围内，按下面执行：

- 不新增 `Any` 作为对外参数、返回值、状态字段
- 不用 `dict[str, str]` 或 `dict[str, object]` 伪装固定结构
- 原始交易所 JSON 只能停留在适配器最外层
- 进入系统主链前，必须转成 `ArbModel` / `ArbFrozenModel`
- 测试里优先用工厂和显式模型，不要手搓松散嵌套字典

## 例外边界

这些地方允许暂时保留更宽的类型，但必须局限在边界层：

- 第三方库原始返回值
- 交易所私有协议里还没标准化完成的载荷
- 兼容旧接口的过渡适配层

一旦这些值进入 service、scanner、control、bootstrap 主链，就必须收口成明确模型。

## 逐步迁移顺序

推荐顺序：

1. 先补 schema
2. 再改模块签名
3. 再删兼容字典
4. 最后把该模块加入 `mypy` 门禁范围

不要反过来做。先开严格门禁、后补模型，只会让重构变慢。

## CI 建议

如果你把这套仓库接进 CI，优先加这两步：

```bash
PYTHONPATH=src UV_CACHE_DIR=.uv-cache uv run mypy
PYTHONPATH=src:. UV_CACHE_DIR=.uv-cache uv run pytest -q
```

建议先只对当前门禁范围执行 `mypy`，等更多模块完成迁移后，再逐步扩大 `files` 列表。

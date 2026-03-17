# Live Exchange Onboarding

## Goal

这份文档用于把项目从“协议与 mock 测试”推进到“真实交易所 dry-run 连通”。首版目标只有 3 个：

- 验证公共 REST/WS 能连通
- 验证私有账户鉴权正常
- 在不下真实单的前提下跑出实时 funding 扫描结果

不要在未完成这些检查前直接接入自动执行。

## 支持的交易所

- Binance
- OKX
- Bybit
- Gate
- Bitget
- HTX

## 建议接通顺序

1. 先接 `Binance` 或 `OKX`
2. 再接 `Bybit`
3. 再补 `Gate / Bitget / HTX`
4. 最后开启多交易所并行扫描

原因很简单：越早接入 API 稳定、文档稳定的交易所，越容易把 transport、限频、错误处理先打磨出来。

## 环境变量

至少准备以下几类变量：

- `*_KEY`
- `*_SECRET`
- `*_PASSPHRASE`：仅 OKX / Bitget 这类需要 passphrase 的交易所
- `ARB_LIVE_ENABLED=true`
- `ARB_READ_ONLY=true`
- `ARB_USE_TESTNET=true`：如果交易所支持 testnet，先开 testnet

建议一所一组，例如：

```bash
export BINANCE_KEY=...
export BINANCE_SECRET=...
export OKX_KEY=...
export OKX_SECRET=...
export OKX_PASSPHRASE=...
export ARB_LIVE_ENABLED=true
export ARB_READ_ONLY=true
```

## 首次接通步骤

1. 先跑公共 smoke，确认公网 REST 正常
2. 再跑私有 smoke，确认签名和权限正常
3. 再跑 `live-scan --dry-run`，确认扫描链路完整
4. 再跑 `run_funding_arb_dry_run.py`，确认主服务开平仓闭环
5. 最后才考虑接真实执行

推荐命令形态：

```bash
uv run arb smoke --exchange binance okx
uv run arb smoke --exchange binance --private
uv run arb live-scan --exchange binance okx --symbol BTC/USDT ETH/USDT --dry-run --iterations 3
PYTHONPATH=src uv run python scripts/run_funding_arb_dry_run.py --exchange binance --symbol BTC/USDT --iterations 3 --funding-sequence 0.001 0.0008 -0.0002
```

## 风控建议

- 默认开启 `read-only`
- 默认只跑 `dry-run`
- 默认只看 `BTC/USDT`、`ETH/USDT`
- 默认只接 `1-2` 家交易所
- 所有私有 API key 都使用最小权限
- 禁止在未验证时间同步前直接下单

## 排查顺序

如果真实接通失败，按这个顺序查：

1. DNS / 代理 / 防火墙
2. API base URL 和 WS URL
3. 本机时间是否同步
4. 签名字段和 header/query 是否匹配
5. 账户权限是否缺失
6. 交易所是否开启了 IP 白名单
7. 是否误把 testnet key 用在 live 域名

## 当前边界

当前仓库已经有：

- 真实 HTTP / WS transport
- 六家交易所的 REST / WS 协议适配
- 各交易所 live runtime
- 多交易所实时扫描运行时
- smoke runner 与 CLI 命令入口

当前仍建议你保持：

- 不自动下单
- 不自动划转
- 不自动做跨所资金调度
- 先用控制 API / 飞书做人工接管

先把连通性、稳定性、日志、告警跑顺，再进入实盘执行。

# Polo Adapter

独立部署的 Polo 兼容适配服务，面向主服务 `Sora2Api` 暴露：

- `POST /videos`
- `GET /videos/generations/{id}`

运行时只依赖两件事：

- HTTP 调用主服务 `POST /v1/chat/completions`
- 只读查询共享 SQLite 数据库

## 目录

- `polo_adapter/app/`: 适配服务代码
- `polo_adapter/tests/`: 适配服务测试
- `polo_adapter/.env.example`: 环境变量示例

## 配置

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `POLO_SHARED_API_KEY` | `han1234` | 与主服务共用的固定 Bearer |
| `POLO_MAIN_BASE_URL` | `http://127.0.0.1:8000` | 主服务地址 |
| `POLO_DB_PATH` | `data/hancat.db` | 共享主库或只读副本路径 |
| `POLO_ADAPTER_HOST` | `0.0.0.0` | 适配服务监听地址 |
| `POLO_ADAPTER_PORT` | `8010` | 适配服务监听端口 |
| `POLO_CREATE_TIMEOUT_SECONDS` | `5` | 抢首个 `task_id` 的超时时间 |
| `POLO_IMAGE_DOWNLOAD_TIMEOUT_SECONDS` | `10` | 远程图片下载超时 |
| `POLO_IMAGE_MAX_BYTES` | `10485760` | 远程图片大小上限 |
| `POLO_IMAGE_MAX_REDIRECTS` | `3` | 远程图片最大重定向次数 |
| `POLO_MAIN_LOCAL_TZ` | `Asia/Shanghai` | 主服务本地时区，用于解析 `completed_at` |

## 启动

```bash
pip install -r polo_adapter/requirements.txt
python -m polo_adapter.app.main
```

服务启动时会只读检查 `admin_config.api_key` 是否和 `POLO_SHARED_API_KEY` 一致，不一致会直接拒绝启动。

## 联调说明

1. 主服务正常运行，并能处理 `POST /v1/chat/completions`
2. 适配服务能读到与主服务共享的 SQLite 主库或只读副本
3. 两边使用同一个 Bearer API key

## 行为说明

- `POST /videos` 强制以 `stream=true` 调主服务，并在 5 秒内等待首个 `task_id`
- 若 5 秒内无 `task_id`，适配服务返回 `504`，但后台继续把主服务 SSE 消费到结束
- `GET /videos/generations/{id}` 只按 `task_id` 精确查库，`tasks` 是状态真源，`request_logs` 仅补充诊断

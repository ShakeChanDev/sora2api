# Polo Adapter

独立部署的 Polo 兼容适配服务。该服务只通过两种方式依赖主服务：

- `POST /v1/chat/completions`
- 只读查询共享 SQLite 数据库

## API

- `POST /videos`
- `GET /videos/generations/{task_id}`

## 环境变量

必填：

- `POLO_ADAPTER_API_KEY`
- `POLO_ADAPTER_MAIN_BASE_URL`

常用默认值：

- `POLO_ADAPTER_SQLITE_PATH=data/hancat.db`
- `POLO_ADAPTER_HOST=0.0.0.0`
- `POLO_ADAPTER_PORT=8100`
- `POLO_ADAPTER_TASK_ID_WAIT_SECONDS=5`
- `POLO_ADAPTER_IMAGE_TIMEOUT_SECONDS=15`
- `POLO_ADAPTER_IMAGE_MAX_BYTES=10485760`
- `POLO_ADAPTER_IMAGE_MAX_REDIRECTS=3`
- `POLO_ADAPTER_SQLITE_BUSY_TIMEOUT_MS=5000`
- `POLO_ADAPTER_MAIN_LOCAL_TZ=Asia/Shanghai`

兼容旧部署时，也支持读取旧变量名：

- `POLO_SHARED_API_KEY`
- `POLO_MAIN_BASE_URL`
- `POLO_DB_PATH`
- `POLO_CREATE_TIMEOUT_SECONDS`
- `POLO_IMAGE_DOWNLOAD_TIMEOUT_SECONDS`
- `POLO_IMAGE_MAX_BYTES`
- `POLO_IMAGE_MAX_REDIRECTS`
- `POLO_MAIN_LOCAL_TZ`

旧部署若仍需监听 `8010` 端口，请显式设置 `POLO_ADAPTER_PORT=8010`。

参考配置见 `polo_adapter/.env.example`。

## 本地运行

```bash
cd polo_adapter
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python main.py
```

## Docker 运行

```bash
docker build -t polo-adapter ./polo_adapter
docker run --rm -p 8100:8100 --env-file ./polo_adapter/.env -v ${PWD}/data:/app/data polo-adapter
```

Windows PowerShell 示例：

```powershell
docker build -t polo-adapter .\polo_adapter
docker run --rm -p 8100:8100 --env-file .\polo_adapter\.env -v ${PWD}\data:/app/data polo-adapter
```

## 共享数据库挂载

- 主服务主库默认路径：`data/hancat.db`
- 如使用只读副本，改为设置 `POLO_ADAPTER_SQLITE_PATH`
- 适配服务只会以 SQLite `mode=ro` 打开数据库

## 联调说明

1. 先启动主服务，并确认 `POST /v1/chat/completions` 可用。
2. 让适配服务的 `POLO_ADAPTER_API_KEY` 与主服务 API key 保持一致。
3. 让适配服务可读取主服务数据库文件或只读副本。
4. 适配服务启动时会校验 `admin_config.api_key` 是否与适配器 API key 一致，不一致会直接拒绝启动。
5. 调用：

```bash
curl -X POST "http://127.0.0.1:8100/videos" ^
  -H "Authorization: Bearer han1234" ^
  -H "Content-Type: application/json" ^
  -d "{\"prompt\":\"a panda walking in snow\"}"
```

查询：

```bash
curl -X GET "http://127.0.0.1:8100/videos/generations/task_xxx" ^
  -H "Authorization: Bearer han1234"
```

## 模型映射

- `sora-2-portrait-10s -> sora2-portrait-10s`
- `sora-2-landscape-10s -> sora2-landscape-10s`
- `sora-2-portrait-15s -> sora2-portrait-15s`
- `sora-2-landscape-15s -> sora2-landscape-15s`
- `sora-2-portrait-25s -> sora2-portrait-25s`
- `sora-2-landscape-25s -> sora2-landscape-25s`
- `sora-2-pro-portrait-10s -> sora2pro-portrait-10s`
- `sora-2-pro-landscape-10s -> sora2pro-landscape-10s`
- `sora-2-pro-portrait-15s -> sora2pro-portrait-15s`
- `sora-2-pro-landscape-15s -> sora2pro-landscape-15s`

默认模型：

- 外部：`sora-2-portrait-15s`
- 内部：`sora2-portrait-15s`

## 行为约束

- `style` 仅做原样透传，不保证上游生效
- `references` 先做前置只读查库校验，再原样透传给主服务顶层字段
- `image_url` 会先做公网校验、下载并转为 base64，再映射到主服务 `image`
- `GET /videos/generations/{task_id}` 中，`created_at` 按 SQLite `CURRENT_TIMESTAMP` 的 UTC 语义解析，`completed_at` 按 `POLO_ADAPTER_MAIN_LOCAL_TZ` 解析
- 创建接口会先启动后台 SSE drain，再等待首个 `task_id`
- 若在 `POLO_ADAPTER_TASK_ID_WAIT_SECONDS` 内没有拿到 `task_id`，接口返回 `504`，但后台仍会继续消费上游 SSE 到 `[DONE]`

# Sora2API 开发者文档

## 项目概述

Sora2API 是一个基于 FastAPI 的 Sora/OpenAI 兼容接口服务，入口在 `main.py` 和 `src/main.py`。它对外提供两类能力：

- OpenAI 风格接口：`GET /v1/models`、`POST /v1/chat/completions`
- 管理后台接口：`/api/*`，用于登录、Token 管理、代理与缓存配置、日志查看、任务终止等

从源码看，这个项目不是一个“纯转发网关”，而是包含了较完整的运行时能力：

- 多 Token 管理、可按图片/视频能力和 Pro 套餐筛选
- 图片/视频生成轮询、失败重试、401 自动禁用
- 文件缓存与 `tmp/` 静态回源
- 管理后台页面与嵌入式生成面板
- 代理管理、WARP 部署、外部 POW 服务接入
- SQLite 持久化和启动时数据库迁移

核心入口与初始化链路：

- `main.py`：启动脚本，调用 `uvicorn.run("src.main:app", ...)`
- `src/main.py`：创建 FastAPI 应用、注册路由、挂载静态目录、初始化数据库和调度器

## 技术栈

依赖来源以 `requirements.txt` 和容器文件为准。

### 后端与运行时

| 技术 | 版本/来源 | 说明 |
|---|---|---|
| Python | `Dockerfile` 使用 `python:3.11-slim` | 本地最低实际验证版本待确认 |
| FastAPI | `fastapi==0.119.0` | Web 框架 |
| Uvicorn | `uvicorn[standard]==0.32.1` | ASGI 服务启动 |
| Pydantic | `pydantic==2.10.4` | 请求/响应与数据模型 |
| Pydantic Settings | `pydantic-settings==2.7.0` | 已安装，但当前主配置仍由自定义 TOML 读取 |
| aiosqlite | `aiosqlite==0.20.0` | SQLite 异步访问 |
| APScheduler | `APScheduler==3.10.4` | 定时批量刷新 Token |
| curl-cffi | `curl-cffi==0.13.0` | 上游请求、代理、浏览器指纹模拟 |
| Playwright | `playwright==1.48.0` | Sentinel/POW 相关浏览器流程 |
| PyJWT | `pyjwt==2.10.1` | 解析 AT JWT |
| bcrypt | `bcrypt==4.2.1` | 鉴权工具中预留的密码哈希能力 |
| faker | `faker==24.0.0` | 自动生成用户名 |
| python-dateutil | `python-dateutil==2.8.2` | 解析订阅到期时间 |
| tomli / toml | `requirements.txt` | TOML 配置读取 |

### 部署与前端

| 技术 | 来源 | 说明 |
|---|---|---|
| Docker | `Dockerfile` | 可自行构建镜像 |
| Docker Compose | `docker-compose.yml`、`docker-compose.warp.yml` | 标准部署 / WARP 代理部署 |
| 原生静态页面 | `static/*.html`、`static/js/generate.js` | 登录页、管理台、生成面板 |

## 目录结构

当前仓库根目录结构较简单，主目录如下：

```text
Sora2Api/
├─ config/
│  ├─ setting.toml
│  └─ setting_warp.toml
├─ src/
│  ├─ api/
│  ├─ core/
│  ├─ services/
│  └─ utils/
├─ static/
│  ├─ login.html
│  ├─ manage.html
│  ├─ generate.html
│  └─ js/generate.js
├─ Dockerfile
├─ docker-compose.yml
├─ docker-compose.warp.yml
├─ main.py
├─ README.md
└─ requirements.txt
```

### 目录职责

- `config/`
  - 存放 TOML 配置模板。
  - `setting.toml` 是默认配置文件。
  - `setting_warp.toml` 是 WARP 代理部署时挂载进去的替代配置。

- `src/api/`
  - 对外 HTTP 路由层。
  - `routes.py` 提供 OpenAI 兼容接口。
  - `admin.py` 提供管理后台接口。

- `src/core/`
  - 基础设施层。
  - `config.py` 负责读取 `config/setting.toml` 并维护内存配置对象。
  - `database.py` 负责 SQLite 表结构、迁移、CRUD。
  - `models.py` 定义 Pydantic 数据模型。
  - `auth.py` 负责 API Key 和后台登录鉴权。
  - `logger.py` 提供调试日志输出到 `logs.txt`。

- `src/services/`
  - 业务核心层。
  - 处理 Token 生命周期、负载均衡、图片/视频生成、上游 Sora 调用、缓存、并发控制、代理解析、外部 POW 服务接入等。

- `src/utils/`
  - 当前主要是 `timezone.py`，用于日志时间转换。

- `static/`
  - 管理后台前端资源。
  - `login.html`：后台登录页。
  - `manage.html`：管理台，内部用 iframe 嵌入 `generate.html`。
  - `generate.html` + `js/generate.js`：生成面板。

### 运行时生成的目录/文件

这些目录不会在仓库初始状态中出现，但会由程序在启动时创建或使用：

- `data/`：SQLite 数据库目录，默认数据库文件为 `data/hancat.db`
- `tmp/`：缓存图片/视频文件，并通过 `/tmp/*` 对外静态提供
- `logs.txt`：调试日志文件，由 `src/core/logger.py` 在项目根目录写入

## 安装与运行方式

### 方式一：本地运行

项目根目录已有启动入口 `main.py`，本地运行命令可直接使用：

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

服务默认监听：

- Host：`0.0.0.0`
- Port：`8000`

来源：`config/setting.toml` 的 `[server]` 段。

首次可访问：

- `http://localhost:8000/`
- 根路径会重定向到 `/login`

### 方式二：Docker Compose 标准部署

`docker-compose.yml` 使用的是预构建镜像 `thesmallhancat/sora2api:latest`，不是本地 `Dockerfile` 自动构建。

```bash
docker-compose up -d
docker-compose logs -f
```

默认挂载：

- `./data:/app/data`
- `./config/setting.toml:/app/config/setting.toml`

默认环境变量：

- `PYTHONUNBUFFERED=1`
- `TZ=Asia/Shanghai`
- `TIMEZONE_OFFSET=8`

### 方式三：Docker Compose WARP 部署

`docker-compose.warp.yml` 会同时启动：

- `sora2api`
- `warp`

启动命令：

```bash
docker-compose -f docker-compose.warp.yml up -d
docker-compose -f docker-compose.warp.yml logs -f
```

该模式会把：

- `./config/setting_warp.toml`

挂载为容器内：

- `/app/config/setting.toml`

`setting_warp.toml` 中默认代理配置为：

```toml
[proxy]
proxy_enabled = true
proxy_url = "socks5://warp:1080"
```

### Dockerfile 自建镜像

根目录 `Dockerfile` 可用于自行构建镜像，特点：

- 基础镜像：`python:3.11-slim`
- 安装 Playwright Chromium 所需系统依赖
- 执行 `pip install -r requirements.txt`
- 执行 `playwright install chromium`
- 启动命令：`python main.py`

如需本地构建：

```bash
docker build -t sora2api:local .
docker run -p 8000:8000 sora2api:local
```

## 配置说明

### 配置总览

配置来源分为两层：

1. TOML 文件：`config/setting.toml`
2. SQLite 配置表：首次启动由 TOML 初始化，后续大部分配置以数据库为准

这个行为是由以下链路决定的：

- `src/core/config.py`：启动时读取 `config/setting.toml`
- `src/main.py`：
  - 首次启动：`db.init_config_from_toml(config_dict, is_first_startup=True)`
  - 后续启动：读取数据库配置表，再同步到内存 `config`

### 重要结论

- `setting.toml` 并不是所有配置的长期唯一来源。
- 首次启动后，以下配置主要从数据库读取并生效：
  - 管理员账号/API Key
  - 缓存配置
  - 生成超时
  - Token 自动刷新
  - 调用逻辑
  - POW 服务配置
- 因此，生产环境中如果已经生成 `data/hancat.db`，单纯修改 `setting.toml` 不一定会覆盖现有数据库配置。

### `config/setting.toml` 结构

#### `[global]`

来源：`config/setting.toml`

```toml
[global]
api_key = "han1234"
admin_username = "admin"
admin_password = "admin"
```

用途：

- OpenAI 兼容接口 API Key
- 管理后台默认账号密码

实际生效逻辑：

- 首次启动时写入 `admin_config` 表
- 后续优先从数据库 `admin_config` 读取

#### `[sora]`

```toml
[sora]
base_url = "https://sora.chatgpt.com/backend"
timeout = 120
max_retries = 3
poll_interval = 2.5
max_poll_attempts = 600
```

用途：

- `base_url`：上游 Sora 后端地址
- `timeout` / `max_retries`：上游请求辅助参数
- `poll_interval`：轮询间隔，启动时会和 `call_logic_config` 配合决定实际生效值
- `max_poll_attempts`：配置对象中可读，但轮询主逻辑更多使用 `timeout / poll_interval` 动态计算

#### `[server]`

```toml
[server]
host = "0.0.0.0"
port = 8000
```

用途：

- `main.py` / `src/main.py` 中 `uvicorn.run()` 的监听地址

#### `[debug]`

```toml
[debug]
enabled = false
log_requests = true
log_responses = true
mask_token = true
```

用途：

- 控制 `logs.txt` 调试日志输出

注意：

- `POST /api/admin/debug` 只修改内存中的 `config.debug_enabled`
- 当前未看到将 debug 配置写回数据库的逻辑
- 因此该配置的持久化行为为“运行时有效，重启后回到文件值”，这一点建议在维护时注意

#### `[cache]`

```toml
[cache]
enabled = false
timeout = 600
base_url = "http://127.0.0.1:8000"
```

用途：

- 控制图片/视频文件是否缓存到本地 `tmp/`
- `timeout = -1` 表示永不清理
- `base_url` 决定缓存文件对外拼接 URL 的前缀

实际生效逻辑：

- 首次启动初始化到 `cache_config`
- 后续通过 `/api/cache/*` 从数据库修改

#### `[generation]`

```toml
[generation]
image_timeout = 300
video_timeout = 3000
```

用途：

- 图片/视频轮询超时阈值

联动行为：

- 图片超时同时也会更新 `TokenLock` 的锁超时

#### `[admin]`

```toml
[admin]
error_ban_threshold = 3
task_retry_enabled = true
task_max_retries = 3
auto_disable_on_401 = true
```

用途：

- 连续错误达到阈值时自动禁用 Token
- 生成失败后的自动重试
- 401 / `token_invalidated` 时自动禁用 Token

实际生效位置：

- `src/services/token_manager.py`：错误计数与自动禁用
- `src/services/generation_handler.py`：失败重试与 401 自动禁用

#### `[proxy]`

```toml
[proxy]
proxy_enabled = false
proxy_url = ""
image_upload_proxy_enabled = false
image_upload_proxy_url = ""
```

用途：

- 全局代理
- 图片上传专用代理

实际生效逻辑：

- 首次启动初始化到 `proxy_config`
- `ProxyManager` 解析优先级为：
  1. 直接传入的 `proxy_url`
  2. Token 自身 `proxy_url`
  3. 全局代理

#### `[watermark_free]`

```toml
[watermark_free]
watermark_free_enabled = false
parse_method = "third_party"
custom_parse_url = ""
custom_parse_token = ""
fallback_on_failure = true
```

用途：

- 视频生成后发布并尝试获取无水印地址
- `parse_method` 支持 `third_party` / `custom`
- `fallback_on_failure` 控制失败时是否回退到普通带水印地址

实际生效逻辑：

- 主要在 `GenerationHandler._poll_task_result()` 中按请求动态读取数据库配置

#### `[token_refresh]`

```toml
[token_refresh]
at_auto_refresh_enabled = false
```

用途：

- 控制是否启用每日 00:00 批量刷新 Token

实际生效逻辑：

- 启动时如果开启，则由 APScheduler 注册 `batch_refresh_all_tokens`
- 也可以通过 `POST /api/token-refresh/enabled` 动态开启/关闭

#### `[call_logic]`

```toml
[call_logic]
call_mode = "default"
```

用途：

- 控制调用逻辑模式

当前可见值：

- `default`
- `polling`

影响：

- `LoadBalancer` 在 `polling` 模式下改为轮询式选择 Token，而不是随机选择
- `poll_interval` 也会影响任务轮询频率

#### `[timezone]`

```toml
[timezone]
timezone_offset = 8
```

现状说明：

- 配置文件中存在该段
- 但源码里实际时间转换读取的是环境变量 `TIMEZONE_OFFSET`（见 `src/utils/timezone.py`）
- 当前未看到从 `setting.toml` 的 `[timezone]` 自动同步到环境变量的代码
- 因此该段的实际生效链路为“待确认”

#### `[pow_service]`

```toml
[pow_service]
mode = "local"
use_token_for_pow = false
server_url = "http://localhost:8002"
api_key = "your-secure-api-key-here"
proxy_enabled = false
proxy_url = ""
```

用途：

- POW / Sentinel 处理策略
- `mode` 支持：
  - `local`
  - `external`

实际生效逻辑：

- 启动时从数据库 `pow_service_config` 读入内存
- 外部模式通过 `src/services/pow_service_client.py` 调用：
  - `POST {server_url}/api/v1/sora/sentinel-token`

### 数据库存储的配置表

`src/core/database.py` 会创建以下配置表：

- `admin_config`
- `proxy_config`
- `watermark_free_config`
- `cache_config`
- `generation_config`
- `token_refresh_config`
- `call_logic_config`
- `pow_proxy_config`
- `pow_service_config`

其中 `pow_proxy_config` 虽然仍建表，但管理接口已基本统一转向 `pow_service_config`。

## 核心模块解析

### 1. `Database`

文件：`src/core/database.py`

职责：

- 创建和迁移 SQLite 表结构
- 提供 Token、统计、任务、日志、配置的 CRUD
- 首次启动时把 `setting.toml` 初始化到数据库配置表

核心表：

- `tokens`
- `token_stats`
- `tasks`
- `request_logs`
- 各类 `*_config`

关键点：

- 默认数据库文件：`data/hancat.db`
- 启动时会检查缺失列并做轻量迁移
- `tasks.result_urls` 以 JSON 字符串存储
- `request_logs` 用于管理后台日志页

### 2. `Config`

文件：`src/core/config.py`

职责：

- 读取 `config/setting.toml`
- 提供统一的配置访问属性
- 在启动后接收数据库中的配置同步

关键点：

- `admin_username` / `admin_password` / `api_key` 在启动后会被数据库值覆盖
- 缓存、超时、调用逻辑、POW 配置也支持运行时更新
- 不是所有配置都持久化；例如 debug 当前只看到内存更新

### 3. `TokenManager`

文件：`src/services/token_manager.py`

职责：

- 处理 AT / ST / RT 的导入、转换、更新、删除
- 获取账号信息、订阅信息、Sora2 邀请码与剩余次数
- 记录成功/失败统计
- 自动禁用异常 Token
- 自动刷新快过期 Token

真实行为摘要：

- 新增 Token 时会先解析 JWT，尽量从上游拉取：
  - 用户信息
  - 套餐信息
  - Sora2 支持情况与剩余次数
- 若上游用户名为空，可能自动生成并提交一个随机用户名
- `record_error()` 会累计连续错误数，达到 `error_ban_threshold` 后自动禁用
- `record_success()` 会重置连续错误；视频成功后会刷新 Sora2 剩余次数
- 当 Sora2 剩余次数过低时，会设置冷却时间并禁用 Token
- `batch_refresh_all_tokens()` 会筛选 24 小时内过期且带 ST/RT 的 Token 做批量刷新

### 4. `LoadBalancer`

文件：`src/services/load_balancer.py`

职责：

- 从可用 Token 中选择一个用于本次请求

选择逻辑：

- 图片请求：
  - 只选 `image_enabled = true`
  - 排除被 `TokenLock` 锁住的 Token
  - 若启用并发限制，则还要通过 `ConcurrencyManager.can_use_image()`
- 视频请求：
  - 只选 `video_enabled = true`
  - 只选 `sora2_supported = true`
  - 排除处于 `sora2_cooldown_until` 冷却期的 Token
  - Pro 模型会额外要求 `plan_type == "chatgpt_pro"`
- 调用模式：
  - `default`：随机选择
  - `polling`：按 Token ID 轮询

### 5. `ConcurrencyManager`

文件：`src/services/concurrency_manager.py`

职责：

- 管理每个 Token 的图片/视频并发剩余数

关键点：

- `-1` 表示不限制
- 启动时用数据库中已有 Token 初始化
- 新增/更新 Token 时会重置对应并发计数

### 6. `TokenLock`

文件：`src/services/token_lock.py`

职责：

- 给图片生成做单 Token 锁控制

关键点：

- 默认锁超时取图片生成超时
- 只在图片生成链路使用
- 锁超时会自动清理

### 7. `ProxyManager`

文件：`src/services/proxy_manager.py`

职责：

- 统一解析代理地址

优先级：

1. 显式传入的 `proxy_url`
2. Token 自带代理
3. 全局代理配置

另外还支持图片上传专用代理：

- `get_image_upload_proxy_url()`

### 8. `FileCache`

文件：`src/services/file_cache.py`

职责：

- 下载并缓存生成结果到本地 `tmp/`
- 定时清理过期文件

关键点：

- 缓存命中文件名基于 URL 的 MD5
- 图片扩展名固定为 `.png`
- 视频扩展名固定为 `.mp4`
- 清理任务每 5 分钟跑一次
- `timeout = -1` 时不自动删除

### 9. `SoraClient`

文件：`src/services/sora_client.py`

职责：

- 封装所有上游 Sora 请求
- 处理 Sentinel / POW、上传文件、提交任务、查询进度、获取结果
- 扩展支持：
  - Prompt Enhance
  - Storyboard
  - Remix
  - Video Extension
  - Watermark-free 相关发布/删除
  - Character/Cameo 相关创建与删除

关键点：

- 使用 `curl_cffi` 进行大部分上游请求
- 可选用 Playwright 获取 Sentinel token
- 也支持外部 POW 服务
- 包含对 storyboard prompt 的识别与格式化

### 10. `GenerationHandler`

文件：`src/services/generation_handler.py`

职责：

- 把公共 API 请求翻译成具体业务流程
- 负责模型识别、媒体解析、选 Token、提交任务、轮询结果、缓存、日志记录、失败重试

它是整个项目最核心的业务编排器，内部维护了 `MODEL_CONFIG`，定义了：

- 图片模型
- 标准/Pro/HD 视频模型
- 视频续写模型
- Prompt Enhance 模型
- `avatar-create` 模型

真实流程分支包括：

- 图片生成
- 视频生成
- 图生图 / 图生视频
- Prompt Enhance
- Storyboard
- Remix
- Character only
- Character + video
- Video Extension
- Watermark-free / fallback

## 接口说明

以下接口仅纳入源码中已确认存在的路由。

### 一、OpenAI 兼容接口

#### `GET /v1/models`

鉴权：

- 需要 `Authorization: Bearer <api_key>`

用途：

- 返回 `MODEL_CONFIG` 中定义的模型列表

返回内容包含：

- `id`
- `object`
- `owned_by`
- `description`

#### `POST /v1/chat/completions`

鉴权：

- 需要 `Authorization: Bearer <api_key>`

请求模型：

- `model`
- `messages`
- `image`（可选）
- `video`（可选）
- `remix_target_id`（可选）
- `stream`
- `max_tokens`（声明存在，但当前业务逻辑中未见实际使用）

`messages` 的 `content` 支持两种形式：

1. 字符串
2. 数组，元素可能包含：
   - `{"type": "text", ...}`
   - `{"type": "image_url", ...}`
   - `{"type": "video_url", ...}`

关键行为：

- `stream = true`
  - 图片/视频生成的实际工作模式
  - 返回 SSE 流
- `stream = false`
  - 对图片/视频模型而言，当前主要执行“可用性检查”，不是完整生成
  - Prompt Enhance 支持真正的非流式返回

业务分支：

- 图片模型：生成图片，完成后输出 Markdown 图片链接
- 视频模型：轮询视频任务，完成后输出 HTML `<video>` 代码块
- `prompt-enhance-*`：直接返回增强后的提示词
- `avatar-create`：角色创建专用
- 当 `content` 中检测到 `s_<32hex>` 时会走 Remix 分支
- 当 prompt 中检测到 `gen_xxx` 且模型为续写模型时会走视频续写分支

### 二、管理后台接口

#### 1. 登录与鉴权

- `POST /api/login`
  - 后台账号密码登录
  - 成功后返回一个 `admin-...` token
- `POST /api/logout`
  - 注销当前后台 token

说明：

- 后台 token 存在进程内存 `active_admin_tokens` 集合中
- 服务重启后登录态会失效

#### 2. Token 管理

- `GET /api/tokens`
  - 返回所有 Token 和统计信息
- `POST /api/tokens`
  - 添加新 Token
- `PUT /api/tokens/{token_id}`
  - 更新 Token / ST / RT / client_id / proxy / 并发限制等
- `DELETE /api/tokens/{token_id}`
  - 删除 Token
- `PUT /api/tokens/{token_id}/status`
  - 启用/禁用状态切换
- `POST /api/tokens/{token_id}/enable`
- `POST /api/tokens/{token_id}/disable`
- `POST /api/tokens/{token_id}/test`
  - 测试 Token 是否有效并刷新部分状态

转换与导入：

- `POST /api/tokens/st2at`
- `POST /api/tokens/rt2at`
- `POST /api/tokens/import`
  - 支持 `offline` / `at` / `st` / `rt`
- `POST /api/tokens/import/pure-rt`

批量接口：

- `POST /api/tokens/batch/test-update`
- `POST /api/tokens/batch/enable-all`
- `POST /api/tokens/batch/delete-disabled`
- `POST /api/tokens/batch/disable-selected`
- `POST /api/tokens/batch/delete-selected`
- `POST /api/tokens/batch/update-proxy`

#### 3. 管理员与系统配置

- `GET /api/admin/config`
- `POST /api/admin/config`
  - 更新错误阈值、失败重试、401 自动禁用
- `POST /api/admin/password`
  - 修改后台账号/密码
- `POST /api/admin/apikey`
  - 更新公共 API Key
- `POST /api/admin/debug`
  - 启停调试日志

#### 4. 代理配置

- `GET /api/proxy/config`
- `POST /api/proxy/config`
- `POST /api/proxy/test`

#### 5. 无水印配置

- `GET /api/watermark-free/config`
- `POST /api/watermark-free/config`

#### 6. 缓存配置

- `GET /api/cache/config`
- `POST /api/cache/config`
  - 更新缓存超时
- `POST /api/cache/base-url`
  - 更新缓存对外基础地址
- `POST /api/cache/enabled`

#### 7. 生成超时配置

- `GET /api/generation/timeout`
- `POST /api/generation/timeout`

#### 8. Token 自动刷新

- `GET /api/token-refresh/config`
- `POST /api/token-refresh/enabled`

#### 9. 调用逻辑配置

- `GET /api/call-logic/config`
- `POST /api/call-logic/config`

#### 10. POW 配置

- `GET /api/pow-proxy/config`
- `POST /api/pow-proxy/config`
- `GET /api/pow/config`
- `POST /api/pow/config`

#### 11. 统计、日志与任务

- `GET /api/stats`
  - 系统总览统计
- `GET /api/logs`
  - 最近请求日志
- `DELETE /api/logs`
  - 清空日志
- `POST /api/tasks/{task_id}/cancel`
  - 终止正在处理中的任务
- `GET /api/admin/logs/download`
  - 下载 `logs.txt`

## 业务流程

### 1. 启动初始化流程

1. `main.py` 启动 Uvicorn，加载 `src.main:app`
2. `src/main.py` 创建全局组件：
   - `Database`
   - `TokenManager`
   - `ProxyManager`
   - `ConcurrencyManager`
   - `LoadBalancer`
   - `SoraClient`
   - `GenerationHandler`
3. 挂载：
   - `/static` -> `static/`
   - `/tmp` -> `tmp/`
4. `startup_event()` 执行：
   - 读取 `setting.toml`
   - 初始化数据库表
   - 首次启动时把配置写入数据库
   - 之后从数据库回填内存配置
   - 初始化并发管理器
   - 启动缓存清理任务
   - 按需启动每日 Token 刷新调度器

### 2. Token 导入/刷新流程

#### 导入

1. 管理后台调用 `/api/tokens` 或 `/api/tokens/import*`
2. `TokenManager` 根据模式使用：
   - 直接 AT
   - ST -> AT
   - RT -> AT
3. 解析 JWT
4. 尝试拉取用户信息、订阅信息、Sora2 状态
5. 写入 `tokens` 和 `token_stats`
6. 同步 `ConcurrencyManager`

#### 自动刷新

1. 若 `at_auto_refresh_enabled = true`，调度器每日 00:00 执行
2. `batch_refresh_all_tokens()` 遍历 Token
3. 仅处理：
   - 带 ST/RT
   - 有过期时间
   - 24 小时内过期
4. 优先 ST 刷新，其次 RT 刷新
5. 刷新失败可能把 Token 标记为过期并禁用

### 3. 图片生成流程

1. 客户端调用 `POST /v1/chat/completions`
2. `routes.py` 解析 prompt / image
3. `GenerationHandler` 校验模型
4. `LoadBalancer` 选择支持图片的 Token
5. 获取图片锁与图片并发槽
6. 如带输入图片，则先上传图片
7. 调用 `SoraClient.generate_image()`
8. 轮询 `get_image_tasks()`
9. 成功后：
   - 可选下载并缓存到 `tmp/`
   - 写入 `tasks`
   - 写入 `request_logs`
   - SSE 返回 Markdown 图片链接
10. 释放图片锁和并发槽

### 4. 视频生成流程

1. 客户端调用 `POST /v1/chat/completions`
2. `routes.py` 解析 prompt / image / remix / video
3. `GenerationHandler` 判断分支：
   - 普通视频
   - Storyboard
   - Remix
   - Character 相关
   - Video Extension
4. `LoadBalancer` 选择支持视频的 Token
5. 获取视频并发槽
6. 调用上游创建任务
7. 轮询视频任务：
   - `get_pending_tasks()`
   - `get_video_drafts()`
8. 成功后：
   - 可选无水印发布
   - 可选缓存到 `tmp/`
   - 更新数据库任务和日志
   - SSE 返回 HTML `<video>` 代码块
9. 释放视频并发槽

### 5. 无水印流程

仅在视频完成后且无水印配置开启时触发。

1. `GenerationHandler._poll_task_result()` 检测到 `watermark_free_enabled`
2. 调用 `SoraClient.post_video_for_watermark_free()`
3. 根据配置决定解析方式：
   - `third_party`：拼接第三方 URL
   - `custom`：调用自定义解析服务
4. 若缓存开启，下载无水印视频到 `tmp/`
5. 若失败：
   - `fallback_on_failure = true`：回退到普通视频 URL
   - `false`：任务失败

### 6. 角色创建流程

角色创建并不通过管理后台接口，而是走公共生成接口的特殊模型/分支。

#### 角色专用创建

1. 使用模型 `avatar-create`
2. 输入视频或 prompt 中的 `gen_xxx`
3. 上传/解析来源
4. 轮询 Cameo 处理状态
5. 下载头像、上传头像、Finalize Character、设置公开
6. SSE 返回 `character_card` 事件和摘要文本

#### 角色创建后直接生成视频

1. 上传视频
2. 创建角色
3. 用 `@username + prompt` 再次生成视频
4. 结束后尝试删除临时角色

### 7. Remix 流程

1. 请求中传入 `remix_target_id`
   - 或 prompt 中包含 `s_<32hex>`
2. 清理 prompt 中的 remix 链接
3. 调用上游 remix 接口
4. 轮询视频结果

### 8. 视频续写流程

1. 使用 `sora2-extension-10s` 或 `sora2-extension-15s`
2. prompt 中必须包含 `gen_xxx`
3. `GenerationHandler` 解析 generation id 和续写 prompt
4. 调用 `SoraClient.extend_video()`
5. 后续和普通视频任务一样轮询返回

## 部署方式

### 标准部署建议

- 若只是单机使用，优先用 `docker-compose.yml`
- 若要自己构建镜像，再参考 `Dockerfile`

### 数据与挂载

建议持久化以下内容：

- `data/`：数据库
- `config/setting.toml`：初始配置

缓存目录 `tmp/` 当前未在 compose 中挂载；如果希望重启后仍保留缓存，可按需追加卷挂载。

### 时区

容器部署里显式设置了：

- `TZ=Asia/Shanghai`
- `TIMEZONE_OFFSET=8`

其中：

- `TZ` 影响容器系统时间
- `TIMEZONE_OFFSET` 影响 `src/utils/timezone.py` 的日志时间转换

### 代理/WARP

如果所在网络环境需要代理访问上游，可选两种方式：

- 直接在后台或配置中填代理地址
- 使用 `docker-compose.warp.yml` 启动 WARP sidecar

### 浏览器依赖

由于项目包含 Playwright 逻辑，自建镜像时需要：

- 安装 Chromium 运行依赖
- 执行 `playwright install chromium`

`Dockerfile` 已经处理了这一点。

## 常见问题与排查

### 1. 公共 API 返回 401

检查项：

- 请求头是否带了 `Authorization: Bearer <api_key>`
- 当前 API Key 是否已经在后台被改过

原因说明：

- 公共 API Key 最终以数据库 `admin_config.api_key` 为准，不一定还是 `setting.toml` 默认值

### 2. 管理后台登录后重启失效

这是当前实现的正常行为。

原因：

- 后台会话 token 只保存在进程内存 `active_admin_tokens`
- 服务重启后该集合会清空

### 3. `stream=false` 没有真正生成图片/视频

这是当前接口实现特性。

现状：

- 对图片/视频模型，非流式模式主要做可用性检查
- 真正生成建议使用 `stream=true`
- Prompt Enhance 是例外，支持真实非流式返回

### 4. 提示 “No available tokens...”

常见原因：

- Token 被手动禁用
- Token 已过期
- 视频 Token 不支持 Sora2
- Sora2 剩余次数耗尽且在冷却期
- 图片或视频并发数耗尽
- 请求的是 Pro 模型，但没有 `chatgpt_pro` Token

排查入口：

- 管理后台 `Token` 列表
- `GET /api/tokens`
- `POST /api/tokens/{id}/test`

### 5. 视频频繁超时

检查项：

- `generation.video_timeout`
- `call_logic.poll_interval`
- 上游代理质量

相关接口：

- `GET /api/generation/timeout`
- `POST /api/generation/timeout`
- `GET /api/call-logic/config`

### 6. 代理不可用

排查方式：

- 调用 `POST /api/proxy/test`
- 检查全局代理与 Token 级代理是否冲突
- WARP 模式下确认 `warp` 容器是否正常

### 7. 缓存文件访问异常

检查项：

- 缓存是否开启：`/api/cache/config`
- `cache_base_url` 是否正确
- `tmp/` 是否存在、是否有写权限

说明：

- 缓存路径通过 `/tmp/*` 暴露
- 若 `cache_base_url` 为空，系统会退回 `http://{server_host}:{server_port}`

### 8. 无水印失败

检查项：

- `watermark_free_enabled` 是否开启
- `parse_method` 是否为 `custom`
- 若是 `custom`，`custom_parse_url` / `custom_parse_token` 是否已配置
- 若失败时想保底，确认 `fallback_on_failure = true`

### 9. 下载不到 `logs.txt`

检查项：

- 是否开启 debug：`POST /api/admin/debug`
- 服务启动后 `logs.txt` 是否存在

说明：

- `DebugLogger` 启动时会删除旧的 `logs.txt` 并重新创建
- 若未开启 debug，则日志内容可能为空或文件不存在

### 10. 修改 `setting.toml` 后配置没生效

这通常不是 bug，而是持久化边界导致。

原因：

- 首次启动后，多数配置由数据库表接管
- 后续重启时会从数据库回填到内存

建议：

- 运行中的实例优先通过后台接口更新配置
- 若确需重新以 TOML 初始化，需要结合当前 `data/hancat.db` 处理策略谨慎操作

### 11. 数据库迁移异常

项目启动时会自动执行：

- `init_db()`
- `check_and_migrate_db()`

如升级后出现异常，可优先检查：

- `data/hancat.db` 是否可写
- SQLite 文件是否损坏
- 是否有旧版本表缺列导致迁移失败

## 已发现的待确认 / 差异

以下内容是根据源码实际核对后发现的“不一致”或“未完全接线”点，文档中不应按已实现功能写死。

### 1. `/api/characters` 后端未找到

现象：

- `static/manage.html` 调用了：
  - `GET /api/characters`
  - `DELETE /api/characters/{id}`
- 但当前 `src/api/` 下未找到对应路由

结论：

- 这部分更像前端残留或未提交完整后端，标记为“待确认”

### 2. 没有单独的 `/generate` 路由

现象：

- `static/manage.html` 通过 iframe 加载 `/static/generate.html`
- `src/main.py` 只显式暴露了：
  - `/`
  - `/login`
  - `/manage`

结论：

- 当前没有单独的 `/generate` 页面路由
- 生成面板是静态资源路径，不是独立后端页面路由

### 3. `tokens.username` 与 Pydantic `Token` 模型不一致

现象：

- 数据表 `tokens` 含 `username` 列
- `admin.py` 的日志查询也返回 `token_username`
- 但 `src/core/models.py` 的 `Token` 模型未声明 `username`

结论：

- 运行时是否依赖 Pydantic 额外字段处理，需要“待确认”
- 后续维护时建议统一数据表与模型字段

### 4. Python 版本说明不一致

现象：

- `README.md` 写的是 Python 3.8+
- `Dockerfile` 固定使用 `python:3.11-slim`

结论：

- 当前最低可运行版本以源码并不能完全确认
- 若要给出正式版本承诺，建议补一轮实际版本验证

### 5. `python-dotenv` 已安装但未看到 `.env` 生效链路

现象：

- `requirements.txt` 包含 `python-dotenv`
- `.gitignore` 也忽略了 `.env`
- 但源码里未找到 `load_dotenv()` 或类似加载逻辑

结论：

- 不应把 `.env` 视为当前已接入的正式配置来源

### 6. `[timezone]` 配置段的实际生效链路待确认

现象：

- `config/setting.toml` 中有 `[timezone].timezone_offset`
- 但 `src/utils/timezone.py` 实际读的是环境变量 `TIMEZONE_OFFSET`

结论：

- 当前不能确认修改 TOML 的 `[timezone]` 会直接影响运行时

## 维护建议

### 1. 先理顺“配置来源”

当前项目同时存在：

- TOML 配置
- SQLite 配置表
- 少量仅内存生效配置

建议维护时优先明确每个配置项属于哪一类，尤其是：

- 是否首次启动后就转入数据库
- 是否支持热更新
- 是否重启会丢失

### 2. 补齐前后端接口对齐检查

当前最明显的不一致是：

- `static/manage.html` 中的 `/api/characters*`

建议：

- 要么补后端接口
- 要么移除前端入口，避免误导使用者

### 3. 统一数据库字段与 Pydantic 模型

优先检查：

- `tokens.username`
- 其他可能在表结构里存在、但模型未声明的字段

这会直接影响：

- 类型提示
- Pydantic 校验
- 日后重构安全性

### 4. 为关键流程补自动化测试

当前仓库未发现明确的测试目录或测试命令配置。

建议至少覆盖：

- Token 导入与 ST/RT 转换
- `POST /v1/chat/completions` 主要分支
- 配置接口读写
- 数据库初始化与迁移

### 5. 收敛日志策略

当前日志分两套：

- `request_logs` 表
- `logs.txt` 调试文件

建议明确：

- 哪些场景查数据库日志
- 哪些场景查文件日志
- debug 日志是否需要长期保留或轮转

### 6. 明确公共 API 的产品语义

当前 `POST /v1/chat/completions` 对图片/视频模型的非流式行为是“可用性检查”，而不是“同步生成”。

建议在后续对外文档中显式强调这一点，避免调用方按 OpenAI 常规 chat completion 语义误用。

### 7. 评估安全与默认值

默认配置中的：

- `admin/admin`
- `api_key = han1234`

只适合本地测试。部署时应立即修改。

此外还建议关注：

- CORS 当前为全开放 `*`
- 后台会话 token 仅保存在内存中

## 快速上手建议

如果你是第一次接手这个项目，建议按下面顺序阅读和验证：

1. 先看 `src/main.py`
   - 搞清楚启动时初始化了哪些组件、挂载了哪些路由和静态目录
2. 再看 `src/api/routes.py`
   - 理解公共 API 的输入格式和流式/非流式差异
3. 再看 `src/services/generation_handler.py`
   - 这是图片、视频、Remix、角色、续写等流程的总编排器
4. 再看 `src/services/token_manager.py` 和 `src/services/load_balancer.py`
   - 理解 Token 是怎么导入、筛选、禁用、重试、刷新和轮询的
5. 最后看 `src/core/database.py`
   - 弄清楚哪些配置和状态是持久化的

一个最小可运行闭环通常是：

1. 启动服务：`python main.py`
2. 登录后台：`http://localhost:8000/login`
3. 添加至少一个可用 Token
4. 调用 `GET /v1/models`
5. 用 `POST /v1/chat/completions` 发起流式生成请求

以上流程跑通后，再进入代理、缓存、无水印、自动刷新、WARP/POW 等高级能力排查会更高效。

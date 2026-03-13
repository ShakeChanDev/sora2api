# Sora2API 开发者说明文档

> 说明：本文基于当前仓库静态代码、配置文件和前端资源整理，未执行会改写仓库状态的启动操作。无法从当前仓库闭环确认的内容，均标注为"待确认"。

## 项目概述

Sora2API 是一个基于 FastAPI 的单服务项目，对外提供两类能力：

- OpenAI 兼容的生成接口，核心端点是 `GET /v1/models` 和 `POST /v1/chat/completions`
- 一个自带的管理后台，用于 Token 管理、系统配置、日志查看和内置生成面板

从当前代码实现看，这个项目的目标是把 Sora 相关图片、视频和提示词增强能力统一包装成一个开发者可直接调用的 HTTP 服务，并补齐以下运行能力：

- 多 Token 管理与轮询
- 代理与 WARP 支持
- SQLite 持久化
- 任务轮询与日志记录
- 文件缓存与 `/tmp/*` 静态访问
- 管理后台和生成面板

项目启动入口：

- `main.py`
- `src/main.py`

运行时重要数据位置：

- 数据库：`data/hancat.db`
- 缓存目录：`tmp/`
- 调试日志：`logs.txt`

## 如何快速理解并上手这个项目

建议按下面顺序阅读源码：

1. 先看 `src/main.py`，理解应用启动、依赖装配、静态路由和启动流程。
2. 再看 `src/api/routes.py`，确认外部 OpenAI 兼容接口接收什么、返回什么。
3. 再看 `src/services/generation_handler.py`，这是生成主流程编排中心。
4. 接着看 `src/services/sora_client.py`，这里是所有上游 Sora/ChatGPT 请求细节。
5. 最后看 `src/api/admin.py` 和 `src/core/database.py`，理解配置持久化、Token 生命周期和后台能力。

如果只是想先跑起来：

1. 本地安装依赖并执行 `python main.py`
2. 或直接执行 `docker-compose up -d`
3. 访问 `http://localhost:8000/`，页面会跳转到 `/login`
4. 首次默认管理员账号来自 `config/setting.toml`，默认是 `admin / admin`
5. 默认 API Key 初始值来自 `config/setting.toml`，默认是 `han1234`

## 技术栈

| 类别 | 实际组件 | 说明 |
|---|---|---|
| Web 框架 | `fastapi==0.119.0` | 主服务框架 |
| ASGI 运行 | `uvicorn[standard]==0.32.1` | 启动 `src.main:app` |
| HTTP 请求 | `curl-cffi==0.13.0` | 主要用于访问上游 Sora/ChatGPT 接口 |
| 浏览器能力 | `playwright==1.48.0` | 用于 Sentinel/PoW 相关浏览器流程；代码中允许缺失后降级 |
| 数据建模 | `pydantic==2.10.4` | 请求、响应、配置数据模型 |
| 存储 | `aiosqlite==0.20.0` | SQLite 异步访问 |
| 认证与安全 | `pyjwt==2.10.1`、`bcrypt==4.2.1` | JWT 解码、密码哈希与校验 |
| 文件上传 | `python-multipart==0.0.20` | 支撑 multipart 相关请求 |
| 调度 | `APScheduler==3.10.4` | 每日批量刷新 Token |
| 时间处理 | `python-dateutil==2.8.2` | 订阅到期时间解析 |
| 前端 | 原生 HTML/CSS/JS | `login.html`、`manage.html`、`generate.html` 无前端构建链 |
| UI 依赖 | Tailwind CDN | `login.html` 与 `manage.html` 通过 CDN 加载样式 |
| 容器运行时 | `python:3.11-slim` | Dockerfile 基础镜像 |
| 代理侧车 | `caomingjun/warp` | WARP 模式下的 `warp` 服务 |

补充说明：

- README 声明 Python 版本为 `3.8+`，但 `Dockerfile` 使用的是 Python `3.11-slim`。本地最低兼容版本以 README 为线索，但"实际最低版本"仍属"待确认"。
- 依赖清单里有 `python-dotenv`、`pydantic-settings`、`toml`，当前主流程代码中未看到明显直接调用，具体用途属"待确认"。

## 目录结构

| 路径 | 作用 |
|---|---|
| `config/` | TOML 配置模板目录，包含标准模式和 WARP 模式配置 |
| `config/setting.toml` | 默认配置文件，首次启动时用于初始化数据库配置 |
| `config/setting_warp.toml` | WARP 模式下会被挂载为运行时 `setting.toml` |
| `src/` | Python 应用源码目录 |
| `src/main.py` | FastAPI 应用创建、依赖注入、启动与关闭逻辑 |
| `src/api/` | HTTP 路由层，分为 OpenAI 兼容接口和后台管理接口 |
| `src/core/` | 配置、认证、数据库、日志、Pydantic 模型等底层能力 |
| `src/services/` | 业务服务层，包含生成流程、Token 管理、代理、缓存、并发、负载均衡、Sora 上游调用 |
| `src/utils/` | 当前主要是时区工具 |
| `static/` | 前端静态资源目录 |
| `static/login.html` | 管理员登录页 |
| `static/manage.html` | 管理后台主页面 |
| `static/generate.html` | 生成面板页面 |
| `static/js/generate.js` | 生成面板核心前端逻辑 |
| `main.py` | 根目录启动脚本 |
| `requirements.txt` | Python 依赖清单 |
| `Dockerfile` | 容器镜像定义 |
| `docker-compose.yml` | 标准 Docker Compose 部署 |
| `docker-compose.warp.yml` | WARP 代理模式部署 |

运行期目录和文件：

| 路径 | 来源 | 说明 |
|---|---|---|
| `data/` | 运行时创建 | 存放 SQLite 数据库 |
| `data/hancat.db` | 运行时创建 | 主数据库 |
| `tmp/` | 启动时创建 | 缓存图片/视频文件，并通过 `/tmp/*` 对外暴露 |
| `logs.txt` | 启动时创建 | 调试日志文件；注意会在每次启动时清空重建 |

当前仓库未发现：

- `tests/` 目录
- `pytest.ini`
- `pyproject.toml`
- 前端构建配置文件
- 自动化测试用例

## 安装与运行方式

### 前置条件

- Docker 与 Docker Compose，或
- Python 虚拟环境与 `pip`

### 方式一：本地运行

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

启动后访问：

- `http://localhost:8000/`
- `http://localhost:8000/login`
- `http://localhost:8000/manage`

首次默认值来自 `config/setting.toml`：

- 管理员账号：`admin`
- 管理员密码：`admin`
- API Key：`han1234`

### 方式二：标准 Docker Compose

```bash
docker-compose up -d
docker-compose logs -f
```

已确认行为：

- 暴露端口 `8000:8000`
- 挂载 `./data:/app/data`
- 挂载 `./config/setting.toml:/app/config/setting.toml`
- 环境变量包含 `TZ=Asia/Shanghai` 与 `TIMEZONE_OFFSET=8`

### 方式三：WARP 代理模式

```bash
docker-compose -f docker-compose.warp.yml up -d
docker-compose -f docker-compose.warp.yml logs -f
```

已确认行为：

- 主服务仍暴露 `8000:8000`
- 额外启动 `warp` 容器并暴露 `1080:1080`
- 主服务挂载的是 `config/setting_warp.toml`，实际容器内路径仍是 `/app/config/setting.toml`
- WARP 模式配置中代理地址为 `socks5://warp:1080`

### 首次启动与后续启动的区别

首次启动时：

1. `src/core/config.py` 会先读取 `config/setting.toml`
2. `src/main.py` 检测数据库不存在
3. `src/core/database.py` 创建表结构
4. 使用 `setting.toml` 初始化各配置表默认行

后续启动时：

1. 仍然先读取 `setting.toml`
2. 如果已存在 `data/hancat.db`，则执行数据库结构检查与迁移
3. 大多数运行配置会从数据库重新加载回内存配置对象

这意味着：

- `setting.toml` 不是唯一配置来源
- 真正长期生效的多数配置，最终以 SQLite 为准
- 手改 `setting.toml` 后，是否能在已有数据库场景下直接生效，要看该配置项是否会被数据库覆盖

## 配置说明

### 配置优先级与生效方式

当前项目的配置不是"纯文件式"，而是"文件初始化 + 数据库存储 + 运行时回填"模式。

真实生效顺序：

1. `src/core/config.py` 启动时读取 `config/setting.toml`
2. `src/main.py` 在 `startup_event` 中初始化或迁移数据库
3. 启动阶段从数据库加载以下配置并覆盖或回填运行时配置：
   - 管理员账号、密码、API Key
   - 缓存配置
   - 生成超时配置
   - Token 自动刷新配置
   - 调用逻辑配置
   - POW 服务配置
4. 后台接口会继续更新数据库，并同步修改运行时内存配置
5. 当前 `debug enabled` 开关只更新内存，不会写回数据库

### 配置项一览

| 配置段 | 关键字段 | 当前作用 | 持久化说明 |
|---|---|---|---|
| `[global]` | `api_key` `admin_username` `admin_password` | 初始 API Key 与后台登录信息 | 首次启动写入 `admin_config`；后续以数据库为准 |
| `[sora]` | `base_url` `timeout` `max_retries` `poll_interval` `max_poll_attempts` | 上游 Sora 接口地址、请求超时、重试、轮询参数 | 主要来自文件；`poll_interval` 运行时可被调用逻辑配置覆盖 |
| `[server]` | `host` `port` | Uvicorn 监听地址 | 文件读取 |
| `[debug]` | `enabled` `log_requests` `log_responses` `mask_token` | 调试日志控制 | `enabled` 可运行时修改但当前不持久化；其他字段当前仅文件读取 |
| `[cache]` | `enabled` `timeout` `base_url` | 缓存开关、缓存过期、返回 URL 基址 | 数据库存储并运行时更新 |
| `[generation]` | `image_timeout` `video_timeout` | 图片/视频任务超时阈值 | 数据库存储并运行时更新 |
| `[admin]` | `error_ban_threshold` `task_retry_enabled` `task_max_retries` `auto_disable_on_401` | 错误封禁、失败重试、401 自动禁用 | 数据库存储并运行时更新 |
| `[proxy]` | `proxy_enabled` `proxy_url` `image_upload_proxy_enabled` `image_upload_proxy_url` | 全局代理和图片上传专用代理 | 数据库存储并运行时更新 |
| `[watermark_free]` | `watermark_free_enabled` `parse_method` `custom_parse_url` `custom_parse_token` `fallback_on_failure` | 无水印视频流程 | 数据库存储并运行时更新 |
| `[token_refresh]` | `at_auto_refresh_enabled` | 是否启用每日批量自动刷新 | 数据库存储并驱动 APScheduler |
| `[call_logic]` | `call_mode` | 调用模式 | 数据库存储；当前代码里主要影响负载均衡策略 |
| `[timezone]` | `timezone_offset` | 注释上用于时区 | 待确认。当前代码实际读取环境变量 `TIMEZONE_OFFSET`，不是这里 |
| `[pow_service]` | `mode` `use_token_for_pow` `server_url` `api_key` `proxy_enabled` `proxy_url` | Sentinel/PoW 计算模式 | 数据库存储并运行时更新 |

### 需要特别注意的配置事实

- `debug enabled` 当前通过 `POST /api/admin/debug` 只改内存，重启后是否保留取决于 `setting.toml`。
- `TIMEZONE_OFFSET` 的真实读取位置在 `src/utils/timezone.py`，不是 `config/setting.toml` 的 `[timezone]` 段。
- WARP 模式使用的是 `config/setting_warp.toml`，它比标准配置更精简，部分缺失字段会依赖代码默认值。
- `pow_proxy_config` 在代码中仍有兼容层，但当前实际管理已统一归入 `pow_service_config`。

## 核心模块解析

### 1. `src/core`：基础设施层

#### `src/core/config.py`

职责：

- 读取 `config/setting.toml`
- 提供 `config` 全局对象
- 允许运行时更新部分配置
- 支持"文件默认值 + 数据库覆盖"的访问方式

关键点：

- 管理员账号密码与 API Key 可从数据库注入回内存
- `call_logic_mode`、缓存、超时、POW 服务等都支持运行时动态修改
- 配置对象不是只读常量，而是运行期状态容器

#### `src/core/auth.py`

职责：

- 校验 OpenAI 接口的 `Authorization: Bearer <api_key>`
- 校验后台登录用户名密码
- 提供密码哈希和校验方法

关键点：

- `/v1/*` 使用 API Key
- `/api/*` 后台接口使用管理员登录后发放的会话 Token
- 后台会话 Token 不是 JWT，而是简单随机串

#### `src/core/logger.py`

职责：

- 记录请求、响应、错误到 `logs.txt`

关键点：

- `logs.txt` 会在每次服务启动时被清空
- `mask_token=true` 时会对 Bearer Token 做脱敏
- 仅当 `debug.enabled=true` 时才真正写日志

#### `src/core/database.py`

职责：

- 创建和迁移 SQLite 表结构
- 提供 Token、任务、日志、配置表的 CRUD

当前已确认的表：

- `tokens`
- `token_stats`
- `tasks`
- `request_logs`
- `admin_config`
- `proxy_config`
- `watermark_free_config`
- `cache_config`
- `generation_config`
- `token_refresh_config`
- `call_logic_config`
- `pow_proxy_config`
- `pow_service_config`

关键点：

- 首次启动时把 TOML 的默认值落表
- 后续启动会做缺失列迁移
- `get_active_tokens()` 会筛选：
  - `is_active = 1`
  - `cooled_until` 已过或为空
  - `expiry_time > CURRENT_TIMESTAMP`

#### `src/core/models.py`

职责：

- 定义 Token、任务、日志、各类配置表的 Pydantic 模型
- 定义 OpenAI 兼容请求/响应模型

关键点：

- `ChatCompletionRequest` 支持 `model`、`messages`、`image`、`video`、`remix_target_id`、`stream`
- `ChatMessage.content` 既支持字符串，也支持多模态数组

### 2. `src/api`：路由层

#### `src/api/routes.py`

职责：

- 暴露 `GET /v1/models`
- 暴露 `POST /v1/chat/completions`

关键点：

- 只消费 `messages[-1]`，不是完整多轮对话
- 支持字符串 prompt 和多模态数组
- 可从 prompt 自动提取 `remix_target_id`
- 流式返回使用 `text/event-stream`

#### `src/api/admin.py`

职责：

- 管理员登录与退出
- Token CRUD、批量导入、ST/RT 转换
- 代理、缓存、超时、POW、调用逻辑、无水印、自动刷新等后台配置
- 系统统计、请求日志、任务取消、调试日志下载

关键点：

- 管理员会话 Token 存在进程内存 `active_admin_tokens` 中
- 服务重启后，后台登录态会失效
- 当前实现不是多实例共享会话设计

### 3. `src/services`：业务服务层

#### `src/services/generation_handler.py`

职责：

- 定义 `MODEL_CONFIG`
- 编排图片、视频、提示词增强、角色创建、Remix、分镜、视频续写等流程
- 任务轮询、缓存落地、重试与错误处理

关键点：

- 非流式模式对普通生成主要是"可用性检查"
- 提示词增强是少数支持真正非流式返回内容的分支
- 视频完成后可进入无水印发布/解析流程
- 流式返回除了 `content`，还会携带 `reasoning_content`

#### `src/services/sora_client.py`

职责：

- 处理所有上游 Sora/ChatGPT 请求
- 生成图片、视频、Remix、分镜、视频续写、角色创建、提示词增强
- 处理 Sentinel/PoW、浏览器设备信息、Playwright 回退

关键点：

- 图片生成调用 `/video_gen`
- 视频生成最终走 `/nf/create` 或 storyboard/extension 相关接口
- 分镜检测是 prompt 语法触发，不是单独对外 API
- 代码里集成了本地 PoW 与外部 POW 服务两套方案

#### `src/services/token_manager.py`

职责：

- 添加、更新、测试 Token
- ST 转 AT、RT 转 AT
- 拉取用户信息、订阅信息、Sora2 支持状态与剩余额度
- 错误计数、自动禁用、自动刷新

关键点：

- 失败累计达到 `error_ban_threshold` 会自动禁用 Token
- 401 或 `token_invalidated` 会触发失效逻辑
- 自动刷新优先尝试 ST，再尝试 RT
- 每日批量刷新由 APScheduler 驱动

#### `src/services/load_balancer.py`

职责：

- 从活跃 Token 池中选择合适 Token

关键点：

- 默认随机选择
- `call_logic_mode = polling` 时改为轮询
- 图片场景会过滤锁定 Token
- 视频场景会过滤不支持 Sora2、额度冷却中、未启用视频能力的 Token
- Pro 模型要求 `plan_type == "chatgpt_pro"`

#### `src/services/concurrency_manager.py`

职责：

- 控制每个 Token 的图片/视频并发额度

关键点：

- `-1` 表示不限制
- 启动时从数据库中现有 Token 初始化
- 新增或更新 Token 时会重置并发计数

#### `src/services/token_lock.py`

职责：

- 图片生成的 Token 锁控制

关键点：

- 图片生成不是简单共享池，而是"单 Token 锁 + 可选并发额度"
- 锁超时时间跟随 `image_timeout`

#### `src/services/file_cache.py`

职责：

- 下载并缓存图片或视频到 `tmp/`
- 定时清理过期文件

关键点：

- 清理任务每 5 分钟跑一次
- `timeout = -1` 表示永不删除
- 若 `cache.enabled=false`，最终返回的是原始远程地址

#### `src/services/proxy_manager.py`

职责：

- 统一解析代理来源

优先级：

1. 显式传入的 `proxy_url`
2. Token 级代理
3. 全局代理
4. 无代理

图片上传还有独立优先级：

1. 图片上传专用代理
2. Token 级代理
3. 全局代理

#### `src/services/pow_service_client.py`

职责：

- 访问外部 POW 服务 `/api/v1/sora/sentinel-token`

关键点：

- 只在 `pow_service.mode = external` 时主用
- 外部服务失败后会回退到本地模式

#### `src/utils/timezone.py`

职责：

- 请求日志的 UTC 到本地时区转换

关键点：

- 读取环境变量 `TIMEZONE_OFFSET`
- 当前未看到直接读取 `[timezone] timezone_offset` 的代码路径

## 接口说明

### OpenAI 兼容接口

#### 认证方式

所有 `/v1/*` 接口都要求：

```http
Authorization: Bearer <API_KEY>
```

校验逻辑在 `src/core/auth.py`。

#### 1. `GET /v1/models`

| 项目 | 说明 |
|---|---|
| 路径 | `GET /v1/models` |
| 认证 | Bearer API Key |
| 作用 | 返回当前 `MODEL_CONFIG` 中注册的模型 |
| 关键返回字段 | `object=list`、`data[].id`、`data[].description` |
| 错误来源 | API Key 无效时返回 401 |

#### 2. `POST /v1/chat/completions`

| 项目 | 说明 |
|---|---|
| 路径 | `POST /v1/chat/completions` |
| 认证 | Bearer API Key |
| 关键请求字段 | `model`、`messages`、可选 `image`、`video`、`remix_target_id`、`stream` |
| 内容格式 | `messages[-1].content` 支持字符串，或多模态数组 |
| 多模态项 | `text`、`image_url`、`video_url` |
| 图片输入 | 支持 `data:image/...;base64,...` |
| 视频输入 | 支持 `data:video/...;base64,...` 或 URL |
| 成功返回 | 流式 SSE 或 JSON |
| 典型错误 | 无效模型、无可用 Token、Pro Token 不满足、内容违规、上游超时、国家或地区限制、PoW 或 Sentinel 失败 |

请求行为上的重要实现细节：

- 当前实现只读取最后一条消息 `messages[-1]`。
- 如果是多模态数组，会提取其中的文本项和图片或视频项。
- 如果 prompt 中出现形如 `s_<32位hex>` 的字符串，会自动识别为 Remix 目标 ID。
- 如果使用 `avatar-create` 模型，可以通过视频或 `gen_xxx` 触发角色创建。
- 如果使用 `sora2-extension-*` 模型，prompt 中必须包含 `gen_xxx`。

返回格式的重要实现细节：

流式返回：

- `Content-Type: text/event-stream`
- 单个 chunk 的 `object` 是 `chat.completion.chunk`
- `choices[0].delta` 中除了 `content` 外，还有 `reasoning_content`
- `model` 字段当前固定写为 `"sora"`，不是请求的模型名

非流式返回：

- 对普通图片或视频生成，当前主要用于可用性检查，不一定直接产出最终媒体
- 对提示词增强，会直接返回最终文本
- 图片生成的非流式内容会被包装为 Markdown 图片
- 视频生成的非流式内容会被包装为 HTML `<video>` 片段

当前代码中注册的模型：

图片模型：

- `gpt-image`
- `gpt-image-landscape`
- `gpt-image-portrait`

标准视频模型：

- `sora2-landscape-10s`
- `sora2-portrait-10s`
- `sora2-landscape-15s`
- `sora2-portrait-15s`

视频续写模型：

- `sora2-extension-10s`
- `sora2-extension-15s`

需要 Pro 的视频模型：

- `sora2-landscape-25s`
- `sora2-portrait-25s`
- `sora2pro-landscape-10s`
- `sora2pro-portrait-10s`
- `sora2pro-landscape-15s`
- `sora2pro-portrait-15s`
- `sora2pro-landscape-25s`
- `sora2pro-portrait-25s`
- `sora2pro-hd-landscape-10s`
- `sora2pro-hd-portrait-10s`
- `sora2pro-hd-landscape-15s`
- `sora2pro-hd-portrait-15s`

提示词增强模型：

- `prompt-enhance-short-10s`
- `prompt-enhance-short-15s`
- `prompt-enhance-short-20s`
- `prompt-enhance-medium-10s`
- `prompt-enhance-medium-15s`
- `prompt-enhance-medium-20s`
- `prompt-enhance-long-10s`
- `prompt-enhance-long-15s`
- `prompt-enhance-long-20s`

角色创建模型：

- `avatar-create`

### 管理接口

#### 认证方式

后台大多数 `/api/*` 接口要求管理员 Token：

```http
Authorization: Bearer <admin-token>
```

登录接口：

- `POST /api/login` 不需要管理员 Token
- 登录成功后返回的 Token 存在浏览器 `localStorage`
- 当前服务重启后，这个管理员 Token 会失效

#### 1. 认证与会话

| 接口 | 作用 | 主要字段 | 关键返回 |
|---|---|---|---|
| `POST /api/login` | 管理员登录 | `username` `password` | `success` `token` |
| `POST /api/logout` | 退出登录 | Header 中管理员 Token | `success` |

#### 2. Token 管理

| 接口 | 作用 | 主要字段 |
|---|---|---|
| `GET /api/tokens` | 获取全部 Token 与统计 | 无 |
| `POST /api/tokens` | 新增 Token | `token` `st` `rt` `client_id` `proxy_url` `remark` `image_enabled` `video_enabled` `image_concurrency` `video_concurrency` |
| `PUT /api/tokens/{token_id}` | 更新 Token | 与新增类似 |
| `DELETE /api/tokens/{token_id}` | 删除 Token | 路径参数 |
| `POST /api/tokens/{token_id}/test` | 测试 Token 有效性 | 路径参数 |
| `POST /api/tokens/{token_id}/enable` | 启用 Token | 路径参数 |
| `POST /api/tokens/{token_id}/disable` | 禁用 Token | 路径参数 |
| `PUT /api/tokens/{token_id}/status` | 设置启用状态 | `is_active` |

`GET /api/tokens` 当前会返回比较完整的账号信息，包括：

- Token 本身
- ST、RT、`client_id`、`proxy_url`
- 订阅信息 `plan_type` `plan_title`
- Sora2 信息 `sora2_supported` `sora2_remaining_count` 等
- 功能开关与并发限制
- `is_expired` 与 `disabled_reason`

#### 3. Token 转换、导入与批量操作

| 接口 | 作用 | 主要字段 |
|---|---|---|
| `POST /api/tokens/st2at` | ST 转 AT | `st` |
| `POST /api/tokens/rt2at` | RT 转 AT | `rt` `client_id` |
| `POST /api/tokens/import` | 批量导入 Token | `tokens[]` `mode` |
| `POST /api/tokens/import/pure-rt` | 纯 RT 批量导入 | `refresh_tokens[]` `client_id` `proxy_url` |
| `POST /api/tokens/batch/test-update` | 批量测试并更新状态 | `token_ids[]` 可选 |
| `POST /api/tokens/batch/enable-all` | 批量启用 | `token_ids[]` 可选 |
| `POST /api/tokens/batch/delete-disabled` | 删除禁用 Token | `token_ids[]` 可选 |
| `POST /api/tokens/batch/disable-selected` | 批量禁用 | `token_ids[]` |
| `POST /api/tokens/batch/delete-selected` | 批量删除 | `token_ids[]` |
| `POST /api/tokens/batch/update-proxy` | 批量修改代理 | `token_ids[]` `proxy_url` |

`/api/tokens/import` 当前支持的导入模式：

- `offline`
- `at`
- `st`
- `rt`

纯 RT 模式走独立接口 `/api/tokens/import/pure-rt`。

#### 4. 系统配置接口

| 接口 | 作用 |
|---|---|
| `GET /api/admin/config` | 获取后台配置 |
| `POST /api/admin/config` | 更新后台配置 |
| `POST /api/admin/password` | 修改管理员用户名或密码 |
| `POST /api/admin/apikey` | 更新 API Key |
| `POST /api/admin/debug` | 开关调试日志 |
| `GET /api/proxy/config` | 获取代理配置 |
| `POST /api/proxy/config` | 保存代理配置 |
| `POST /api/proxy/test` | 测试代理连通性 |
| `GET /api/watermark-free/config` | 获取无水印配置 |
| `POST /api/watermark-free/config` | 保存无水印配置 |
| `GET /api/cache/config` | 获取缓存配置 |
| `POST /api/cache/config` | 更新缓存超时 |
| `POST /api/cache/base-url` | 更新缓存基址 |
| `POST /api/cache/enabled` | 启用或关闭缓存 |
| `GET /api/generation/timeout` | 获取生成超时 |
| `POST /api/generation/timeout` | 更新生成超时 |
| `GET /api/token-refresh/config` | 获取自动刷新配置 |
| `POST /api/token-refresh/enabled` | 开关自动刷新 |
| `GET /api/call-logic/config` | 获取调用逻辑配置 |
| `POST /api/call-logic/config` | 更新调用逻辑配置 |
| `GET /api/pow/config` | 获取 POW 服务配置 |
| `POST /api/pow/config` | 更新 POW 服务配置 |
| `GET /api/pow-proxy/config` | 兼容读取 POW 代理配置 |
| `POST /api/pow-proxy/config` | 兼容更新 POW 代理配置 |

典型错误来源：

- 401：管理员 Token 缺失或失效
- 400：参数校验失败、代理地址错误、超时值超界、调用模式非法
- 500：数据库或运行时内部错误

#### 5. 统计、日志与任务运维

| 接口 | 作用 |
|---|---|
| `GET /api/stats` | 聚合系统统计 |
| `GET /api/logs` | 获取最近请求日志 |
| `DELETE /api/logs` | 清空请求日志 |
| `POST /api/tasks/{task_id}/cancel` | 取消运行中的任务 |
| `GET /api/admin/logs/download` | 下载 `logs.txt` |

### 页面与静态资源

| 路径 | 作用 | 说明 |
|---|---|---|
| `GET /` | 入口页 | 返回 HTML 跳转到 `/login` |
| `GET /login` | 登录页 | 实际文件是 `static/login.html` |
| `GET /manage` | 后台主页 | 实际文件是 `static/manage.html` |
| `/static/*` | 静态资源 | 包含 `login.html`、`manage.html`、`generate.html`、`js/generate.js` |
| `/tmp/*` | 缓存文件访问 | 指向 `tmp/` 目录中的图片或视频缓存 |

前端相关的重要事实：

- `login.html` 与 `manage.html` 使用 Tailwind CDN。
- `generate.html` 是独立生成面板，前端自己填写 `baseUrl` 和 `apiKey`，并不依赖管理员 Token 去代理生成请求。
- `generate.html` 默认值是：
  - `baseUrl = http://127.0.0.1:8000`
  - `apiKey = Kong000`
- 这和后端默认配置 `han1234` 不一致，实际使用时应以后台当前 API Key 为准。

## 业务流程

### 1. 启动流程

1. 根目录 `main.py` 用 Uvicorn 启动 `src.main:app`。
2. `src/main.py` 创建 FastAPI、CORS、中间依赖对象。
3. 创建 `Database`、`TokenManager`、`ProxyManager`、`LoadBalancer`、`SoraClient`、`GenerationHandler`。
4. `startup_event` 读取 `config/setting.toml` 原始内容。
5. 如果数据库不存在，则创建表并把 TOML 初始值写入配置表。
6. 如果数据库已存在，则做迁移检查并补缺表缺列。
7. 从数据库回填管理员、缓存、生成超时、自动刷新、调用逻辑、POW 配置到运行时 `config`。
8. 从数据库加载全部 Token，初始化并发管理器。
9. 启动缓存清理后台任务。
10. 如果开启 `at_auto_refresh_enabled`，则启动 APScheduler，每天 `00:00` 批量刷新 Token。

### 2. Token 生命周期

1. 管理员通过后台新增、编辑、导入 Token，或通过 ST、RT 转换得到 AT。
2. `TokenManager` 解析 AT、读取用户信息、订阅信息、Sora2 支持状态和剩余额度。
3. Token 与其统计信息写入 SQLite。
4. 启动或更新后，并发额度会同步到 `ConcurrencyManager`。
5. 生成请求发生时，`LoadBalancer` 只从活跃 Token 池中选可用 Token。
6. 成功请求会记录 usage 与成功状态。
7. 连续错误超过阈值时，Token 会被自动禁用。
8. 遇到 401、`token_invalidated`、刷新失败等情况时，Token 会被标记为失效或禁用。
9. 自动刷新开启后，系统每日检查即将过期的 Token，并优先用 ST、其次用 RT 尝试刷新。

### 3. 生成主流程

1. 请求进入 `POST /v1/chat/completions`。
2. 系统记录客户端请求日志。
3. 从 `messages[-1]` 中提取 prompt、图片、视频或 remix 信息。
4. 校验模型是否存在于 `MODEL_CONFIG`。
5. 根据模型类型进入图片、视频、提示词增强、角色创建、Remix、分镜、视频续写等不同分支。
6. `LoadBalancer` 选择合适 Token。
7. 图片请求会检查 TokenLock 和图片并发额度。
8. 视频请求会检查视频能力、Sora2 支持、Sora2 冷却、Pro 订阅和视频并发额度。
9. 如有图片或视频上传需求，会先走上游上传流程。
10. `SoraClient` 负责生成 Sentinel Token 或 PoW 并请求上游接口。
11. 生成开始后会在数据库创建 `tasks` 记录，并写入 `request_logs`。
12. `GenerationHandler` 轮询 pending tasks 或 drafts，直到完成、失败或超时。
13. 如果开启缓存，会把媒体下载到 `tmp/` 并返回本地 URL。
14. 如果是视频且启用了无水印模式，生成完成后还会走"发布 -> 解析 -> 可选缓存 -> 删除发布内容"的附加流程。
15. 最终结果通过 SSE 或 JSON 返回给客户端。

### 4. 特殊分支

提示词增强：

- 模型名是 `prompt-enhance-*`
- 直接调用 `enhance_prompt`
- 支持流式与非流式返回文本

分镜：

- 不是独立外部接口
- 当前通过 prompt 中的 `[5.0s]` 这种语法自动识别
- 识别后转换为 storyboard 格式，调用 `/nf/create/storyboard`

Remix：

- 可显式传 `remix_target_id`
- 也可在 prompt 中包含 `s_xxx` 自动提取
- 会先清洗 prompt，再调用上游 Remix

角色创建：

- 使用 `avatar-create`
- 可通过视频或 `gen_xxx` 走角色创建流程
- 会经历上传视频、轮询 cameo、下载头像、上传头像、finalize、公开角色等步骤

视频续写：

- 使用 `sora2-extension-10s` 或 `sora2-extension-15s`
- prompt 中必须包含 `gen_xxx`
- 走 `/project_y/profile/drafts/{generation_id}/long_video_extension`

无水印模式：

- 视频完成后可额外发布为 post，再解析出无水印地址
- 支持 `third_party` 与 `custom` 两种解析方式
- 失败时是否回落到原视频，取决于 `fallback_on_failure`

### 5. 并发与负载

1. 默认模式下，Token 选择是随机的。
2. `call_mode = polling` 时，会切换为轮询选择。
3. 图片生成有两层限制：
   - TokenLock 单 Token 锁
   - `image_concurrency` 并发额度
4. 视频生成有三层限制：
   - `video_enabled`
   - `video_concurrency`
   - `sora2_supported` 与冷却或剩余额度
5. Pro 模型还要求 `plan_type == "chatgpt_pro"`。
6. 视频成功后会刷新 Sora2 剩余额度；当剩余额度过低时，系统会自动设置冷却并禁用 Token。

## 部署方式

### 1. 本地裸机部署

适合开发调试。

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

特点：

- 最直接
- 便于单步调试
- 若本机未安装 Playwright 依赖或 Chromium，PoW 浏览器流程可能受影响

### 2. 标准 Docker Compose 部署

适合单机运行。

```bash
docker-compose up -d
docker-compose logs -f
```

特点：

- 使用的是预构建镜像 `thesmallhancat/sora2api:latest`
- 不走本地 `Dockerfile build`
- 自动挂载数据库目录和配置文件
- 设置了 `TZ=Asia/Shanghai` 与 `TIMEZONE_OFFSET=8`

### 3. WARP 代理模式部署

适合需要通过 WARP 出口访问上游的场景。

```bash
docker-compose -f docker-compose.warp.yml up -d
docker-compose -f docker-compose.warp.yml logs -f
```

特点：

- 增加 `warp` 服务
- 主服务配置文件切换为 `config/setting_warp.toml`
- 默认代理地址是 `socks5://warp:1080`

### 4. Dockerfile 的角色

当前仓库有 `Dockerfile`，已确认它会：

- 基于 `python:3.11-slim`
- 安装 Playwright 运行依赖
- 执行 `playwright install chromium`
- 以 `python main.py` 启动

但当前提供的 `docker-compose*.yml` 都使用远程镜像，不直接 `build` 本仓库源码。

## 常见问题与排查

### 1. 没有可用 Token

常见报错：

- `No available tokens for image generation`
- `No available tokens for video generation`
- `No available Pro tokens`

优先排查：

- 后台 `GET /api/tokens` 是否还有活跃 Token
- Token 是否已禁用、已过期、冷却中
- 视频 Token 是否具备 `sora2_supported=true`
- 请求的是否是 Pro 模型
- `image_enabled` 或 `video_enabled` 是否被关闭
- 并发额度是否已耗尽

### 2. 401 或 `token_invalidated`

表现：

- Token 测试失败
- 请求过程中出现 401
- Token 被自动禁用或标记过期

排查点：

- 使用 `/api/tokens/{id}/test` 重新检查
- 看是否启用了 `auto_disable_on_401`
- 确认 ST 或 RT 是否可用于刷新
- 查看 `tokens.is_expired` 与 `disabled_reason`

### 3. `unsupported_country_code`

表现：

- 上游提示国家或地区不可用

排查点：

- 当前出口是否受限
- 是否需要启用全局代理或 WARP
- Token 所在账号地区是否受限

### 4. 代理测试失败

表现：

- `/api/proxy/test` 返回失败
- 上游请求连接不上或 TLS 异常

排查点：

- 代理 URL 协议是否正确，例如 `http://`、`socks5://`
- 用的是全局代理、Token 代理，还是图片上传专用代理
- WARP 模式下 `warp` 容器是否正常启动
- 生成面板用的 `baseUrl` 是否指向了正确服务实例

### 5. PoW 或 Sentinel 失败

表现：

- 403 或 429 获取 `oai-did` 失败
- Sentinel Token 生成失败
- `nf/create` 报 400、invalid sentinel 等错误

排查点：

- Playwright 或 Chromium 是否安装完整
- `pow_service.mode` 是 `local` 还是 `external`
- 外部 POW 服务的 `server_url`、`api_key` 是否正确
- 是否启用了 POW 代理
- 查看 `logs.txt` 中的 Sentinel 相关日志

### 6. 缓存 URL 不可访问

表现：

- 返回了 `/tmp/...` 地址但客户端打不开
- 返回的 URL 域名不对

排查点：

- 是否启用了缓存
- `cache.base_url` 是否正确
- 反向代理或公网地址是否和 `cache.base_url` 一致
- `tmp/` 是否已被正确映射和暴露

### 7. 无水印模式失败或回落

表现：

- 视频生成成功，但无水印环节失败
- 自动回落到原始视频
- 或直接标记任务失败

排查点：

- `watermark_free_enabled` 是否开启
- `parse_method` 是 `third_party` 还是 `custom`
- `custom_parse_url` 和 `custom_parse_token` 是否正确
- `fallback_on_failure` 是否开启

### 8. 任务超时

表现：

- 最终返回 `Generation exceeded ... seconds limit`

排查点：

- `image_timeout` 或 `video_timeout`
- `poll_interval`
- 上游是否长时间无结果
- 当前 Token 是否网络不稳定
- 日志表和 `logs.txt` 中是否能看到持续进度

### 9. 后台登录态丢失

表现：

- 服务重启后必须重新登录

原因：

- 管理员会话 Token 存在进程内存里，不在数据库中

### 10. 日志丢失

表现：

- 重启后 `logs.txt` 为空

原因：

- `DebugLogger` 启动时会主动删除旧的 `logs.txt` 再重建

### 11. 生成面板 API Key 不一致

表现：

- 打开生成面板直接请求失败

原因：

- `static/generate.html` 默认填的是 `Kong000`
- 后端默认初始化 API Key 来自 `config/setting.toml`，默认是 `han1234`
- 如果数据库里已经改过 API Key，应以后台配置实际值为准

## 维护建议

- 优先把 SQLite 看作"真实配置源"，尤其是管理员配置、代理、缓存、生成超时、自动刷新、无水印、POW 和调用逻辑。
- 升级前先备份 `data/hancat.db`。
- 定期通过后台批量测试 Token，刷新账号订阅和 Sora2 状态。
- 对 Pro 模型单独维护一组 Pro Token，避免普通 Token 被无意义轮询。
- 调试时再开启 `debug`，排障结束后关闭；`logs.txt` 会包含详细请求和响应信息。
- 定期清理或观察 `tmp/` 目录增长情况，尤其在启用缓存时。
- 如果要改时区展示，优先检查环境变量 `TIMEZONE_OFFSET`，不要只改 `setting.toml`。
- 当前前后端存在接口漂移迹象，建议优先对齐 `manage.html`、`generate.js` 与 `admin.py`、`routes.py`。
- 建议补充自动化测试，至少覆盖：
  - `POST /v1/chat/completions` 的请求解析
  - Token 选择逻辑
  - 配置读写与启动迁移
  - 管理接口的关键配置更新流程
- 建议检查依赖清单中未明显使用的库，确认是否为历史遗留。

## 待确认与已知差异

### 待确认

- 前端引用了 `/api/characters` 与 `/api/characters/{id}`，当前后端路由中未找到对应实现。
- 前端引用了 `/api/download/batch-zip`，当前后端路由中未找到对应实现。
- 前端引用了 `/v1/tasks/{id}/watermark/cancel`，当前后端路由中未找到对应实现。
- `static/manage.html` 引用了 `/static/favicon.ico`，当前仓库中未找到该静态资源。
- README 声明 Python `3.8+`，Docker 运行时是 Python `3.11`；本地最低兼容版本仍属待确认。
- FastAPI 默认 `/docs`、`/redoc` 是否对外开放，当前未实际运行验证；代码未显式关闭，但仍建议视为待确认。

### 已确认差异

- `config/setting.toml` 里有 `[timezone] timezone_offset`，但当前代码真实读取的是环境变量 `TIMEZONE_OFFSET`。
- `static/generate.html` 的默认 API Key 是 `Kong000`，与 `config/setting.toml` 的默认 `han1234` 不一致。
- 当前项目的"OpenAI 兼容"能力主要集中在 `/v1/models` 和 `/v1/chat/completions`，不是完整 OpenAI API 全量实现。
- 当前仓库未发现自动化测试目录或测试用例。

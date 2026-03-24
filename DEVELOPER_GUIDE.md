# Sora2API 开发者文档

> 说明：本文基于当前仓库的静态代码、配置文件、容器文件和前端资源整理，未执行会改写仓库状态的启动操作。凡是无法从当前仓库直接闭环确认的内容，统一标记为“待确认”。
>
> 标注规则：
> - “已确认”表示可以从当前仓库中的源码、配置或静态资源直接对应出来。
> - “待确认”表示需要实际启动、联调上游服务或验证部署环境后才能下结论。
> - “前后端漂移”表示前端页面引用了某个接口或静态资源，但当前后端代码或仓库文件中未找到对应实现。

## 项目概述

Sora2API 是一个基于 FastAPI 的单服务项目，目标是把 Sora 相关图片、视频和提示词增强能力统一包装成开发者可直接调用的 HTTP 服务，同时提供一个自带的管理后台。

从当前代码实现看，项目对外主要暴露两类能力：

- OpenAI 风格接口：`GET /v1/models`、`POST /v1/chat/completions`
- 管理接口：`/api/*`，覆盖登录、Token 管理、代理配置、缓存配置、日志查看、任务终止等后台能力

当前仓库显示它不是一个“纯转发网关”，而是带有完整运行时能力的服务：

- 多 Token 管理、轮询选择与图片/视频能力筛选
- 并发控制、锁控制、失败重试、401 自动禁用
- SQLite 持久化与启动时数据库迁移
- 代理、WARP、POW/Sentinel 相关能力
- 缓存文件落地和 `/tmp/*` 静态暴露
- 登录页、管理台和内嵌生成面板

重要入口与运行时文件：

| 项目 | 位置 | 说明 |
|---|---|---|
| 启动脚本 | `main.py` | 调用 `uvicorn.run("src.main:app", ...)` |
| 应用入口 | `src/main.py` | 组装 FastAPI、注册路由、初始化数据库和调度器 |
| 默认配置 | `config/setting.toml` | 首次启动初始化和部分运行时配置来源 |
| 数据库 | `data/hancat.db` | 运行时创建，默认 SQLite 主库 |
| 缓存目录 | `tmp/` | 运行时创建，并通过 `/tmp/*` 暴露 |
| 调试日志 | `logs.txt` | 调试日志文件，已确认会在启动时重建 |

## 如何快速理解并上手这个项目

如果你是第一次接手这个仓库，建议按下面顺序阅读：

1. 先看 `src/main.py`，理解应用初始化、依赖注入、静态资源挂载和启动/关闭流程。
2. 再看 `src/api/routes.py`，确认外部 OpenAI 兼容接口的输入格式和流式/非流式行为。
3. 再看 `src/services/generation_handler.py`，这里是生成主流程的编排中心。
4. 接着看 `src/services/sora_client.py`，这里封装了所有上游 Sora/ChatGPT 请求细节。
5. 再看 `src/services/token_manager.py`、`src/services/load_balancer.py`、`src/services/concurrency_manager.py`，理解 Token 生命周期和调度逻辑。
6. 最后看 `src/api/admin.py` 与 `src/core/database.py`，梳理后台能力与持久化结构。

如果只是想先跑通一个最小闭环：

1. 准备 Docker 或 Python 虚拟环境。
2. 启动服务：`python main.py` 或 `docker-compose up -d`。
3. 访问 `http://localhost:8000/`，页面会跳转到 `/login`。
4. 使用默认管理员凭据登录，进入后台导入至少一个可用 Token。
5. 先调用 `GET /v1/models`，再用 `POST /v1/chat/completions` 发起一次流式请求。

## 技术栈

| 类别 | 当前实现 | 说明 |
|---|---|---|
| Web 框架 | `fastapi==0.119.0` | 主服务框架 |
| ASGI 运行 | `uvicorn[standard]==0.32.1` | 启动 `src.main:app` |
| 数据建模 | `pydantic==2.10.4` | 请求、响应与配置模型 |
| 配置读取 | `tomli==2.2.1` | `src/core/config.py` 直接读取 `config/setting.toml` |
| HTTP 请求 | `curl-cffi==0.13.0` | 主要用于访问上游 Sora/ChatGPT 接口 |
| 数据库 | `aiosqlite==0.20.0` | SQLite 异步访问 |
| 认证相关 | `pyjwt==2.10.1`、`bcrypt==4.2.1` | Token/JWT 解析与后台密码能力 |
| 文件上传 | `python-multipart==0.0.20` | 支撑 multipart 相关请求 |
| 调度 | `APScheduler==3.10.4` | 每日批量刷新 Token |
| 时间处理 | `python-dateutil==2.8.2` | 订阅到期时间解析 |
| 浏览器流程 | `playwright==1.48.0` | Sentinel/POW 相关浏览器能力 |
| 随机资料 | `faker==24.0.0` | 用户名生成等辅助用途 |
| 前端 | 原生 HTML/CSS/JS | `static/login.html`、`manage.html`、`generate.html` |
| UI 样式 | Tailwind CDN | `login.html` 与 `manage.html` 通过 CDN 加载样式 |
| 容器镜像 | `python:3.11-slim` | `Dockerfile` 基础镜像 |
| WARP 侧车 | `caomingjun/warp` | `docker-compose.warp.yml` 中的代理容器 |

补充说明：

- README 声明 Python 版本为 `3.8+`，但 `Dockerfile` 使用 `python:3.11-slim`。这两条信息是已确认存在的文档差异；“本地最低兼容版本”仍属待确认。
- 依赖清单里还存在 `python-dotenv`、`pydantic-settings`、`toml`。当前主流程中未看到明显调用链，具体用途待确认。

## 目录结构

### 仓库主结构

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

| 路径 | 作用 |
|---|---|
| `config/` | TOML 配置模板目录，包含标准模式和 WARP 模式 |
| `config/setting.toml` | 默认配置文件，首次启动时用于初始化数据库配置 |
| `config/setting_warp.toml` | WARP 模式下会被挂载为运行时 `setting.toml` |
| `src/main.py` | FastAPI 应用创建、依赖注入、静态资源挂载、启动/关闭流程 |
| `src/api/routes.py` | OpenAI 兼容接口层 |
| `src/api/admin.py` | 管理后台接口层 |
| `src/core/config.py` | 读取 `setting.toml`，并维护进程内配置对象 |
| `src/core/database.py` | SQLite 初始化、迁移和 CRUD |
| `src/core/models.py` | Pydantic 数据模型 |
| `src/core/auth.py` | API Key 与管理员登录鉴权 |
| `src/core/logger.py` | 调试日志输出到 `logs.txt` |
| `src/services/` | 业务核心层，覆盖 Token、代理、生成、缓存、并发、负载均衡、POW 等 |
| `src/utils/timezone.py` | 时间与时区工具 |
| `static/login.html` | 登录页 |
| `static/manage.html` | 管理后台主页，内部嵌入生成面板 |
| `static/generate.html` | 生成面板页面 |
| `static/js/generate.js` | 生成面板核心脚本 |

### 运行期目录和文件

| 路径 | 来源 | 说明 |
|---|---|---|
| `data/` | 运行时创建 | 存放 SQLite 数据 |
| `data/hancat.db` | 运行时创建 | 主数据库 |
| `tmp/` | 启动时创建 | 缓存图片/视频文件，并通过 `/tmp/*` 暴露 |
| `logs.txt` | 启动时创建 | 调试日志文件；已确认会在启动时删除旧文件并重建 |

当前仓库未发现以下常见工程文件：

- `tests/` 目录
- `pytest.ini`
- `pyproject.toml`
- 前端构建配置文件

## 安装与运行方式

### 前置条件

- Docker 与 Docker Compose，或
- Python 虚拟环境与 `pip`

### 方式一：本地运行

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

Windows 下激活虚拟环境命令为：

```powershell
venv\Scripts\activate
```

### 方式二：标准 Docker Compose

```bash
docker-compose up -d
docker-compose logs -f
```

### 方式三：WARP 代理模式

```bash
docker-compose -f docker-compose.warp.yml up -d
docker-compose -f docker-compose.warp.yml logs -f
```

### Dockerfile 的角色

`Dockerfile` 做了几件关键事情：

1. 以 `python:3.11-slim` 为基础镜像。
2. 预设 `TZ=Asia/Shanghai` 与 `TIMEZONE_OFFSET=8`。
3. 安装 Playwright/Chromium 所需系统依赖。
4. 安装 Python 依赖并执行 `playwright install chromium`。
5. 以 `python main.py` 启动服务。

### 首次启动与后续启动的区别

当前启动逻辑在 `src/main.py` 中可确认如下：

1. 读取 `config/setting.toml` 到内存配置对象。
2. 判断 `data/hancat.db` 是否存在。
3. 首次启动时，创建数据库表并用 TOML 中的配置初始化数据库。
4. 非首次启动时，检查并迁移数据库缺失表或字段。
5. 之后再从数据库读出管理员配置、缓存配置、生成超时、Token 刷新、调用逻辑、POW 服务等信息，回写到进程内配置对象。

这意味着一个重要结论：

- `setting.toml` 更像“首次启动初始化来源”和“部分静态配置来源”。
- 多数后台可编辑配置在首次启动后会转移到 SQLite 表中，后续以数据库为主。

## 配置说明

### 配置来源与生效方式

| 来源 | 当前角色 | 典型条目 |
|---|---|---|
| `config/setting.toml` | 首次启动初始化来源；也是部分运行时只读配置来源 | 管理员默认值、API Key、基础超时、代理默认值 |
| SQLite 配置表 | 首次启动后多数后台配置的真实来源 | `admin_config`、`proxy_config`、`cache_config` 等 |
| 进程内 `config` 对象 | 启动后承载当前有效值；部分值由数据库回写 | API Key、缓存超时、生成超时、调用逻辑 |
| 环境变量 | 少量运行时配置入口 | `TZ`、`TIMEZONE_OFFSET` |

### 重要结论

- `server.host`、`server.port` 由 `config/setting.toml` 提供，当前未看到后台动态修改入口。
- `sora.base_url`、`sora.timeout`、`sora.max_retries`、`sora.max_poll_attempts` 当前仍由文件配置提供。
- 管理员账号、API Key、缓存、代理、生成超时、自动刷新、调用逻辑、POW 服务等在启动后会优先从数据库加载。
- `src/utils/timezone.py` 实际读取的是环境变量 `TIMEZONE_OFFSET`，不是 `setting.toml` 的 `[timezone] timezone_offset`。这一点已确认存在配置表述与实际生效链路差异。

### `config/setting.toml` 结构

| 段落 | 作用 |
|---|---|
| `[global]` | 初始 API Key、管理员用户名和密码 |
| `[sora]` | 上游基础地址、超时、重试和轮询参数 |
| `[server]` | 服务监听地址和端口 |
| `[debug]` | 调试日志开关与脱敏行为 |
| `[cache]` | 缓存开关、超时和外部可访问 base URL |
| `[generation]` | 图片/视频超时 |
| `[admin]` | 错误阈值、失败重试、401 自动禁用 |
| `[proxy]` | 全局代理和图片上传代理 |
| `[watermark_free]` | 无水印相关解析策略 |
| `[token_refresh]` | Access Token 自动刷新开关 |
| `[call_logic]` | 调用模式与轮询间隔 |
| `[timezone]` | 时区偏移说明；当前实际生效链路待确认 |
| `[pow_service]` | POW 计算模式、外部服务、代理配置 |

### 数据库存储的配置表

以下配置表可以从 `src/core/database.py` 直接确认：

| 表名 | 用途 |
|---|---|
| `admin_config` | 管理员账号、API Key、错误阈值、任务重试、401 自动禁用 |
| `proxy_config` | 全局代理与图片上传代理 |
| `watermark_free_config` | 无水印配置 |
| `cache_config` | 缓存开关、缓存超时、缓存 base URL |
| `generation_config` | 图片和视频超时 |
| `token_refresh_config` | 自动刷新 Access Token 开关 |
| `call_logic_config` | 调用模式和轮询间隔 |
| `pow_proxy_config` | 旧的 POW 代理配置表 |
| `pow_service_config` | 当前 POW 服务模式、外部服务地址、密钥与代理 |

除配置表外，还存在以下业务表：

- `tokens`
- `token_stats`
- `tasks`
- `request_logs`

## 核心模块解析

### 1. `Database`

`src/core/database.py` 是持久化核心，主要负责：

- 首次启动建表和初始化配置
- 老库迁移与字段补齐
- Token、任务、日志、后台配置、reference 主库与 reference 绑定的 CRUD
- 在后台接口和启动流程之间充当状态中枢

当前数据库层不仅存 Token，也存管理后台配置，因此它更像项目的“运行时状态中心”。

### 2. `Config`

`src/core/config.py` 的作用不是简单“读一次文件”，而是：

- 在进程启动时读取 `config/setting.toml`
- 对外暴露属性访问器，例如 `api_key`、`cache_timeout`、`call_logic_mode`
- 在启动过程中接收数据库回写，把“数据库真实值”放回内存配置对象

这也解释了为什么文档维护时必须区分“文件配置”和“数据库配置”。

### 3. `TokenManager`

`src/services/token_manager.py` 负责 Token 生命周期管理，当前能从代码中确认的职责包括：

- 解析 Access Token/JWT
- 拉取用户信息、订阅信息、Sora2 邀请码和剩余次数
- ST 转 AT、RT 转 AT
- 新增、更新、删除 Token
- 测试 Token 可用性
- 记录使用次数、错误次数和成功次数
- 到期或冷却后刷新相关状态
- 批量刷新所有 Token

它是后台 Token 面板和生成链路之间的桥梁。

### 4. `LoadBalancer`

`src/services/load_balancer.py` 的职责比较集中：

- 从可用 Token 中按轮询选择一个候选 Token
- 根据场景筛选图片/视频能力
- 按需要求 Pro Token
- 和 `ConcurrencyManager` 配合，避免超过单 Token 并发限制

### 5. `ConcurrencyManager`

`src/services/concurrency_manager.py` 维护每个 Token 的图片/视频并发配额，核心能力有：

- 初始化各 Token 的并发限制
- 判断当前是否还能接收图片或视频任务
- 获取和释放图片/视频并发槽位
- 返回剩余配额
- 当 Token 被修改时重置其并发额度

### 6. `TokenLock`

`src/services/token_lock.py` 是更细粒度的“排它锁”工具：

- 为特定 Token 加锁/解锁
- 检查 Token 是否被锁定
- 清理过期锁

它和 `ConcurrencyManager` 解决的是不同问题：前者偏互斥，后者偏容量。

### 7. `ProxyManager`

`src/services/proxy_manager.py` 负责代理选择和代理配置访问：

- 决定请求是否走显式传入代理、Token 级代理或全局代理
- 单独处理图片上传代理配置
- 读取和更新代理配置表

在上游请求、图片上传和外部 POW 服务场景里都会被使用。

### 8. `FileCache`

`src/services/file_cache.py` 负责媒体缓存与清理：

- 将上游媒体下载到 `tmp/`
- 生成稳定的缓存文件名
- 提供定时清理过期缓存的后台任务
- 在启动/关闭时由 `src/main.py` 负责启动和关闭清理循环

如果开启缓存，对外返回的媒体 URL 会依赖这里落盘的文件。

### 9. `ReferenceService`

`src/services/reference_service.py` 负责本地 reference 主库和按账号自动同步：

- 管理本地 `reference_id`、名称、描述、类型、源图路径和哈希
- 管理 `reference_id + token_id -> upstream ref_xxx` 绑定
- 校验 `references` 数量、类型和存在性
- 在视频提交前，把本地 `reference_id` 解析成上游 `ref_xxx`
- 按观察文档中的顺序执行 `file/upload -> references/create|update -> nf/create`

这里是本次 `references` 能力的核心收口点。

### 10. `SoraClient`

`src/services/sora_client.py` 是上游请求层，职责最重：

- 统一封装访问 Sora/ChatGPT 上游接口的请求
- 处理 Sentinel/POW 相关流程
- 上传图片、上传角色视频、生成图片/视频
- 上传 reference 图片、创建/编辑/删除 upstream references
- 拉取图片任务、视频草稿、任务状态
- 执行无水印相关请求
- 创建角色、设置角色公开、删除角色
- 执行 Remix、视频续写和分镜生成
- 执行提示词增强

如果你要排查“为什么请求上游失败”，这里通常是重点入口。

### 11. `GenerationHandler`

`src/services/generation_handler.py` 是整个业务流的编排中心，当前可确认的关键职责有：

- 解析模型与请求输入
- 区分图片、视频、角色创建、提示词增强、Remix、续写等分支
- 从 prompt 中提取 Remix ID、风格标记和 generation ID
- 选择 Token、控制并发、记录日志、处理失败重试
- 轮询任务状态并格式化 OpenAI 风格流式/非流式响应

如果只读一个业务文件，优先读这个文件。

## 接口说明

### 一、OpenAI 兼容接口

当前代码中已确认存在的公开接口只有两条：

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/v1/models` | 返回当前 `MODEL_CONFIG` 中可用的模型列表 |
| `POST` | `/v1/chat/completions` | 统一承接图片、视频、角色、Remix、续写、提示词增强请求 |

`POST /v1/chat/completions` 的关键输入特征：

- `messages[-1].content` 支持字符串，或 OpenAI 风格的多模态数组。
- 多模态数组支持 `text`、`image_url`、`video_url`。
- 顶层还支持 `image`、`video`、`remix_target_id`、`references` 这些扩展字段。
- 如果 prompt 中出现 `s_xxx...` 形式的 Remix ID，后端会尝试自动提取。

`references` 相关约束：

- 字段类型：`string[]`
- 字段含义：Sora2API 本地 `reference_id` 数组，不是上游 `ref_xxx`
- 数量限制：去重后最多 `5` 个
- 支持范围：仅普通视频生成与分镜生成
- 明确不支持：图片、提示词增强、avatar-create、Remix、长视频续写

`references` 的上游字段结构和时序实现依据必须以 `C:/Codex/apps/Sora2Api/sora_reference_observation.md` 为准。

已确认的关键结论：

- 上游 `POST /backend/nf/create` 不接收顶层 `references`
- 选中的 reference 会折叠进 `inpaint_items`
- 单项结构固定为 `{ "kind": "reference", "reference_id": "<upstream_ref>" }`
- create/edit reference 时序是 `POST /backend/project_y/file/upload` 先拿 `asset_pointer`，再调用 `/backend/project_y/references/create|{id}`

当前支持的模型类型可从 `MODEL_CONFIG` 直接看出，主要包括：

- 图片模型：`gpt-image*`
- 视频模型：`sora2*`、`sora2pro*`、`sora2pro-hd*`
- 视频续写模型：`sora2-extension-*`
- 提示词增强模型：`prompt-enhance-*`
- 角色创建模型：`avatar_create` 类型模型

需要特别注意的行为差异：

- 对视频、Remix、角色创建等分支，`stream=false` 并不等于“同步拿到最终媒体”，当前更接近“可用性检查”或非流式包装。
- 该项目的“OpenAI 兼容”主要集中在接口形状，不等于完整实现 OpenAI 全量 API。

### 二、管理后台接口

`src/api/admin.py` 中已确认存在的接口族如下：

- 认证：`/api/login`、`/api/logout`
- Token 管理：`/api/tokens`、`/api/tokens/st2at`、`/api/tokens/rt2at`
- Token 批量操作：`/api/tokens/batch/*`
- Reference 主库：`/api/references`、`/api/references/{reference_id}`
- 管理员配置：`/api/admin/config`、`/api/admin/password`、`/api/admin/apikey`
- 调试开关：`/api/admin/debug`
- 代理配置与测试：`/api/proxy/config`、`/api/proxy/test`
- 无水印配置：`/api/watermark-free/config`
- 统计与日志：`/api/stats`、`/api/logs`、`/api/admin/logs/download`
- 缓存配置：`/api/cache/*`
- 生成超时：`/api/generation/timeout`
- Token 自动刷新：`/api/token-refresh/*`
- 调用逻辑：`/api/call-logic/*`
- POW 配置：`/api/pow-proxy/*`、`/api/pow/*`
- 任务终止：`/api/tasks/{task_id}/cancel`

### 三、页面与静态资源

当前在 `src/main.py` 中已确认存在的页面和静态资源挂载：

| 路径 | 来源 | 说明 |
|---|---|---|
| `/` | `src/main.py` | 返回 HTML 并重定向到 `/login` |
| `/login` | `static/login.html` | 登录页 |
| `/manage` | `static/manage.html` | 管理后台主页 |
| `/static/*` | `static/` | 前端静态资源 |
| `/tmp/*` | `tmp/` | 缓存媒体资源 |
| `/reference-assets/*` | `data/reference_assets/` | 本地 reference 源图预览资源 |

已确认当前没有单独的 `/generate` 路由；管理页通过 iframe 直接加载 `/static/generate.html`。

## 业务流程

### 1. 启动初始化流程

1. `main.py` 启动 `src.main:app`。
2. `src/main.py` 创建 FastAPI 应用、注入 `Database`、`TokenManager`、`ProxyManager`、`LoadBalancer`、`SoraClient`、`ReferenceService`、`GenerationHandler`。
3. 挂载 `static/`、`tmp/` 与 `reference-assets/`。
4. 启动事件中初始化数据库、执行迁移检查。
5. 从数据库加载管理员配置、缓存、生成超时、调用逻辑、POW 服务等运行参数。
6. 初始化并发管理器、启动缓存清理任务。
7. 若启用了 AT 自动刷新，则创建每日 00:00 调度任务。

### 2. Token 导入与刷新流程

1. 管理员通过后台新增 Token，或使用 ST/RT 导入接口转换后写入数据库。
2. `TokenManager` 拉取用户信息、订阅状态和 Sora2 能力，补齐 Token 元数据。
3. `Database` 写入 `tokens` 和统计表。
4. 后台可测试、启用、禁用、删除或批量处理 Token。
5. 如果开启自动刷新，调度器会周期性调用 `batch_refresh_all_tokens`。

### 3. 图片生成流程

1. 客户端调用 `POST /v1/chat/completions` 并指定图片模型。
2. `routes.py` 解析 `messages` 中的文字和图片输入。
3. `GenerationHandler` 根据模型类型判定为图片任务。
4. `LoadBalancer` 选择支持图片的 Token，并由并发管理器占用图片槽位。
5. `SoraClient` 上传图片（如果有）并调用上游图片生成接口。
6. 结果返回后根据缓存配置决定是否落盘到 `tmp/`，再格式化成 OpenAI 风格响应。

### 4. 视频生成流程

1. 客户端指定视频模型，输入可以是纯文本，也可以附带图片或视频。
2. `GenerationHandler` 判断是普通视频、图生视频、分镜生成还是其他视频变体。
3. `LoadBalancer` 选择支持视频能力且满足配额的 Token。
4. 如果请求带有本地 `references`，`ReferenceService` 会先校验数量和存在性，再针对选中的 token 做上游同步。
5. 同步路径遵循 `C:/Codex/apps/Sora2Api/sora_reference_observation.md` 中确认的时序：先 `file/upload` 拿 `asset_pointer`，再 `references/create|update`。
6. `SoraClient` 最终把解析好的 upstream `ref_xxx` 写进 `inpaint_items`，与已有 upload 项共存后提交 `nf/create`。
7. `GenerationHandler` 轮询任务进度，直到完成、失败或超时。
8. 成功后格式化为流式 chunk 或非流式响应。

### 5. 无水印流程

1. 视频任务完成后，如果后台开启无水印模式，编排层会继续走解析链路。
2. 当前支持第三方解析和自定义解析地址两种路径。
3. 如果无水印失败且允许回退，则返回带水印版本；否则直接报错。

### 6. 角色创建流程

1. 当请求落到 `avatar_create` 类型模型时，编排层进入角色分支。
2. 如果只有视频输入且没有 prompt，则走“仅创建角色”。
3. 如果有视频并附带 prompt，则先创建角色，再基于角色继续生成视频。
4. 代码中还支持从 generation ID 创建角色的分支。

### 7. Remix 流程

1. 客户端可以显式传 `remix_target_id`，也可以在 prompt 中附带 Sora 分享链接或 `s_xxx` ID。
2. `routes.py` 和 `GenerationHandler` 会尝试自动提取目标 ID。
3. `SoraClient` 基于该目标视频向上游发起 Remix 请求。
4. 后续仍走统一的任务轮询与响应格式化流程。

### 8. 视频续写流程

1. `MODEL_CONFIG` 中带 `video_extension` 模式的模型会触发续写分支。
2. `GenerationHandler` 从 prompt 中抽取 generation ID，清理无关标记后发起续写。
3. `SoraClient` 调用上游扩展接口，并按设定的 `extension_duration_s` 继续生成。
4. 最终仍通过统一轮询返回结果。

补充：

- 提示词增强走的是 `prompt-enhance-*` 分支，不会进入媒体生成轮询链路。
- 分镜生成是视频生成链路中的特殊 prompt 解析分支。

## 部署方式

### 标准部署建议

- 本地调试优先使用 `python main.py`，便于直接看堆栈和日志。
- 需要稳定运行或依赖 Playwright/Chromium 时，优先使用 Docker。
- 如果环境本身受地区限制，可考虑 `docker-compose.warp.yml`。

### 数据与挂载

部署时建议重点关注以下目录：

- `config/`
- `data/`
- `tmp/`
- `logs.txt`

其中 `data/` 决定是否会被视为首次启动；如果丢失数据库，服务会按首次启动重新初始化。

### 时区

容器默认设置：

- `TZ=Asia/Shanghai`
- `TIMEZONE_OFFSET=8`

如果你希望调整时间显示，当前更应该先检查环境变量 `TIMEZONE_OFFSET`，不要只修改 `setting.toml` 的 `[timezone]`。

### 代理与 WARP

- 标准代理由 `proxy_config` 和 Token 自带 `proxy_url` 共同决定。
- 图片上传代理与普通代理可以分开配置。
- WARP 模式是独立的 Docker Compose 方案，不是单个代码开关。
- POW 服务还可以有独立代理配置。

### 浏览器依赖

POW/Sentinel 相关流程依赖 Playwright/Chromium：

- Dockerfile 已显式安装系统依赖和 Chromium。
- 如果本地部署缺少这些依赖，相关上游能力可能失败。

## 常见问题与排查

### 1. 提示 “No available tokens...”

排查方向：

- 是否所有 Token 都被手动禁用或因错误自动禁用
- 是否都在冷却中
- 是否视频额度耗尽
- 是否并发槽位已满
- 是否 Token 已过期

### 2. 公共 API 返回 401 或 `token_invalidated`

排查方向：

- Token 是否已经失效
- 是否触发了 401 自动禁用
- 数据库中该 Token 的 `is_active`、`is_expired`、`disabled_reason` 是什么

### 3. 返回 `unsupported_country_code`

排查方向：

- 当前网络出口是否受地区限制
- 是否需要代理或 WARP
- 所选 Token 所在区域是否受限

### 4. 代理测试失败

排查方向：

- 全局代理 URL 是否正确
- Token 级 `proxy_url` 是否覆盖了全局代理
- 图片上传代理是否单独配置错误
- WARP 容器是否正常工作

### 5. Sentinel 或 POW 失败

排查方向：

- Playwright/Chromium 是否安装完整
- `pow_service.mode` 是 `local` 还是 `external`
- 外部 POW 服务的 `server_url`、`api_key` 是否正确
- 是否启用了 POW 专用代理
- 查看 `logs.txt` 中的相关日志

### 6. 缓存 URL 不可访问

排查方向：

- 是否开启了缓存
- `cache_base_url` 是否与实际反向代理地址一致
- `tmp/` 是否正确暴露
- 服务返回的是相对路径还是拼接后的公网地址

### 7. 无水印失败或回退

排查方向：

- `watermark_free_enabled` 是否开启
- `parse_method` 是否符合当前部署方式
- 自定义解析地址和令牌是否正确
- `fallback_on_failure` 是否开启

### 8. 任务超时

排查方向：

- `image_timeout` 或 `video_timeout`
- `poll_interval`
- 上游长时间无结果
- 当前 Token 网络不稳定
- 日志表和 `logs.txt` 中是否仍有进度

### 9. 管理后台重启后需要重新登录

当前原因已确认：

- 管理员会话 Token 保存在进程内存里，没有落库或使用外部会话存储。

### 10. `logs.txt` 重启后丢失

当前原因已确认：

- `src/core/logger.py` 在初始化 logger 时会先删除旧的 `logs.txt`，再重新创建。

### 11. 生成面板 API Key 不一致

当前原因已确认：

- `static/generate.html` 默认填的是 `Kong000`
- `config/setting.toml` 与数据库默认值是 `han1234`
- 如果数据库里已经改过 API Key，应以后台当前配置为准

## 已知差异、前后端漂移与待确认项

### 已确认差异

- `static/generate.html` 默认 API Key 为 `Kong000`，而默认后端初始化值为 `han1234`。
- `src/core/logger.py` 会在启动时删除旧的 `logs.txt` 再重建。
- `config/setting.toml` 中有 `[timezone] timezone_offset`，但 `src/utils/timezone.py` 实际读取的是环境变量 `TIMEZONE_OFFSET`。
- 当前“OpenAI 兼容”能力主要集中在 `/v1/models` 和 `/v1/chat/completions`，并不是完整 OpenAI API 集合。
- README 声明 Python `3.8+`，而容器运行时固定在 Python `3.11`。
- 数据库 `tokens` 表写入了 `username` 字段，但 `src/core/models.py` 中的 `Token` Pydantic 模型没有该字段，存在模型与表结构不一致。
- 当前仓库未发现自动化测试目录、`pytest.ini`、`pyproject.toml` 或前端构建配置。
- 当前没有单独的 `/generate` 路由，管理页通过 `/static/generate.html` 的 iframe 使用生成面板。

### 前后端漂移

以下引用可从前端静态资源中确认，但当前后端代码或仓库文件中未找到对应实现：

- `/api/characters`
- `/api/characters/{id}`
- `/api/download/batch-zip`
- `/v1/tasks/{id}/watermark/cancel`
- `/static/favicon.ico`

这些条目不应在对外文档中写成“已支持”。

### 待确认

- `python-dotenv`、`pydantic-settings`、`toml` 在当前主流程里的实际运行角色。
- FastAPI 默认 `/docs`、`/redoc` 是否在实际部署中对外开放；代码未显式关闭，但本文未做运行验证。
- README 所称的 Python `3.8+` 最低兼容版本是否真实可跑通。

## 维护建议

### 1. 先理顺“配置来源”

建议优先回答每个配置项属于哪一类：

- 只在 TOML 中生效
- 首次启动后转入数据库
- 仅内存有效
- 是否支持热更新

这个问题不先理顺，后续排障和重构都会比较痛苦。

### 2. 优先修复前后端接口漂移

当前最明显的漂移是：

- `/api/characters*`
- `/api/download/batch-zip`
- `/v1/tasks/{id}/watermark/cancel`
- `/static/favicon.ico`

建议要么补实现，要么删掉前端入口，避免误导使用者。

### 3. 统一数据库字段与模型定义

当前最明显的问题是 `tokens.username` 与 Pydantic `Token` 模型不一致。建议优先补齐或明确废弃字段，否则后续重构很容易埋雷。

### 4. 为关键流程补自动化测试

建议至少覆盖：

- `POST /v1/chat/completions` 的请求解析
- Token 选择逻辑
- 配置读写与启动迁移
- 管理接口关键配置更新流程

### 5. 收敛日志策略

当前项目同时存在：

- `request_logs` 表
- `logs.txt` 文件

建议明确：

- 哪些问题先查数据库日志
- 哪些问题先查文件日志
- `logs.txt` 是否需要保留历史或滚动切分

### 6. 明确公共 API 的产品语义

尤其要强调：

- `/v1/chat/completions` 在不同模型分支下的行为不完全相同
- 视频相关 `stream=false` 不是典型意义上的同步生成
- “OpenAI 兼容”更多是兼容请求/响应形状，而不是完整产品能力

### 7. 默认安全值只适合本地测试

当前默认配置中的：

- `admin / admin`
- `api_key = han1234`

都只适合本地试跑。部署时应立即修改，并同时评估：

- CORS 当前全开放
- 管理员会话仅在内存中保存

## 接手这个项目时的最小检查清单

1. 先看 `src/main.py`，确认启动链路、挂载目录和数据库初始化。
2. 登录后台前先确认 `config/setting.toml` 或数据库中的管理员账号和 API Key。
3. 导入一个可用 Token，并验证 `/api/tokens` 后台信息是否完整。
4. 调 `GET /v1/models` 确认模型列表可返回。
5. 用 `POST /v1/chat/completions` 先跑一个最简单的流式请求。
6. 如果失败，再按顺序排查代理、POW/Sentinel、缓存、无水印和自动刷新配置。

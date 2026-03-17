# Sora 观测接口速查

## 说明

- 本文基于两个时间点的真实样本整理：
  - `2026-03-08`：`/drafts` 页面初始化与被动抓包
  - `2026-03-13`：真实文生图 + 图生图主动观测
- 定位：第三方站点观测接口速查，不是项目内部 API 契约。
- 约束：不输出真实 token、cookie、session 或账号信息。
- 时效性：Sora / OpenAI / Cloudflare / Statsig 链路可能随时间变化，使用前应再做实样确认。

## 接口列表

| 分类 | Method Path | Host | 作用 | 鉴权 | 样本状态 |
| --- | --- | --- | --- | --- | --- |
| 页面文档 | `GET /drafts` | `sora.chatgpt.com` | 草稿页 HTML 文档 | `Cookie` | 先出现一次网络切换失败，后续 `200` |
| 会话 | `GET /api/auth/session` | `sora.chatgpt.com` | 读取当前 Web 会话与 `accessToken` | `Cookie` | `200` |
| 安全 | `POST /cdn-cgi/challenge-platform/.../oneshot/...` | `sora.chatgpt.com` / `chatgpt.com` | Cloudflare challenge/JSD 一次性校验 | `Cookie` | `200` |
| 安全 | `GET /backend-api/sentinel/frame.html` | `chatgpt.com` | Sentinel iframe 入口 | `Cookie` | `200` |
| 安全 | `POST /backend-api/sentinel/req` | `chatgpt.com` | 获取 anti-abuse token、Turnstile、PoW 参数 | `Cookie` | `200` |
| 账单/权限 | `GET /backend/billing/subscriptions` | `sora.chatgpt.com` | 返回订阅计划与周期状态 | `Authorization` + `Cookie` | `200` |
| 账号态 | `GET /backend/authenticate` | `sora.chatgpt.com` | 返回账号、国家支持、onboarding、`in_nf` | `Authorization` + `Cookie` | `200` |
| 模型/能力 | `GET /backend/models` | `sora.chatgpt.com` | 拉取模型清单 | `Authorization` + `Cookie` | `200` |
| 模型/能力 | `GET /backend/parameters` | `sora.chatgpt.com` | 返回分辨率、功能开关、生成能力参数 | `Authorization` + `Cookie` | `200` |
| 个人资料 | `GET /backend/project_y/v2/me` | `sora.chatgpt.com` | 返回 profile、手机号验证状态、邀请码等 | `Authorization` + `Cookie` | `200` |
| 草稿 | `GET /backend/project_y/profile/drafts/v2` | `sora.chatgpt.com` | 拉取 drafts 列表/条目元数据 | `Authorization` + `Cookie` | `200` |
| 初始化 | `GET /backend/project_y/initialize_async` | `sora.chatgpt.com` | 草稿页异步初始化数据 | `Authorization` + `Cookie` | `200` |
| 任务/图片 | `POST /backend/uploads` | `sora.chatgpt.com` | 图生图输入图上传，返回 `media_id` | `Authorization` + `Cookie` | `200` |
| 任务/图片 | `POST /backend/video_gen` | `sora.chatgpt.com` | 文生图 / 图生图任务提交 | `Authorization` + `Cookie` + `OpenAI-Sentinel-Token` + `OAI-Device-Id` | `200` |
| 任务/图片 | `GET /backend/v2/recent_tasks?limit=20` | `sora.chatgpt.com` | 图片任务运行态与终态真源 | `Authorization` + `Cookie` | `200` |
| 任务/额度 | `GET /backend/nf/pending/v2` | `sora.chatgpt.com` | 轮询待处理任务与生成进度 | `Authorization` + `Cookie` | `200` |
| 任务/额度 | `GET /backend/nf/check` | `sora.chatgpt.com` | 返回额度/速率检查结果 | `Authorization` + `Cookie` | `200` |
| 埋点 | `POST /v1/initialize` | `ab.chatgpt.com` | 实验/埋点初始化 | `Origin`、`Referer` | `204` |
| 埋点 | `POST /v1/rgstr` | `ab.chatgpt.com` | 事件注册/Statsig 上报 | `Origin`、`Referer` | `202` |
| 配置 | `GET /ces/v1/projects/oai/settings` | `chatgpt.com` | 返回埋点/Segment 配置 | `Origin`、`Referer` | `200` |
| 遥测 | `POST /ces/v1/b` | `chatgpt.com` | 批量事件上报 | `Origin`、`Referer` | `200` |
| 遥测 | `POST /cdn-cgi/rum` | `sora.chatgpt.com` | 页面性能与 RUM 上报 | `Cookie`、`Origin` | `204` |

## 鉴权总览

| 类型 | 字段名 | 位置 | 覆盖范围 | 是否必填 | 来源推测 | 失效风险 |
| --- | --- | --- | --- | --- | --- | --- |
| Bearer Token | `Authorization` | 请求头 | 业务 API：`/backend/*`、`/backend/project_y/*`、`/backend/nf/*` | 推测必填 | `/api/auth/session` 返回 `accessToken` 后由前端运行时注入 | token 轮换、登录态变化 |
| Session Cookie | `Cookie` | 请求头 | HTML、会话、Cloudflare、Sentinel、业务 API | 推测必填 | 浏览器会话与站点 cookie jar | session token / clearance 过期 |
| Anti-abuse Token | `OpenAI-Sentinel-Token` | 请求头 | 当前图片提交：`POST /backend/video_gen` | 当前主动样本必填 | 页面 `SentinelSDK.token(...)` 生成 | Sentinel 上下文过期、风控策略变化 |
| Device ID | `OAI-Device-Id` | 请求头 | 当前图片提交：`POST /backend/video_gen` | 当前主动样本必填 | 页面 / cookie 上下文派生 | 设备标识轮换、会话迁移 |
| CSRF Cookie | `__Host-next-auth.csrf-token` | `Cookie` 内 | 会话框架层 | 不完整样本 | 推测由 NextAuth 生成 | cookie 更新后失效 |

## 本地鉴权与双通道模型

- 页面通道以 `GET /api/auth/session` 为唯一可信的 `accessToken` 来源；本地任务提交与页面兜底都应从这里刷新鉴权上下文。
- Sora 业务接口调用应同时携带 `Authorization: Bearer <accessToken>` 与 `Cookie`；仅 Bearer 或仅 Cookie 都不应视为完整鉴权。
- 当前图片提交额外依赖 `OpenAI-Sentinel-Token` 与 `OAI-Device-Id`。这是 `2026-03-13` 主动成功样本的直接结论。
- proxy 通道应复用已持久化 auth context，至少包含 `access_token`、cookies、`oai-did`、`user-agent` 与代理绑定上下文。
- page 通道在 Playwright 已接管页面内按同一套鉴权语义发请求，并在需要时覆盖刷新 auth context。
- 推荐职责边界：优先 proxy 低成本轮询；遇到 `auth_context_incomplete`、`auth_context_invalid`、`proxy_binding_missing`、`cf_challenge` 等情况再切 page。

## 图片链路

| 模式 | 真实链路 | 关键差异 | 运行态/终态 |
| --- | --- | --- | --- |
| 文生图 | `POST /backend/video_gen -> GET /backend/v2/recent_tasks?limit=20` | `operation=simple_compose`、`inpaint_items=[]` | `recent_tasks` 同时承担运行态与终态真源 |
| 图生图 | `POST /backend/uploads -> POST /backend/video_gen -> GET /backend/v2/recent_tasks?limit=20` | 多一步 `media_id` 上传，提交时 `operation=remix` | `recent_tasks` 同时承担运行态与终态真源 |

- 当前图片任务的真实状态序列是 `queued -> running -> succeeded`，不是页面外部实现里常见的抽象态 `processing`。
- `POST /backend/video_gen` 当前成功返回顶层 `id`，可直接视为 `task_id`。
- `GET /backend/v2/recent_tasks?limit=20` 当前仍以 `task_responses[].id` 匹配任务，并从 `generations[].url` 读取结果图地址。
- `progress_pct` 当前 Web 样本是 `0-1` 小数，且早期运行态可能为 `null`。
- 如果真实观测与 [`docs/reference/sora2api-task-chain.md`](./sora2api-task-chain.md) 不一致，以当前实样为准。

## 接口时序

1. 页面位于 `https://sora.chatgpt.com/explore` 时，会读取 `GET /api/auth/session` 并并发拉起账单、账号、模型、参数与 `nf/check` 初始化接口。
2. 文生图提交时，页面直接走 `POST /backend/video_gen`，返回 `task_id` 后轮询 `GET /backend/v2/recent_tasks?limit=20`，直到 `succeeded + generations[].url`。
3. 图生图提交时，页面先走 `POST /backend/uploads` 换取 `media_id`，再走 `POST /backend/video_gen`，随后同样只轮询 `recent_tasks` 到终态。
4. `/drafts` 与 `pending/v2` 依然是视频链路和草稿页的重要接口，但在本次图片主动样本里不是必经环节。

## 观察结论

- `GET /backend/nf/pending/v2` 仍是页面任务监控态的重要信号，但它不是当前图片生成的必要轮询接口。
- 图片链路当前可以明确落成两条：
  - 文生图：`video_gen -> recent_tasks`
  - 图生图：`uploads -> video_gen -> recent_tasks`
- `/api/auth/session` 是 Web 会话向业务 Bearer 令牌过渡的直接证据。
- Sora 业务数据接口稳定依赖 `Authorization: Bearer` 与 `Cookie`；当前图片提交还额外依赖 Sentinel token 和 device id。
- `/backend-api/sentinel/req` 返回 anti-abuse token、Turnstile、PoW 参数，说明页面初始化会进入安全校验链路；只是 warm session 不一定每次重放都重新出现该请求。
- `/drafts` 导航阶段曾出现一次 `net::ERR_NETWORK_CHANGED` 后自动恢复，这应视为链路抖动，不应直接判定为业务失败。
- 当 `drafts/v2` 不可用或返回 `404/410` 时，应自动回退到 `drafts`；但对图片任务来说，`recent_tasks` 依然是当前更直接的运行态与终态真源。

## 关联证据

- 图片主动观测：[`docs/research/sora-image-capture-2026-03-13.md`](../research/sora-image-capture-2026-03-13.md)
- 被动抓包整理：[`docs/research/sora-packet-capture-2026-03-08.md`](../research/sora-packet-capture-2026-03-08.md)
- 上游链路基线：[`docs/reference/sora2api-task-chain.md`](./sora2api-task-chain.md)

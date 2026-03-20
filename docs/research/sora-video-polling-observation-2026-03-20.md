# Sora 视频真实轮询观测与 PollingClient 差异

## 说明

- 观测日期：`2026-03-20`
- 观测方式：附着已登录 NSTBrowser profile，使用 Playwright CDP 全程监听页面真实出网
- 观测 profile：`6437789e-6489-4ace-9903-5fafcd574f57`
- 观测页面：`https://sora.chatgpt.com/explore`
- 观测目标：验证视频生成链路里，浏览器真实 `submit -> pending -> drafts` 与当前 `PollingClient` 是否等价
- 产物来源：[`tmp/nst_live_listen_6437789e_20260320.jsonl`](../../tmp/nst_live_listen_6437789e_20260320.jsonl)
- 安全边界：本文不记录可复用 AT、ST、RT、Cookie 或完整 Sentinel token，仅保留脱敏结构化信息

## 当前实现状态

- 当前仓库已按本文结论收紧视频提交后链路：
  - 视频运行态轮询继续使用服务端 HTTP
  - 视频完成态终态查询已切到 `GET /backend/project_y/profile/drafts/v2?limit=15`
  - 任务级 `PollingContext` 已保存白名单页面头快照：
    - `page_url`
    - `referer`
    - `sec-fetch-*`
    - `sec-ch-*`
  - `pending/drafts` 轮询不再补 `openai-sentinel-token`
  - `401/403` 仅允许一次页面态 auth refresh 补偿
- 当前实现不再使用 `egress_probe`：
  - 视频 token 必须显式绑定 `browser_profile_id`
  - 视频 token 必须显式绑定从指纹浏览器 profile 同步来的 `proxy_url`
  - 视频轮询只允许使用 `token.proxy_url`，不再回退全局代理或直连

## 观测摘要

- 本次真实浏览器任务号：`task_01km4f6bzff73vjq6hgpk3d0pw`
- 提交时间：`2026-03-20 09:54:25`
- 页面真实 `submit` 接口：`POST https://sora.chatgpt.com/backend/nf/create`
- 页面真实运行态轮询接口：`GET https://sora.chatgpt.com/backend/nf/pending/v2`
- 页面真实完成态补扫接口：`GET https://sora.chatgpt.com/backend/project_y/profile/drafts/v2?limit=15`
- 页面最终草稿结果里已出现该任务的视频 URL

## 真实执行过程

### 1. 提交前安全请求

- `2026-03-20 09:54:24`
- 页面发起：`POST https://chatgpt.com/backend-api/sentinel/req`
- 页面上下文：
  - `origin=https://chatgpt.com`
  - `referer=https://chatgpt.com/backend-api/sentinel/frame.html?...`
  - `content-type=text/plain;charset=UTF-8`
- 结论：
  - 本次视频提交前，页面确实触发了 Sentinel 请求
  - 该请求发生在真正 `nf/create` 之前

### 2. 真实视频提交

- `2026-03-20 09:54:25`
- 页面发起：`POST https://sora.chatgpt.com/backend/nf/create`
- 响应：`200`
- 真实请求头包含：
  - `Authorization`
  - 完整 `Cookie`
  - `User-Agent=Chrome/143`
  - `oai-device-id`
  - `openai-sentinel-token`
  - `origin=https://sora.chatgpt.com`
  - `referer=https://sora.chatgpt.com/explore`
  - `sec-fetch-*`
  - `sec-ch-*`
- 真实请求体关键字段：
  - `kind=video`
  - `prompt=13231212312321`
  - `orientation=portrait`
  - `size=small`
  - `n_frames=300`
  - `model=sy_8`
  - `title=null`
  - `project_config=null`
  - `trim_config=null`
  - `metadata=null`
  - `storyboard_id=null`
- 响应体关键字段：
  - `id=task_01km4f6bzff73vjq6hgpk3d0pw`
  - `task_type=video_gen`

### 3. 真实 pending 轮询

- 页面从 `09:54:26` 开始轮询 `GET /backend/nf/pending/v2`
- 轮询间隔：约 `2-3 秒`
- 页面轮询头稳定包含：
  - `Authorization`
  - 完整 `Cookie`
  - `User-Agent=Chrome/143`
  - `oai-device-id`
  - `referer=https://sora.chatgpt.com/explore`
  - `sec-fetch-*`
  - `sec-ch-*`
- 页面轮询阶段未观察到：
  - `openai-sentinel-token`
  - 新的 `/api/auth/session`
- 任务状态序列：
  - `09:54:26 -> preprocessing`
  - `09:54:31 ~ 09:55:18 -> queued`
  - `09:55:20 ~ 09:55:25 -> running (progress_pct=0.1)`
  - `09:57:05 ~ 09:57:07 -> processing (progress_pct=1.0)`
  - `09:57:10 -> []`，任务从 pending 列表消失

### 4. 真实 drafts 完成态补扫

- `2026-03-20 09:57:14`
- 页面发起：`GET https://sora.chatgpt.com/backend/project_y/profile/drafts/v2?limit=15`
- 响应：`200`
- 请求头形态与 `pending_v2` 基本一致：
  - `Authorization`
  - 完整 `Cookie`
  - `User-Agent=Chrome/143`
  - `oai-device-id`
  - `referer=https://sora.chatgpt.com/explore`
  - `sec-fetch-*`
  - `sec-ch-*`
- 响应体中已出现本次任务：
  - `task_id=task_01km4f6bzff73vjq6hgpk3d0pw`
  - `kind=sora_draft`
  - `has_url=true`
  - `reason_str=null`
  - `url=<videos.openai.com/...>`

## 关键结论

### 已证实的事实

- 当前真实浏览器视频链路确实是：
  - `sentinel/req`
  - `POST /backend/nf/create`
  - 多次 `GET /backend/nf/pending/v2`
  - `pending` 清空后切 `GET /backend/project_y/profile/drafts/v2?limit=15`
- 浏览器真实轮询不是“裸 Bearer GET”，而是页面 `fetch`：
  - 带页面 Cookie jar
  - 带真实浏览器 `User-Agent`
  - 带 `oai-device-id`
  - 带 `referer`
  - 带 `sec-fetch-*`
  - 带 `sec-ch-*`
- 浏览器真实轮询阶段未观察到 `openai-sentinel-token`
- 浏览器真实轮询阶段未观察到 `/api/auth/session` 刷新

### 对当前实现的直接影响

- `PollingClient` 不是完全等价的浏览器轮询实现
- 但当前证据也不支持“必须把所有轮询都搬进 page_execute”
- 最需要优先修正的是：
  - 请求形态差异
  - `drafts` 接口路径差异
  - egress 身份未证明一致

## 浏览器真实轮询 vs 当前 PollingClient 差异表

| 项目 | 浏览器真实轮询 | 当前 PollingClient | 结论 | 风险判断 | 建议 |
| --- | --- | --- | --- | --- | --- |
| `pending` 接口 | `GET /backend/nf/pending/v2` | `GET /backend/nf/pending/v2` | 一致 | 低 | 保持 |
| `drafts` 接口 | `GET /backend/project_y/profile/drafts/v2?limit=15` | `GET /backend/project_y/profile/drafts?limit=15` | 不一致 | 高 | 先按真实观测改成 `drafts/v2`，或至少做 `v2 -> legacy` 明确回退 |
| 请求发起位置 | 页面 `fetch` | 服务端 `AsyncSession(impersonate="chrome")` | 不一致 | 中高 | 记录为非等价 replay，不要误判成浏览器原生 |
| `Authorization` | 有 | 有 | 一致 | 低 | 保持 |
| `Cookie` | 有，完整 cookie jar | 有，来自页面态快照 | 大体一致 | 中 | 保持，但要继续验证 cookie 新鲜度 |
| `User-Agent` | Chrome 143 页面真实 UA | 取页面态 UA | 大体一致 | 低 | 保持 |
| `oai-device-id` | 有 | 有 | 一致 | 低 | 保持 |
| `openai-sentinel-token` | 轮询阶段未观察到 | 未发送 | 一致 | 低 | 不需要给 `pending/drafts` 补 sentinel |
| `referer` | `https://sora.chatgpt.com/explore` | 当前未显式发送 | 不一致 | 中 | 从 `PollingContext.page_url` 回放真实 referer |
| `origin` | GET 轮询未观察到 | 未发送 | 大体一致 | 低 | 保持 |
| `sec-fetch-*` | 页面真实存在 | 当前未发送 | 不一致 | 中 | 记录并回放基础 `sec-fetch-site/mode/dest` |
| `sec-ch-*` | 页面真实存在 | 当前未发送 | 不一致 | 中 | 记录并回放基础 `sec-ch-ua` 族 |
| 轮询节奏 | `2-3s` | 配置轮询，当前约 `2.5s` | 大体一致 | 低 | 保持 |
| `/api/auth/session` | 本次轮询窗口未观察到 | 仅 `401/403` 时补偿刷新一次 | 不一致但可解释 | 低中 | 保持补偿逻辑，不要改成每次轮询都刷 |
| 页面 URL 上下文 | 页面始终位于 `https://sora.chatgpt.com/explore` | 当前无真实页面上下文，仅服务端请求 | 不一致 | 中 | 将 `page_url` 落入 `PollingContext` 并参与请求头回放 |
| 传输层 | 浏览器原生 fetch transport | 服务端 HTTP client | 不一致 | 中高 | 继续视为“近似轮询”，不要宣称浏览器等价 |
| 网络出口身份 | 浏览器 profile 真实出口 | 服务端按 token.proxy_url 发送 | 依赖 profile 代理同步 | 中 | 保证 `token.proxy_url` 与指纹浏览器 profile 代理保持一致，不回退全局代理 |

## 当前裁决

- `video submit`：
  - 当前 page_execute 方向正确
  - 本次观测没有推翻该策略
- `pending_v2`：
  - 可以继续保留服务端稳态轮询
  - 但必须补齐 `referer`、`sec-fetch-*`、`sec-ch-*` 等页面态请求上下文
- `drafts_lookup`：
  - 当前实现需要调整
  - 浏览器真实观测明确落在 `drafts/v2`
- `auth refresh`：
  - 不需要在每次轮询前都调用 `/api/auth/session`
  - 保留 `401/403 -> 单次页面补偿刷新` 更符合当前观测
- `sentinel`：
  - 不需要把 `openai-sentinel-token` 引入到 `pending/drafts` 轮询里
- `replay-safe`：
  - 依然不能宣称当前轮询已经浏览器等价
  - 核心阻塞点仍是 transport 差异与 egress 未证明

## 建议实施项

1. 把 `PollingContext` 扩展为可保存页面请求头快照  
- 至少保存：
  - `page_url`
  - `referer`
  - `sec-fetch-site`
  - `sec-fetch-mode`
  - `sec-fetch-dest`
  - `sec-ch-ua`
  - `sec-ch-ua-mobile`
  - `sec-ch-ua-platform`

2. 调整 `PollingClient.get_video_drafts()`  
- 优先请求：
  - `GET /backend/project_y/profile/drafts/v2?limit=15`
- 若真实联调证明需要兼容旧路径，再显式做：
  - `v2 -> legacy` 回退

3. 保留 `401/403 -> refresh_polling_context()` 一次性补偿  
- 当前真实观测没有支持“每次轮询都刷新 auth context”
- 所以不应把补偿机制升级成默认高频刷新

4. 保证 `token.proxy_url` 按 profile 正确同步  
- 在没有同出口证据前，只能说当前轮询“可工作”，不能说“浏览器等价”

## 观测边界

- 本次观测覆盖：
  - `submit`
  - `pending_v2`
  - `drafts/v2`
- 本次观测未覆盖：
  - publish
  - watermark-free
  - 服务端轮询命中 `401/403` 后的页面补偿刷新
- 本次结论只对：
  - `2026-03-20`
  - 该账号形态
  - 该 NST profile
  - 该网络环境
  生效；后续仍需持续实样验证

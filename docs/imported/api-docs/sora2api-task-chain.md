# sora2api 任务链路参考

## 说明

- 来源仓库：`https://github.com/TheSmallHanCat/sora2api`
- 分析基线：`main` 分支，提交 `e7d91b31a7e2a12c261d3cef3dcf79b251b8f8b7`
- 分析日期：`2026-03-12`
- 范围：拆解 `sora2api` 通过 `POST /v1/chat/completions` 发起的图片与视频任务链路，重点补全文生图、图生图与它们和视频链路的差异；不包含本项目 `Video2Api` 的映射、改造建议或 UI 细节。
- 主分析入口只看 3 个文件：`src/api/routes.py`、`src/services/generation_handler.py`、`src/services/sora_client.py`
- 锁、并发、上传代理选择只在需要确认链路细节时补看：`src/services/load_balancer.py`、`src/services/token_lock.py`、`src/services/concurrency_manager.py`
- 时效性：`sora2api` 依赖的 Sora / OpenAI Web 接口可能随时间变化，本文只能代表上述提交时点的实现。
- 安全边界：本文不记录真实 token、cookie、session、代理或可复用登录态。

## 关键接口

| 分类 | 接口 | 作用 | 备注 |
| --- | --- | --- | --- |
| 对外入口 | `POST /v1/chat/completions` | OpenAI 兼容入口，统一接收文生图、图生图、文生视频、图生视频、remix、角色创建请求 | `stream=false` 时只做可用性检查，不真正创建任务 |
| 图片上传 | `POST /backend/uploads` | 图生图、图生视频先上传输入图，换取 `media_id` | `upload_image()` 走 multipart，优先使用独立图片上传代理 |
| 图片提交 | `POST /backend/video_gen` | 真正向 Sora 提交文生图或图生图任务 | `type=image_gen`，由 `generate_image()` 调用 |
| 图片轮询 | `GET /backend/v2/recent_tasks?limit=20` | 读取图片任务状态、进度和结果图地址 | 图片链路唯一真源 |
| 视频提交 | `POST /backend/nf/create` | 真正向 Sora 提交标准视频、图生视频、remix 视频任务 | `generate_video()`、`remix_video()` 最终都收敛到这里 |
| 分镜提交 | `POST /backend/nf/create/storyboard` | 提交分镜视频任务 | 只在提示词命中 storyboard 格式时使用 |
| 视频轮询 | `GET /backend/nf/pending/v2` | 读取运行中视频任务和 `progress_pct` | 视频运行态真源 |
| 完成补扫 | `GET /backend/project_y/profile/drafts?limit=15` | 当视频任务从 pending 消失后，去 drafts 查终态和结果地址 | 视频终态真源 |
| 发布 | `POST /backend/project_y/post` | 把 draft 发布成 post，拿 `post_id` | 仅去水印分支使用 |
| 去水印清理 | `DELETE /backend/project_y/post/{post_id}` | 去水印缓存成功后删除已发布 post | 尽力执行，失败只记日志 |

## 状态建模

- `sora2api` 的持久化任务表只有 `processing / completed / failed` 三态。
- `progress`、`result_urls`、`error_message` 是附属字段，不构成额外阶段。
- `publish` 和 `watermark-free` 只存在于视频任务的内存后处理分支，不会被持久化为独立任务状态。
- `request_logs` 用 `status_code=-1` 表示请求仍在处理中，任务创建成功后再回填 `task_id`。

## 鉴权持久化

### 总体结论

- `sora2api` 的鉴权状态分成“会持久化的长期凭据”和“只保存在进程内存的临时登录态”两类。
- 持久化主载体是 SQLite，默认数据库文件是 `data/hancat.db`。
- 首次启动时，服务会把 `config/setting.toml` 里的默认鉴权配置灌入数据库；后续启动以数据库为准，不会反向用 TOML 覆盖已有行。

### 哪些会落库

| 类别 | 持久化位置 | 主要字段 | 写入时机 | 读取时机 |
| --- | --- | --- | --- | --- |
| 管理员口令与对外 API Key | `admin_config` 单行配置 | `admin_username`、`admin_password`、`api_key` | 首次启动初始化；管理员修改密码或 API Key 时更新 | 启动时加载进 `config` |
| 上游 Sora/OpenAI 凭据 | `tokens` 表 | `token`(AT)、`st`、`rt`、`client_id`、`expiry_time`、`proxy_url` | 新增 token、导入 token、更新 token、自动刷新 AT/RT 时 | token 选择、生成请求、定时刷新、测试 token |
| token 状态与可用性 | `tokens`、`token_stats` | `is_active`、`is_expired`、`disabled_reason`、错误计数、使用计数 | 手动启停、401 失效、自动禁用、调用成功/失败 | 选 token、后台展示、刷新与风控 |
| 其他鉴权相关密钥 | `pow_service_config`、`watermark_free_config` | `api_key`、`custom_parse_token` | 初始化或管理后台更新配置时 | 调外部 POW 服务、调自定义去水印解析服务 |

### 哪些不落库

- 管理后台登录后的 `admin-<random>` token 不会写数据库。
- `/api/login` 成功后只是把 token 放进 `src/api/admin.py` 的模块级 `active_admin_tokens = set()`。
- 这意味着管理员登录态在以下场景会整体失效：
  - 进程重启
  - 调用 `/api/logout`
  - 修改管理员密码后，代码主动 `active_admin_tokens.clear()`

### 管理员鉴权是怎么持久化的

- 管理员用户名、密码、对外 `api_key` 都保存在 `admin_config` 单行记录。
- 启动时，`src/main.py` 会调用 `db.get_admin_config()`，再把数据库里的值写回运行时 `config`。
- `AuthManager.verify_admin()` 登录校验时直接比较 `config.admin_username` 和 `config.admin_password`。
- `AuthManager.verify_api_key()` 则直接比较 `Authorization` 头里的 Bearer 值和 `config.api_key`。
- `update_admin_password()` 和 `update_api_key()` 都会先改库，再同步更新内存配置。
- 尽管 `AuthManager` 里存在 `hash_password()` / `verify_password()`，但管理员登录和改密主链路没有使用它们；当前实现实际是明文存储、明文比对。

### 上游 token 是怎么持久化的

- `tokens` 表把上游鉴权相关字段一起持久化：
  - `token`：Access Token
  - `st`：Session Token
  - `rt`：Refresh Token
  - `client_id`：OAuth 刷新所需 client id
  - `expiry_time`：从 AT 的 JWT 里解出的过期时间
  - `proxy_url`：和该 token 绑定的代理
- `TokenManager.add_token()` 新增时会：
  - 先解析 AT 的 JWT，提取 `expiry_time`
  - 再尽量用上游接口补齐 `email`、订阅信息、Sora2 信息
  - 最后把 AT/ST/RT/client_id 等字段一并写入 `tokens`
- `import_tokens()` 会按 `offline / at / st / rt` 四种模式导入：
  - `offline`：直接持久化提供的 AT，不做实时校验
  - `at`：直接持久化 AT，并联机更新账号状态
  - `st`：先把 ST 换成 AT，再把 ST 和新 AT 一起写库
  - `rt`：先把 RT 换成 AT，再把 RT、新 AT、可能更新后的 RT 一起写库
- `update_token()` 会把新的 AT/ST/RT/client_id/proxy_url 再次落库，并在需要时重新校验有效性。

### 刷新与失效如何回写数据库

- `auto_refresh_expiring_token()` 会在 AT 24 小时内过期时尝试自动刷新，优先顺序是 `ST -> RT`。
- 刷新成功后，新的 AT 会回写 `tokens.token`，若 RT 被上游轮换，也会回写 `tokens.rt`。
- 401 或 `token_invalidated` 会把 token 标成失效，并写入：
  - `is_expired=1`
  - `is_active=0`
  - `disabled_reason=token_invalid` 或 `expired`
- 成功调用后会更新 `last_used_at`、`use_count`，失败则累计 `token_stats` 的错误计数和连续错误计数。

### 实现特征

- `admin_config` 的鉴权配置属于“单例配置落库”，启动后再映射进内存。
- 管理后台登录态属于“纯内存 session”，没有数据库、Redis 或 JWT 持久化。
- 上游 Sora/OpenAI 凭据属于“数据库库存”，不仅保存 AT，也把 ST/RT/client_id 一起保存，供后续自动刷新复用。
- 管理后台 `GET /api/tokens` 会把完整的 AT/ST/RT 返回给已登录管理员，这意味着一旦后台登录态被拿到，凭据可被完整读出。

## 主入口与统一分流

1. `POST /v1/chat/completions` 进入 `create_chat_completion()`。
2. 路由只看 `messages[-1].content`：
   - 若 `content` 是字符串，直接作为 `prompt`。
   - 若 `content` 是数组，则逐项提取 `text`、`image_url`、`video_url`。
3. `request.image`、`request.video`、`request.remix_target_id` 是显式参数兜底；多模态数组中的内容会在命中解析规则时覆盖它们。
4. 路由校验 `model` 是否存在于 `MODEL_CONFIG`，再按模型类型分成 `image / video / avatar_create / prompt_enhance`。
5. `stream=false` 对所有生成模型都只是可用性检查：`handle_generation()` 只调用 `check_token_availability()`，不会提交图片或视频任务。
6. `handle_generation_with_retry()` 在真正执行前读取后台配置里的 `task_retry_enabled`、`task_max_retries`、`auto_disable_on_401`，作为统一重试门禁。
7. `handle_generation()` 的主分流是：
   - 图片模型：进入 `generate_image()`，走文生图或图生图链路。
   - 视频模型 + `remix_target_id`：进入 remix 链路。
   - 视频模型 + storyboard 提示词：进入 `generate_storyboard()`。
   - 普通视频模型：进入 `generate_video()`。
   - `avatar-create` 模型 + `video` 或提示词内 `generation_id`：只做角色创建。
   - 普通视频模型如果直接携带 `video`，当前实现会报错，要求改用 `avatar-create` 模型。
8. 真正提交前会先选 token；图片与视频复用同一套活跃 token 池，但过滤条件不同。
9. 上游提交成功后，服务把 `task_id` 写入本地 `tasks` 表，初始状态固定为 `processing`，`progress=0.0`；随后进入对应的图片或视频轮询分支。

## 视频六段主链路

| 阶段 | 内部函数 | 上游接口 | 完成信号 | 失败信号 |
| --- | --- | --- | --- | --- |
| 创建 | `create_chat_completion()` | `POST /v1/chat/completions` | 解析出 `model`、`prompt`、媒体参数并进入 `handle_generation_with_retry()` | 参数为空、模型非法、无可用 token |
| 提交 | `handle_generation()` -> `generate_video()` / `generate_storyboard()` / `remix_video()` | `POST /backend/nf/create` 或 `POST /backend/nf/create/storyboard` | 返回 `task_id`，并写入 `tasks(status=processing)` | Sentinel 失败、401、429、无权限、上游提交异常 |
| 轮询 | `_poll_task_result()` | `GET /backend/nf/pending/v2` | 在 pending 中找到同 `task_id`，持续更新 `progress_pct` | 结构化 `cf_shield_429`、超时、轮询异常累计到退出 |
| 完成 | `_poll_task_result()` -> `get_video_drafts()` | `GET /backend/project_y/profile/drafts?limit=15` | `item.task_id == task_id` 且拿到 `downloadable_url/url` | `kind=sora_content_violation`、`reason_str/markdown_reason_str` 非空、缺少视频 URL |
| 发布 | `post_video_for_watermark_free()` | `POST /backend/project_y/post` | 返回 `post.id` | 发布接口异常、返回空 `post_id` |
| 去水印 | `get_watermark_free_url_custom()` 或第三方直拼 URL | 自定义解析服务或第三方地址 | 拿到去水印 URL，必要时缓存并落入 `result_urls` | 解析失败、缓存失败、删除发布贴失败 |

## 视频主链路

### 提交阶段

- 普通文生视频、图生视频最终都收敛到 `SoraClient.generate_video()`。
- `generate_video()` 组织的核心字段包括：
  - `kind=video`
  - `prompt`
  - `orientation`
  - `size`
  - `n_frames`
  - `model`
  - `inpaint_items`
  - `style_id`
- 图生视频时，`inpaint_items=[{kind:"upload", upload_id: media_id}]`。
- 该函数最终调用 `POST /backend/nf/create`，底层经 `SoraClient._nf_create_urllib()` 直连。

### 分镜视频

- `GenerationHandler.handle_generation()` 先用 `SoraClient.is_storyboard_prompt()` 检查提示词里是否存在 `[5.0s]` 这类时间标记。
- 命中后会先用 `format_storyboard_prompt()` 改写提示词，再进入 `generate_storyboard()`。
- `generate_storyboard()` 不再走普通 `nf/create`，而是调用 `POST /backend/nf/create/storyboard`。
- 分镜 payload 比普通视频多出 `title`、`storyboard_id`、`metadata` 等字段，但终态查询仍回到 `pending/v2 -> drafts`。

### Remix

- 入口允许两种 remix 标识：
  - 文本中直接包含 `s_<32位hex>`
  - `https://sora.chatgpt.com/p/s_<32位hex>` 分享链接
- `create_chat_completion()` 会优先抽出 `remix_target_id`，`_handle_remix()` 再清洗提示词中的 remix 链接。
- 最终由 `SoraClient.remix_video()` 把 `remix_target_id` 放进 `POST /backend/nf/create` 的 payload。

### 角色创建

- 角色创建已经从普通视频模型里拆出，当前要求使用 `avatar-create` 系列模型。
- `avatar-create` 模型支持两种入口：
  - 显式 `video` 参数
  - 提示词中包含 `generation_id(gen_xxx)`
- 普通视频模型如果直接携带 `video`，当前实现不会帮用户自动走角色创建，而是直接报错要求切换模型。

### 进度轮询

- 默认轮询间隔来自 `config/setting.toml` 的 `sora.poll_interval=2.5` 秒。
- `_poll_task_result()` 对视频任务先调用 `GET /backend/nf/pending/v2`。
- 若在 pending 列表中找到同 `task_id`，则读取 `progress_pct`，换算成百分比后回写本地 `tasks.progress`。
- 进度存在时按真实值更新；`progress_pct` 为 `null` 时按 `0` 处理。
- 视频任务即使进度不变，也会每 30 秒向流式响应补一条状态说明。
- 若任务不再出现在 pending 列表，代码不会直接判定成功或失败，而是立即切去 `GET /backend/project_y/profile/drafts?limit=15` 做终态补扫。

### 完成判定

- drafts 补扫时，以 `item.task_id == task_id` 作为匹配条件。
- 命中 draft 后，先读取：
  - `kind`
  - `reason_str`
  - `markdown_reason_str`
  - `url`
  - `downloadable_url`
- 失败判定满足任一即可：
  - `kind == "sora_content_violation"`
  - `reason_str` 或 `markdown_reason_str` 为非空
  - `url` 和 `downloadable_url` 都缺失
- 成功判定是拿到有效视频地址，优先使用 `downloadable_url`，缺失时退回 `url`。
- 成功后把最终地址写入 `result_urls`，并把本地任务更新为 `completed`；失败则写 `error_message` 并标记 `failed`。

### 发布与去水印

- 这一段只在 `watermark_free_enabled=true` 时发生。
- 代码不会把“发布中”或“去水印中”记成新的数据库状态，而是在 draft 已找到后直接进入后处理分支。
- 去水印分支使用 draft 的 `id` 作为 `generation_id`，调用 `POST /backend/project_y/post`。
- 发布成功后拿到 `post_id`，再按配置分两种取去水印地址：
  - `third_party`：直接拼 `https://oscdn2.dyysy.com/MP4/{post_id}.mp4`
  - `custom`：调用自定义解析服务 `/get-sora-link`，请求体里传分享链接 `https://sora.chatgpt.com/p/{post_id}`
- 若缓存开启，服务会先下载并缓存去水印视频，再把本地 `/tmp/...` 地址写入 `result_urls`。
- 去水印视频缓存成功后，代码会尽力执行 `DELETE /backend/project_y/post/{post_id}` 清理已发布贴；删除失败只记日志，不会反转任务成功态。

## 图片链路

### 入口与模型分流

- `create_chat_completion()` 同样从 `messages[-1].content` 提取图片任务的 `prompt` 和输入图。
- `MODEL_CONFIG` 里，3 个图片模型的尺寸是固定的：
  - `gpt-image`：`360x360`
  - `gpt-image-landscape`：`540x360`
  - `gpt-image-portrait`：`360x540`
- 路由把这 3 个模型统一归类为 `type=image`，随后都进入 `GenerationHandler.handle_generation()` 的图片分支。
- `stream=false` 时不会提交图片任务，只返回“是否有可用图片 token”的检查结果；真正文生图、图生图都要求 `stream=true`。

### 图片输入解析

- `request.image` 是图片输入的显式兜底字段，期望值是 base64 或 data URI。
- 当 `content` 是多模态数组时，只有命中 `{"type":"image_url"}` 且 `image_url.url` 以 `data:image` 开头，路由才会把它拆成 base64 内容覆盖到 `image_data`。
- 若 data URI 中包含 `base64,`，代码会取逗号后的纯 base64；若不包含，就把整个字符串原样交给后续解码。
- 普通远程 `image_url` 当前不会在这条链路里被下载、转存或透传给上传接口；对图生图来说，这类 URL 实际上等价于“没有提供图片输入”。
- 真正解码发生在 `GenerationHandler._decode_base64_image()`：函数只会去掉 data URI 前缀，再调用 `base64.b64decode()`。

### 图片上传与 media_id 处理

- 图片模型进入真正生成前，会先调用 `load_balancer.select_token(for_image_generation=True)` 选 token。
- 图片 token 的候选过滤规则是：
  - 只看活跃 token
  - 必须 `image_enabled=true`
  - 不能处于 `token_lock` 锁定中
  - 若启用了并发管理，必须还有剩余 image concurrency
- 候选集合确定后，调度策略才看 `call_logic_mode`：
  - `default`：随机选 token
  - `polling`：按 token id 轮询
- 真正执行前，代码会先拿 `token_lock`，再拿 image concurrency 槽位；这把锁覆盖的是整条图片任务链路，而不只是上传步骤。
- 若请求带图，`handle_generation()` 会先把 base64 解码成字节，再调用 `SoraClient.upload_image()` 上传。
- `upload_image()` 用 multipart 方式向 `POST /backend/uploads` 发送：
  - `file`
  - `file_name`
- 上传成功后返回上游 `id`，本地把它当作 `media_id`，供后续图生图或图生视频提交使用。
- 图片上传的代理优先级是：
  - 独立 `image_upload_proxy`
  - token 自带 `proxy_url`
  - 全局代理
  - 不走代理

### `POST /video_gen` 提交参数

- 文生图和图生图最终都收敛到 `SoraClient.generate_image()`。
- 该函数提交到 `POST /backend/video_gen`，而不是视频链路使用的 `nf/create`。
- 文生图时：
  - `operation=simple_compose`
  - `inpaint_items=[]`
- 图生图时：
  - `operation=remix`
  - `inpaint_items=[{type:"image", frame_index:0, upload_media_id: media_id}]`
- 共同 payload 固定包含：
  - `type=image_gen`
  - `prompt`
  - `width`
  - `height`
  - `n_variants=1`
  - `n_frames=1`
  - `inpaint_items`
- 图片生成请求和视频生成请求一样，会额外补 `openai-sentinel-token` 等 header；只是图片链路走的是通用 `_make_request()`，不是 `nf/create` 的 urllib 特化路径。

### `GET /v2/recent_tasks` 轮询与终态判定

- 图片任务提交成功后，也会先写入本地 `tasks(status=processing, progress=0.0)`。
- 随后 `_poll_task_result()` 按 `image_timeout / poll_interval` 轮询 `GET /backend/v2/recent_tasks?limit=20`。
- 响应里只看 `task_responses`，并用 `task_resp.id == task_id` 匹配当前任务。
- 命中后按 `status` 分 3 路处理：
  - `processing`：读取 `progress_pct * 100`，只有比上次进度多至少 20% 才回写数据库并向流式响应发进度消息。
  - `failed`：读取 `error_message`，直接把本地任务标记成 `failed` 并抛错。
  - `succeeded`：从 `generations[].url` 收集结果图地址。
- 图片任务的成功条件不只是 `status == "succeeded"`，还要求至少收集到 1 条有效 `url`。
- 如果状态已经是 `succeeded`，但 `generations[].url` 仍然为空，当前实现不会立刻判失败，而是继续下一轮轮询，直到后续拿到 URL 或整体超时。
- 若这轮 `recent_tasks` 里根本没找到对应 `task_id`，图片链路也不会像视频那样切换到 drafts 补扫，而是继续轮询并每 10 秒发一次心跳。

### 图片缓存与 `result_urls` 回写

- 图片任务成功后，代码会先拿到 `generations[].url` 形成 `urls` 列表，再决定是否缓存。
- 若启用了缓存，服务会逐张调用 `FileCache.download_and_cache(url, "image", token_id=token_id)`。
- 本地缓存 URL 的基址取法是：
  - 优先使用 `cache_base_url`
  - 未配置时回退到 `http://{server_host}:{server_port}`
- 因此最终写回的本地地址形如 `http://127.0.0.1:8000/tmp/<cached_filename>`。
- 单张图片缓存失败不会反转整单成功态；代码只会对那一张回退到原始远端 URL，并继续处理剩余图片。
- 最终 `tasks.result_urls` 会写成 JSON 数组；即使 payload 固定 `n_variants=1`，代码仍按 `generations[]` 全量收集 URL。
- 流式尾块输出的是 Markdown 图片，而不是视频链路的 HTML `<video>`：
  - ``Generated Image: IMAGE_URL_1``
  - ``Generated Image: IMAGE_URL_2``

### 锁、并发、超时与异常回退

- 图片链路额外引入了 per-token `token_lock`，用来保证同一 token 上的图片任务串行执行。
- `token_lock` 的超时时间直接取 `image_timeout`；锁超时后会在下次 `is_locked()` / `acquire_lock()` 时自动失效。
- 若启用了 `ConcurrencyManager`，图片链路还会再扣一层 image concurrency；成功、失败、超时、结构化 `cf_shield_429` 快速失败时都会释放。
- 图片任务的总超时取 `generation.image_timeout`，默认 300 秒；超时后本地任务会被标记为 `failed`，错误信息形如 `Generation timeout after ... seconds`。
- `handle_generation_with_retry()` 对图片和视频共用同一套重试门禁：
  - 默认读取后台 `task_max_retries`
  - 401 / `unauthorized` / `token_invalidated` 在 `auto_disable_on_401=true` 时会自动禁用当前 token，再换 token 重试
  - `_should_retry_on_error()` 会把 `cf_shield`、`cloudflare`、`429`、`rate limit`、模型使用错误排除在自动重试之外
- 轮询阶段只有当异常能被解析成结构化 JSON，且 `error.code == "cf_shield_429"` 时，代码才会立即把图片任务标记为 `failed` 并停止轮询。
- 普通 HTTP 429 文本异常按当前实现不一定命中这个快速失败分支；它更像是“提交阶段不重试，轮询阶段尽量按已有错误处理继续/退出”，而不是统一的硬编码立即失败。

## 与视频链路差异

- 图片与视频都从 `POST /v1/chat/completions` 进入，也都只把本地任务持久化成 `processing / completed / failed` 三态。
- 图片模型分流到 `generate_image()`；视频模型分流到 `generate_video()`、`generate_storyboard()` 或 `remix_video()`。
- 图片提交走 `POST /backend/video_gen`；视频主链路走 `POST /backend/nf/create` 或 `POST /backend/nf/create/storyboard`。
- 图片轮询只看 `GET /backend/v2/recent_tasks?limit=20`；视频轮询是 `pending/v2` 跑态、`drafts` 查终态的两段式。
- 图片任务“未命中列表”时只会继续心跳与轮询，不会像视频那样切到 drafts 做终态补偿。
- 图片没有 `pending/v2 -> drafts -> publish -> watermark-free` 这段后处理链，也没有 draft/post 级别的终态补扫。
- 图片成功后输出 Markdown 图片并回写图片 URL 数组；视频成功后输出 HTML `<video>` 并回写单视频 URL。
- 图片有额外的 per-token `token_lock`；视频没有这把锁，但会做 `sora2_supported`、`sora2_cooldown_until` 和 video concurrency 过滤。

## 回退与失败

- `stream=false` 不会真正调用上游创建任务，只返回“是否有可用 token”的检查结果。
- 任务失败重试由 `handle_generation_with_retry()` 统一处理，默认取后台配置 `task_max_retries=3`。
- `_should_retry_on_error()` 明确排除了 `cf_shield`、`cloudflare`、`429`、`rate limit`、`invalid model`、`avatar-create` 误用、`参数错误` 这几类错误；这些分支默认不会自动重试。
- 401 错误会在 `auto_disable_on_401=true` 时自动禁用当前 token，再换 token 重试。
- 轮询阶段只有结构化 `error.code == "cf_shield_429"` 会被立即判成不可恢复失败；普通 HTTP 429 文本异常并不保证命中这一快速失败逻辑。
- 图片超时取 `image_timeout`，视频超时取 `video_timeout`；两者超时后都会把本地任务标为 `failed`。
- 图片缓存失败不会让成功任务变失败，而是按单张图片退回远端原始 URL。
- 视频去水印失败时：
  - `fallback_on_failure=true`：回退到原始带水印视频 URL
  - `fallback_on_failure=false`：整单直接失败
- 视频缓存失败同样不会反转已经成功的终态，而是退回远端原始 URL。

## 关键结论

- `sora2api` 的图片链路本质上是：`创建请求 -> 可选 /backend/uploads 上传输入图 -> /backend/video_gen 提交 -> /backend/v2/recent_tasks 轮询 -> 可选缓存 -> result_urls 回写`。
- `sora2api` 的视频链路本质上是：`创建请求 -> /backend/nf/create 或 /backend/nf/create/storyboard 提交 -> pending/v2 轮询 -> drafts 终态判定 -> 可选 publish 去水印后处理`。
- 两条链路共用同一套 `/v1/chat/completions` 入口、本地三态任务表、token 池和统一重试框架，但图片多了 `token_lock` 串行控制，视频多了 drafts / publish / watermark-free 后处理。
- 对图片任务来说，`recent_tasks` 既是运行态真源，也是终态真源；对视频任务来说，`pending/v2` 是运行态真源，`drafts` 是终态真源。

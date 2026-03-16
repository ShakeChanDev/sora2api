# 页面态鉴权与抗风控改造

## 当前分层
- 浏览器接入层：`src/services/browser_provider.py`
- 页面态鉴权刷新：`src/services/auth_context_service.py`
- 策略化 mutation 执行：`src/services/mutation_executor.py`
- 稳态 generate 轮询：保留 `src/services/generation_handler.py` 现有 HTTP 轮询主路径

## 默认策略矩阵
| Mutation | 默认策略 |
| --- | --- |
| `image_upload` | `replay_http` |
| `image_submit` | `replay_then_page_fallback` |
| `video_submit` | `replay_then_page_fallback` |
| `storyboard_submit` | `replay_then_page_fallback` |
| `remix_submit` | `replay_then_page_fallback` |
| `long_video_extension` | `replay_then_page_fallback` |
| `publish_execute` | `page_execute` |

## 页面态 auth context
- 高风险 mutation 执行前必须通过真实页面调用 `/api/auth/session`
- 同步收集 `access_token`、`cookie_header`、`user_agent`、`oai-device-id`、`sentinel_token`
- 失败归因统一使用：
  - `auth_context_incomplete`
  - `auth_context_invalid`
  - `sentinel_not_ready`
  - `cloudflare_challenge`
  - `TARGET_CLOSED`
  - `ECONNREFUSED`
  - `execution_context_destroyed`
  - `profile_locked_timeout`
  - `window_locked_timeout`

## 已实现的约束
- `POST /v1/chat/completions` 对外语义保持不变
- `video submit` 支持 fresh auth replay，并在高风险失败时自动切 `page_execute`
- `publish execute` 走页面执行，并在 publish 前重新刷新 auth context
- 日志、管理接口、管理页面默认只展示脱敏预览，不回显 AT / ST / RT / Cookie / Sentinel / API key 明文

## 观测基线
- `video submit` 原生请求关键头已对齐到 fresh AT、完整 Cookie、UA、`oai-device-id`、`openai-sentinel-token`
- `publish execute` 在页面内执行，避免服务端 replay 与原生 `post_text` 语义继续偏离

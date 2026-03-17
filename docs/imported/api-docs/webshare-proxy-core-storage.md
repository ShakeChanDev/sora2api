# Webshare 代理核心落库方案（实施稿）

## 说明

- 分析日期：`2026-03-16`
- 目标：把 Webshare 官方 API 中和“代理核心”直接相关的数据，收敛为一套可落到数据库的当前态 + 历史态模型。
- 范围：代理列表、代理配置、替换历史、IP 授权、统计、活动，以及少量账号 / 套餐上下文。
- 不在本版范围：`sub-user` 管理、完整 API Key 列表管理、账单 / 发票、下单 / 续费流程。
- 设计基线：以 PostgreSQL 为参考；`JSONB` 字段可降级为 MySQL `JSON` 或 SQLite `TEXT`。

## 官方来源

- Proxy List: <https://apidocs.webshare.io/proxy-list>
- Plan: <https://apidocs.webshare.io/subscription/plan>
- Available assets: <https://apidocs.webshare.io/subscription/assets>
- Proxy Replacement Object: <https://apidocs.webshare.io/proxy-replacement/proxy_replacement>
- Replaced Proxy Object: <https://apidocs.webshare.io/proxy-replacement/replaced_proxy>
- Get Proxy Config: <https://apidocs.webshare.io/proxy-config/get_proxy_config>
- Update Proxy Config: <https://apidocs.webshare.io/proxy-config/update>
- IP Authorization List: <https://apidocs.webshare.io/ipauthorization/list>
- IP Authorization Retrieve: <https://apidocs.webshare.io/ipauthorization/retrieve>
- List Stats: <https://apidocs.webshare.io/proxystats/list_stats>
- List Activity: <https://apidocs.webshare.io/proxystats/list_activity>
- User Profile: <https://apidocs.webshare.io/userprofile/retrieve>

## 设计原则

1. 当前态和历史态分离。
2. 上游对象优先保留稳定自然键，例如 `provider_proxy_id`、`provider_replacement_id`、`provider_ip_auth_id`。
3. 敏感值不落明文。API Key、下载 token、代理用户名密码只保留密文列或 secret ref。
4. 统一区分“上游语义时间”和“本地同步时间”。
5. 不能稳定拆列的扩展字段统一保留 `source_payload_json`，避免后续 API 漂移导致重构。
6. 活动日志采用追加写，不做覆盖更新；小时级统计采用幂等 upsert。

## 统一字段约定

| 字段 | 含义 |
| --- | --- |
| `account_id` | 本地 `webshare_accounts.id` |
| `provider_created_at` | Webshare 返回对象的创建时间 |
| `provider_updated_at` | Webshare 返回对象的更新时间；无则不建 |
| `fetched_at` | 本次从 Webshare 拉取完成的时间 |
| `ingested_at` | 本地写库时间；需要和 `fetched_at` 分开时才单独保留 |
| `source_payload_json` | 原始响应对象或归一化后的响应对象 |
| `last_sync_run_id` | 最近一次写入该对象的同步任务 |

## 核心表

| 表名 | 角色 | 主键 / 去重键 | 写入模式 |
| --- | --- | --- | --- |
| `webshare_accounts` | 账号当前态 | `id`，`webshare_user_id` 唯一 | upsert |
| `webshare_plan_current` | 套餐当前态 | `account_id` 唯一 | upsert |
| `webshare_asset_snapshots` | 资产快照 | `id` | append |
| `webshare_proxy_config_current` | 代理配置当前态 | `account_id` 唯一 | upsert |
| `webshare_proxy_config_history` | 代理配置历史 | `id`，`(account_id, config_hash, fetched_at)` | append on change |
| `webshare_sync_runs` | 通用同步作业审计 | `id` | append |
| `webshare_proxies` | 代理当前态 | `id`，`(account_id, provider_proxy_id)` 唯一 | upsert |
| `webshare_proxy_replacements` | 替换任务当前态 / 历史态 | `id`，`(account_id, provider_replacement_id)` 唯一 | upsert |
| `webshare_replaced_proxy_events` | 单个代理替换事件 | `id`，`(account_id, provider_replaced_proxy_id)` 唯一 | upsert / append-like |
| `webshare_ip_authorizations_current` | IP 授权当前态 | `id`，`(account_id, provider_ip_auth_id)` 唯一 | upsert |
| `webshare_ip_authorization_history` | IP 授权历史 | `id` | append |
| `webshare_proxy_stats_hourly` | 小时级统计 | `id`，`(account_id, bucket_start_at, is_projected)` 唯一 | upsert |
| `webshare_proxy_activity_events` | 原始活动事件 | `id`，`(account_id, payload_hash)` 唯一 | append + dedupe |

## 各表字段边界

### `webshare_accounts`

- 当前只保留接入运行所需的账号上下文。
- 推荐字段：
  - `provider`，固定为 `webshare`
  - `webshare_user_id`
  - `email`
  - `first_name`
  - `last_name`
  - `timezone`
  - `tracking_id`
  - `last_login_at`
  - `api_key_secret_ref`
  - `api_key_fingerprint`
  - `created_at`
  - `updated_at`

### `webshare_plan_current`

- 一账号一行。
- 主要字段：
  - `provider_plan_id`
  - `status`
  - `bandwidth_limit_gb`
  - `monthly_price_usd`
  - `yearly_price_usd`
  - `proxy_type`
  - `proxy_subtype`
  - `proxy_count`
  - `proxy_countries_json`
  - `required_site_checks_json`
  - `on_demand_refreshes_total`
  - `on_demand_refreshes_used`
  - `on_demand_refreshes_available`
  - `automatic_refresh_frequency_seconds`
  - `automatic_refresh_last_at`
  - `automatic_refresh_next_at`
  - `proxy_replacements_total`
  - `proxy_replacements_used`
  - `proxy_replacements_available`
  - `subusers_total`
  - `subusers_used`
  - `subusers_available`
  - `is_unlimited_ip_authorizations`
  - `is_high_concurrency`
  - `is_high_priority_network`
  - `high_quality_ips_only`
  - `source_payload_json`
  - `fetched_at`
  - `updated_at`

### `webshare_asset_snapshots`

- 这类数据适合做快照，不建议先拆国家维表。
- 主要字段：
  - `account_id`
  - `total_subnets_json`
  - `available_countries_json`
  - `fetched_at`
  - `source_payload_json`

### `webshare_proxy_config_current`

- 只保留当前有效配置。
- 主要字段：
  - `request_timeout`
  - `request_idle_timeout`
  - `ip_authorization_country_codes_json`
  - `auto_replace_invalid_proxies`
  - `auto_replace_low_country_confidence_proxies`
  - `auto_replace_out_of_rotation_proxies`
  - `auto_replace_failed_site_check_proxies`
  - `proxy_list_download_token_secret_ref`
  - `config_hash`
  - `fetched_at`
  - `updated_at`
  - `source_payload_json`

### `webshare_proxy_config_history`

- 只有 `config_hash` 变化时写新行。
- 主要字段与 current 基本一致，但增加：
  - `current_id`
  - `changed_at`

### `webshare_sync_runs`

- 所有拉取型任务统一审计。
- `resource_type` 建议值：
  - `user_profile`
  - `plan`
  - `assets`
  - `proxy_config`
  - `proxy_list`
  - `proxy_replacements`
  - `replaced_proxy_events`
  - `ip_authorizations`
  - `proxy_stats_hourly`
  - `proxy_activity_events`
- 主要字段：
  - `resource_type`
  - `request_params_json`
  - `started_at`
  - `finished_at`
  - `status`
  - `fetched_count`
  - `inserted_count`
  - `updated_count`
  - `retired_count`
  - `error_code`
  - `error_message`

### `webshare_proxies`

- 当前态表，不物理删除旧代理。
- 主要字段：
  - `provider_proxy_id`
  - `auth_username_ciphertext`
  - `auth_password_ciphertext`
  - `auth_username_fingerprint`
  - `proxy_address`，允许空
  - `port`
  - `valid`
  - `last_verification_at`
  - `country_code`
  - `city_name`
  - `provider_created_at`
  - `first_seen_at`
  - `last_seen_at`
  - `retired_at`
  - `retire_reason`
  - `last_sync_run_id`
  - `source_payload_json`

### `webshare_proxy_replacements`

- 保存 replacement 对象自身生命周期。
- 主要字段：
  - `provider_replacement_id`
  - `to_replace_json`
  - `replace_with_json`
  - `dry_run`
  - `state`
  - `proxies_removed`
  - `proxies_added`
  - `reason`
  - `error_code`
  - `error_message`
  - `provider_created_at`
  - `dry_run_completed_at`
  - `completed_at`
  - `source_payload_json`

### `webshare_replaced_proxy_events`

- 这是单个代理的替换事实表。
- 主要字段：
  - `provider_replaced_proxy_id`
  - `replacement_id`
  - `reason`
  - `proxy`
  - `proxy_port`
  - `proxy_country_code`
  - `replaced_with`
  - `replaced_with_port`
  - `replaced_with_country_code`
  - `provider_created_at`
  - `source_payload_json`

### `webshare_ip_authorizations_current`

- 当前态中保留 `active`。
- 主要字段：
  - `provider_ip_auth_id`
  - `ip_address`
  - `provider_created_at`
  - `last_used_at`
  - `active`
  - `last_sync_run_id`
  - `source_payload_json`

### `webshare_ip_authorization_history`

- 用于记录授权创建、失活、删除等状态变化。
- 主要字段：
  - `current_id`
  - `provider_ip_auth_id`
  - `ip_address`
  - `event_type`
  - `provider_created_at`
  - `last_used_at`
  - `observed_at`
  - `source_payload_json`

### `webshare_proxy_stats_hourly`

- `timestamp` 按小时 bucket 落库，和文档中的 projected 数据分开。
- 主要字段：
  - `bucket_start_at`
  - `is_projected`
  - `bandwidth_total_gb`
  - `bandwidth_average_gb`
  - `requests_total`
  - `requests_successful`
  - `requests_failed`
  - `error_reasons_json`
  - `countries_used_json`
  - `number_of_proxies_used`
  - `protocols_used_json`
  - `average_concurrency`
  - `average_rps`
  - `last_request_sent_at`
  - `source_payload_json`
  - `fetched_at`

### `webshare_proxy_activity_events`

- 官方活动对象没有稳定 `id`，本版用 `payload_hash` 去重。
- 主要字段：
  - `payload_hash`
  - `event_at`
  - `protocol`
  - `request_duration_ms`
  - `handshake_duration_ms`
  - `tunnel_duration_ms`
  - `error_reason`
  - `error_reason_how_to_fix`
  - `auth_username`
  - `proxy_address`
  - `bytes`
  - `client_address`
  - `ip_address`
  - `hostname`
  - `domain`
  - `port`
  - `proxy_port`
  - `listen_address`
  - `listen_port`
  - `source_payload_json`
  - `fetched_at`

## 同步规则

### 账号、套餐、配置

- `webshare_accounts`、`webshare_plan_current`、`webshare_proxy_config_current` 都使用 upsert。
- `webshare_proxy_config_current` 写入前先做字段归一化并计算 `config_hash`。
- 若 `config_hash` 与当前值不同，再向 `webshare_proxy_config_history` 追加一条历史。

### 代理列表

1. 创建一条 `webshare_sync_runs(resource_type='proxy_list')`。
2. 以 `(account_id, provider_proxy_id)` 为键执行 upsert。
3. 本轮未出现但之前存在、且未退役的代理，更新：
   - `retired_at = fetched_at`
   - `retire_reason = 'missing_from_latest_proxy_list'`
4. 若后续再次出现同一个 `provider_proxy_id`，清空 `retired_at` / `retire_reason`。

### 替换任务与替换事件

- `webshare_proxy_replacements` 按 replacement 对象 upsert。
- `webshare_replaced_proxy_events` 按 replaced proxy 对象 upsert。
- 命中替换事件后，尝试把旧代理在 `webshare_proxies` 标记为：
  - `retired_at = provider_created_at`
  - `retire_reason = reason`

### IP 授权

- 当前列表中的 IP upsert 到 `webshare_ip_authorizations_current(active=true)`。
- 本轮缺失的历史 IP 不删除，只更新为 `active=false`。
- 每次 create / deactivate / missing 都写入 `webshare_ip_authorization_history`。

### 小时级统计

- 以 `(account_id, bucket_start_at, is_projected)` 为幂等键 upsert。
- 推荐把文档返回的 `timestamp` 归一为 UTC 小时整点。

### 原始活动

- 取单个活动对象归一化 JSON 后计算 `sha256(payload)` 作为 `payload_hash`。
- 用 `(account_id, payload_hash)` 去重写入。
- 不建议对活动事件做更新，重复抓取时直接忽略冲突。

## 保留策略

- `webshare_accounts`、`webshare_plan_current`、`webshare_proxy_config_current`、`webshare_proxies`、`webshare_ip_authorizations_current`：长期保留。
- `webshare_proxy_config_history`、`webshare_proxy_replacements`、`webshare_replaced_proxy_events`、`webshare_ip_authorization_history`：长期保留。
- `webshare_proxy_stats_hourly`：至少保留 `365` 天。
- `webshare_proxy_activity_events`：热数据保留 `90` 天；超过窗口后归档到冷表或仅保留汇总。
- `webshare_sync_runs`：至少保留 `180` 天。

## 安全约束

- `api_key_secret_ref`、`proxy_list_download_token_secret_ref` 指向密钥管理系统，不存明文。
- 代理用户名 / 密码至少使用应用层加密后再入库。
- 对需要检索的敏感值，额外存 `fingerprint`，不要直接建立明文字段索引。

## DTO / Repo 模型

- `WebshareAccount`
- `WebsharePlanState`
- `WebshareAssetSnapshot`
- `WebshareProxyConfig`
- `WebshareProxyRecord`
- `WebshareSyncRun`
- `WebshareProxyReplacement`
- `WebshareReplacedProxyEvent`
- `WebshareIpAuthorization`
- `WebshareProxyStatPoint`
- `WebshareProxyActivityEvent`

这些模型的公共约束：

- 所有时间字段统一转成带时区时间。
- 所有 repo upsert 都返回本地主键和写入动作：`inserted / updated / unchanged / retired`。
- 所有 DTO 都保留原始 `source_payload_json`。

## DDL 草案

- PostgreSQL 风格 DDL 已放在同目录文件：
  - `webshare-proxy-core-schema.sql`
- 该 DDL 重点覆盖：
  - 表结构
  - 唯一键
  - 外键
  - 常用索引
  - 活动去重键
  - 当前态 / 历史态拆分

## 已知推断

- `webshare_proxy_activity_events.payload_hash` 是本地推断键，不是官方字段。
- 代理退役通过 `retired_at / retire_reason` 表达，不做硬删除。
- `proxy_address` 必须允许空，因为官方文档说明 residential / backbone 场景下可能不给具体 IP。

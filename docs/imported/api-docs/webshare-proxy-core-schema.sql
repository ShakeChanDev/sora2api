-- Webshare proxy core storage schema
-- PostgreSQL-first DDL. JSONB can be downgraded to JSON/TEXT in MySQL/SQLite.

CREATE TABLE IF NOT EXISTS webshare_accounts (
    id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'webshare',
    webshare_user_id BIGINT,
    email TEXT,
    first_name TEXT,
    last_name TEXT,
    timezone TEXT,
    tracking_id TEXT,
    last_login_at TIMESTAMPTZ,
    api_key_secret_ref TEXT,
    api_key_fingerprint TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_webshare_accounts_provider CHECK (provider = 'webshare'),
    CONSTRAINT uq_webshare_accounts_user UNIQUE (webshare_user_id),
    CONSTRAINT uq_webshare_accounts_email UNIQUE (email)
);

CREATE TABLE IF NOT EXISTS webshare_sync_runs (
    id BIGSERIAL PRIMARY KEY,
    account_id BIGINT NOT NULL REFERENCES webshare_accounts(id) ON DELETE CASCADE,
    resource_type TEXT NOT NULL,
    request_params_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    status TEXT NOT NULL,
    fetched_count INTEGER NOT NULL DEFAULT 0,
    inserted_count INTEGER NOT NULL DEFAULT 0,
    updated_count INTEGER NOT NULL DEFAULT 0,
    retired_count INTEGER NOT NULL DEFAULT 0,
    error_code TEXT,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_webshare_sync_runs_account_resource_started
    ON webshare_sync_runs(account_id, resource_type, started_at DESC);

CREATE TABLE IF NOT EXISTS webshare_plan_current (
    id BIGSERIAL PRIMARY KEY,
    account_id BIGINT NOT NULL REFERENCES webshare_accounts(id) ON DELETE CASCADE,
    provider_plan_id BIGINT,
    status TEXT,
    bandwidth_limit_gb NUMERIC(18, 6),
    monthly_price_usd NUMERIC(18, 6),
    yearly_price_usd NUMERIC(18, 6),
    proxy_type TEXT,
    proxy_subtype TEXT,
    proxy_count INTEGER,
    proxy_countries_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    required_site_checks_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    on_demand_refreshes_total INTEGER,
    on_demand_refreshes_used INTEGER,
    on_demand_refreshes_available INTEGER,
    automatic_refresh_frequency_seconds INTEGER,
    automatic_refresh_last_at TIMESTAMPTZ,
    automatic_refresh_next_at TIMESTAMPTZ,
    proxy_replacements_total INTEGER,
    proxy_replacements_used INTEGER,
    proxy_replacements_available INTEGER,
    subusers_total INTEGER,
    subusers_used INTEGER,
    subusers_available INTEGER,
    is_unlimited_ip_authorizations BOOLEAN,
    is_high_concurrency BOOLEAN,
    is_high_priority_network BOOLEAN,
    high_quality_ips_only BOOLEAN,
    source_payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    fetched_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_webshare_plan_current_account UNIQUE (account_id)
);

CREATE INDEX IF NOT EXISTS idx_webshare_plan_current_provider_plan_id
    ON webshare_plan_current(provider_plan_id);

CREATE TABLE IF NOT EXISTS webshare_asset_snapshots (
    id BIGSERIAL PRIMARY KEY,
    account_id BIGINT NOT NULL REFERENCES webshare_accounts(id) ON DELETE CASCADE,
    total_subnets_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    available_countries_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    fetched_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_webshare_asset_snapshots_account_fetched
    ON webshare_asset_snapshots(account_id, fetched_at DESC);

CREATE TABLE IF NOT EXISTS webshare_proxy_config_current (
    id BIGSERIAL PRIMARY KEY,
    account_id BIGINT NOT NULL REFERENCES webshare_accounts(id) ON DELETE CASCADE,
    request_timeout INTEGER,
    request_idle_timeout INTEGER,
    ip_authorization_country_codes_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    auto_replace_invalid_proxies BOOLEAN,
    auto_replace_low_country_confidence_proxies BOOLEAN,
    auto_replace_out_of_rotation_proxies BOOLEAN,
    auto_replace_failed_site_check_proxies BOOLEAN,
    proxy_list_download_token_secret_ref TEXT,
    config_hash CHAR(64) NOT NULL,
    source_payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    fetched_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_webshare_proxy_config_current_account UNIQUE (account_id)
);

CREATE TABLE IF NOT EXISTS webshare_proxy_config_history (
    id BIGSERIAL PRIMARY KEY,
    account_id BIGINT NOT NULL REFERENCES webshare_accounts(id) ON DELETE CASCADE,
    current_id BIGINT REFERENCES webshare_proxy_config_current(id) ON DELETE SET NULL,
    request_timeout INTEGER,
    request_idle_timeout INTEGER,
    ip_authorization_country_codes_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    auto_replace_invalid_proxies BOOLEAN,
    auto_replace_low_country_confidence_proxies BOOLEAN,
    auto_replace_out_of_rotation_proxies BOOLEAN,
    auto_replace_failed_site_check_proxies BOOLEAN,
    proxy_list_download_token_secret_ref TEXT,
    config_hash CHAR(64) NOT NULL,
    source_payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    fetched_at TIMESTAMPTZ NOT NULL,
    changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_webshare_proxy_config_history_account_hash_fetched
    ON webshare_proxy_config_history(account_id, config_hash, fetched_at);

CREATE INDEX IF NOT EXISTS idx_webshare_proxy_config_history_account_changed
    ON webshare_proxy_config_history(account_id, changed_at DESC);

CREATE TABLE IF NOT EXISTS webshare_proxies (
    id BIGSERIAL PRIMARY KEY,
    account_id BIGINT NOT NULL REFERENCES webshare_accounts(id) ON DELETE CASCADE,
    provider_proxy_id TEXT NOT NULL,
    auth_username_ciphertext TEXT,
    auth_password_ciphertext TEXT,
    auth_username_fingerprint TEXT,
    proxy_address TEXT,
    port INTEGER,
    valid BOOLEAN,
    last_verification_at TIMESTAMPTZ,
    country_code TEXT,
    city_name TEXT,
    provider_created_at TIMESTAMPTZ,
    first_seen_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    retired_at TIMESTAMPTZ,
    retire_reason TEXT,
    last_sync_run_id BIGINT REFERENCES webshare_sync_runs(id) ON DELETE SET NULL,
    source_payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_webshare_proxies_account_provider_proxy UNIQUE (account_id, provider_proxy_id)
);

CREATE INDEX IF NOT EXISTS idx_webshare_proxies_account_proxy_endpoint
    ON webshare_proxies(account_id, proxy_address, port);

CREATE INDEX IF NOT EXISTS idx_webshare_proxies_account_auth_username
    ON webshare_proxies(account_id, auth_username_fingerprint);

CREATE INDEX IF NOT EXISTS idx_webshare_proxies_account_last_seen
    ON webshare_proxies(account_id, last_seen_at DESC);

CREATE INDEX IF NOT EXISTS idx_webshare_proxies_account_retired
    ON webshare_proxies(account_id, retired_at DESC);

CREATE TABLE IF NOT EXISTS webshare_proxy_replacements (
    id BIGSERIAL PRIMARY KEY,
    account_id BIGINT NOT NULL REFERENCES webshare_accounts(id) ON DELETE CASCADE,
    provider_replacement_id BIGINT NOT NULL,
    to_replace_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    replace_with_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    dry_run BOOLEAN NOT NULL DEFAULT FALSE,
    state TEXT,
    proxies_removed INTEGER,
    proxies_added INTEGER,
    reason TEXT,
    error_code TEXT,
    error_message TEXT,
    provider_created_at TIMESTAMPTZ,
    dry_run_completed_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    source_payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_webshare_proxy_replacements_account_provider UNIQUE (account_id, provider_replacement_id)
);

CREATE INDEX IF NOT EXISTS idx_webshare_proxy_replacements_account_state_created
    ON webshare_proxy_replacements(account_id, state, provider_created_at DESC);

CREATE TABLE IF NOT EXISTS webshare_replaced_proxy_events (
    id BIGSERIAL PRIMARY KEY,
    account_id BIGINT NOT NULL REFERENCES webshare_accounts(id) ON DELETE CASCADE,
    provider_replaced_proxy_id BIGINT NOT NULL,
    replacement_id BIGINT REFERENCES webshare_proxy_replacements(id) ON DELETE SET NULL,
    reason TEXT,
    proxy TEXT,
    proxy_port INTEGER,
    proxy_country_code TEXT,
    replaced_with TEXT,
    replaced_with_port INTEGER,
    replaced_with_country_code TEXT,
    provider_created_at TIMESTAMPTZ,
    source_payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_webshare_replaced_proxy_events_account_provider UNIQUE (account_id, provider_replaced_proxy_id)
);

CREATE INDEX IF NOT EXISTS idx_webshare_replaced_proxy_events_account_created
    ON webshare_replaced_proxy_events(account_id, provider_created_at DESC);

CREATE TABLE IF NOT EXISTS webshare_ip_authorizations_current (
    id BIGSERIAL PRIMARY KEY,
    account_id BIGINT NOT NULL REFERENCES webshare_accounts(id) ON DELETE CASCADE,
    provider_ip_auth_id BIGINT NOT NULL,
    ip_address TEXT NOT NULL,
    provider_created_at TIMESTAMPTZ,
    last_used_at TIMESTAMPTZ,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    last_sync_run_id BIGINT REFERENCES webshare_sync_runs(id) ON DELETE SET NULL,
    source_payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_webshare_ip_authorizations_current_account_provider UNIQUE (account_id, provider_ip_auth_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_webshare_ip_authorizations_current_account_ip_active
    ON webshare_ip_authorizations_current(account_id, ip_address)
    WHERE active = TRUE;

CREATE INDEX IF NOT EXISTS idx_webshare_ip_authorizations_current_account_last_used
    ON webshare_ip_authorizations_current(account_id, last_used_at DESC);

CREATE TABLE IF NOT EXISTS webshare_ip_authorization_history (
    id BIGSERIAL PRIMARY KEY,
    account_id BIGINT NOT NULL REFERENCES webshare_accounts(id) ON DELETE CASCADE,
    current_id BIGINT REFERENCES webshare_ip_authorizations_current(id) ON DELETE SET NULL,
    provider_ip_auth_id BIGINT,
    ip_address TEXT NOT NULL,
    event_type TEXT NOT NULL,
    provider_created_at TIMESTAMPTZ,
    last_used_at TIMESTAMPTZ,
    observed_at TIMESTAMPTZ NOT NULL,
    source_payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_webshare_ip_authorization_history_account_observed
    ON webshare_ip_authorization_history(account_id, observed_at DESC);

CREATE TABLE IF NOT EXISTS webshare_proxy_stats_hourly (
    id BIGSERIAL PRIMARY KEY,
    account_id BIGINT NOT NULL REFERENCES webshare_accounts(id) ON DELETE CASCADE,
    bucket_start_at TIMESTAMPTZ NOT NULL,
    is_projected BOOLEAN NOT NULL DEFAULT FALSE,
    bandwidth_total_gb NUMERIC(18, 6),
    bandwidth_average_gb NUMERIC(18, 6),
    requests_total INTEGER,
    requests_successful INTEGER,
    requests_failed INTEGER,
    error_reasons_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    countries_used_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    number_of_proxies_used INTEGER,
    protocols_used_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    average_concurrency NUMERIC(18, 6),
    average_rps NUMERIC(18, 6),
    last_request_sent_at TIMESTAMPTZ,
    source_payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    fetched_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_webshare_proxy_stats_hourly_account_bucket_projected
        UNIQUE (account_id, bucket_start_at, is_projected)
);

CREATE INDEX IF NOT EXISTS idx_webshare_proxy_stats_hourly_account_bucket_desc
    ON webshare_proxy_stats_hourly(account_id, bucket_start_at DESC);

CREATE TABLE IF NOT EXISTS webshare_proxy_activity_events (
    id BIGSERIAL PRIMARY KEY,
    account_id BIGINT NOT NULL REFERENCES webshare_accounts(id) ON DELETE CASCADE,
    payload_hash CHAR(64) NOT NULL,
    event_at TIMESTAMPTZ NOT NULL,
    protocol TEXT,
    request_duration_ms NUMERIC(18, 6),
    handshake_duration_ms NUMERIC(18, 6),
    tunnel_duration_ms NUMERIC(18, 6),
    error_reason TEXT,
    error_reason_how_to_fix TEXT,
    auth_username TEXT,
    proxy_address TEXT,
    bytes BIGINT,
    client_address TEXT,
    ip_address TEXT,
    hostname TEXT,
    domain TEXT,
    port INTEGER,
    proxy_port INTEGER,
    listen_address TEXT,
    listen_port INTEGER,
    source_payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    fetched_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_webshare_proxy_activity_events_account_hash UNIQUE (account_id, payload_hash)
);

CREATE INDEX IF NOT EXISTS idx_webshare_proxy_activity_events_account_event_desc
    ON webshare_proxy_activity_events(account_id, event_at DESC);

CREATE INDEX IF NOT EXISTS idx_webshare_proxy_activity_events_account_proxy_endpoint
    ON webshare_proxy_activity_events(account_id, proxy_address, proxy_port);

CREATE INDEX IF NOT EXISTS idx_webshare_proxy_activity_events_account_auth_username
    ON webshare_proxy_activity_events(account_id, auth_username);

create extension if not exists pgcrypto;

create type run_mode as enum ('dry_run', 'shadow', 'live');
create type strategy_status as enum ('pending', 'running', 'stopped', 'failed', 'completed');
create type order_intent_status as enum ('created', 'submitted', 'cancelled', 'expired', 'rejected', 'simulated');
create type order_status as enum ('new', 'partially_filled', 'filled', 'cancelled', 'rejected', 'expired');
create type alert_level as enum ('info', 'warn', 'error', 'critical');

create table bots (
    id uuid primary key default gen_random_uuid(),
    bot_key varchar(64) not null unique,
    exchange_group varchar(64),
    strategy_name varchar(64) not null,
    mode run_mode not null,
    status strategy_status not null default 'pending',
    hostname varchar(255),
    started_at timestamptz,
    stopped_at timestamptz,
    last_seen_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table config_versions (
    id uuid primary key default gen_random_uuid(),
    config_scope varchar(64) not null,
    version_no integer not null,
    config_json jsonb not null,
    checksum varchar(128) not null,
    created_by varchar(128),
    created_at timestamptz not null default now(),
    unique (config_scope, version_no)
);

create index idx_config_versions_scope_created_at
    on config_versions (config_scope, created_at desc);

create table bot_config_assignments (
    id uuid primary key default gen_random_uuid(),
    bot_id uuid not null references bots(id) on delete cascade,
    config_version_id uuid not null references config_versions(id),
    applied boolean not null default false,
    applied_at timestamptz,
    created_at timestamptz not null default now()
);

create index idx_bot_config_assignments_bot_created_at
    on bot_config_assignments (bot_id, created_at desc);

create table strategy_runs (
    id uuid primary key default gen_random_uuid(),
    bot_id uuid not null references bots(id) on delete cascade,
    strategy_name varchar(64) not null,
    mode run_mode not null,
    status strategy_status not null default 'pending',
    started_at timestamptz,
    ended_at timestamptz,
    reason text,
    created_at timestamptz not null default now()
);

create index idx_strategy_runs_bot_created_at
    on strategy_runs (bot_id, created_at desc);

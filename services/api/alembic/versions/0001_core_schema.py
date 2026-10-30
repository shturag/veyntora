"""core schema

Revision ID: 0001
Revises: 
Create Date: 2026-10-30 15:26:04.206433+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('audit_events',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('ts', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('actor_type', sa.Enum('user', 'service', 'system', 'app_key', name='audit_actor_type', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('actor_id', sa.String(length=255), nullable=True),
    sa.Column('actor_name', sa.String(length=255), nullable=True),
    sa.Column('action', sa.String(length=128), nullable=False),
    sa.Column('target_type', sa.String(length=64), nullable=False),
    sa.Column('target_id', sa.String(length=255), nullable=True),
    sa.Column('before', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('after', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('ip', postgresql.INET(), nullable=True),
    sa.Column('user_agent', sa.String(length=512), nullable=True),
    sa.Column('request_id', sa.String(length=64), nullable=True),
    sa.Column('prev_hash', sa.LargeBinary(length=32), nullable=True),
    sa.Column('hash', sa.LargeBinary(length=32), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_events'))
    )
    op.create_index(op.f('ix_audit_events_action'), 'audit_events', ['action'], unique=False)
    op.create_index(op.f('ix_audit_events_actor_id'), 'audit_events', ['actor_id'], unique=False)
    op.create_index(op.f('ix_audit_events_ts'), 'audit_events', ['ts'], unique=False)
    op.create_table('outbox_events',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('ts', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('topic', sa.String(length=128), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_outbox_events'))
    )
    op.create_index(op.f('ix_outbox_events_published_at'), 'outbox_events', ['published_at'], unique=False)
    op.create_index(op.f('ix_outbox_events_topic'), 'outbox_events', ['topic'], unique=False)
    op.create_table('platform_settings',
    sa.Column('id', sa.SmallInteger(), autoincrement=False, nullable=False),
    sa.Column('company_name', sa.String(length=255), server_default='', nullable=False),
    sa.Column('default_locale', sa.String(length=16), server_default='en', nullable=False),
    sa.Column('default_chat_retention_days', sa.Integer(), server_default='90', nullable=False),
    sa.Column('default_trace_retention_days', sa.Integer(), server_default='30', nullable=False),
    sa.Column('privacy_notice_url', sa.String(length=1024), nullable=True),
    sa.Column('imprint_url', sa.String(length=1024), nullable=True),
    sa.Column('extra', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.CheckConstraint('id = 1', name=op.f('ck_platform_settings_single_row')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_platform_settings'))
    )
    op.create_table('provider_instances',
    sa.Column('capability', sa.Enum('llm', 'embedding', 'reranker', 'vector_store', 'parser', 'guardrail', name='provider_capability', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('adapter', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('endpoint', sa.String(length=1024), nullable=True),
    sa.Column('model', sa.String(length=255), nullable=True),
    sa.Column('options', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('hosting', sa.Enum('self_hosted', 'external', name='provider_hosting', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('region', sa.String(length=64), nullable=True),
    sa.Column('fallback_instance_id', sa.Uuid(), nullable=True),
    sa.Column('enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('health_status', sa.Enum('unknown', 'healthy', 'degraded', 'down', name='provider_health', native_enum=False, create_constraint=True, length=32), server_default='unknown', nullable=False),
    sa.Column('health_checked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('health_detail', sa.Text(), nullable=True),
    sa.Column('previous_secret_ref', sa.String(length=512), nullable=True),
    sa.Column('previous_secret_valid_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('secret_ref', sa.String(length=512), nullable=True),
    sa.Column('secret_last4', sa.String(length=4), nullable=True),
    sa.Column('secret_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['fallback_instance_id'], ['provider_instances.id'], name=op.f('fk_provider_instances_fallback_instance_id_provider_instances'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_provider_instances')),
    sa.UniqueConstraint('name', name=op.f('uq_provider_instances_name'))
    )
    op.create_table('users',
    sa.Column('keycloak_sub', sa.String(length=255), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=True),
    sa.Column('display_name', sa.String(length=255), nullable=False),
    sa.Column('locale', sa.String(length=16), nullable=True),
    sa.Column('attributes', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('suspended', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('suspended_reason', sa.Text(), nullable=True),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
    sa.UniqueConstraint('keycloak_sub', name=op.f('uq_users_keycloak_sub'))
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=False)
    op.create_table('access_reviews',
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('due_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('status', sa.Enum('open', 'closed', name='access_review_status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_access_reviews_created_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_access_reviews'))
    )
    op.create_table('budgets',
    sa.Column('scope_type', sa.Enum('chatbot', 'group', 'cost_centre', name='budget_scope', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('scope_id', sa.String(length=64), nullable=False),
    sa.Column('period', sa.String(length=16), server_default='month', nullable=False),
    sa.Column('limit_amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('currency', sa.String(length=3), server_default='EUR', nullable=False),
    sa.Column('notify_at_percent', sa.SmallInteger(), server_default='80', nullable=False),
    sa.Column('action_at_limit', sa.Enum('notify', 'fallback_model', 'fast_only', 'block', name='budget_action', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('fallback_instance_id', sa.Uuid(), nullable=True),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.ForeignKeyConstraint(['fallback_instance_id'], ['provider_instances.id'], name=op.f('fk_budgets_fallback_instance_id_provider_instances'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_budgets')),
    sa.UniqueConstraint('scope_type', 'scope_id', 'period', name=op.f('uq_budgets_scope_type'))
    )
    op.create_table('byok_keys',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('provider', sa.String(length=64), nullable=False),
    sa.Column('label', sa.String(length=255), server_default='', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('secret_ref', sa.String(length=512), nullable=True),
    sa.Column('secret_last4', sa.String(length=4), nullable=True),
    sa.Column('secret_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_byok_keys_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_byok_keys')),
    sa.UniqueConstraint('user_id', 'provider', name=op.f('uq_byok_keys_user_id'))
    )
    op.create_table('chatbots',
    sa.Column('slug', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('description', sa.Text(), server_default='', nullable=False),
    sa.Column('avatar', sa.String(length=512), nullable=True),
    sa.Column('owner_id', sa.Uuid(), nullable=True),
    sa.Column('live_version_id', sa.Uuid(), nullable=True),
    sa.Column('canary_version_id', sa.Uuid(), nullable=True),
    sa.Column('canary_percent', sa.SmallInteger(), server_default='0', nullable=False),
    sa.Column('status', sa.Enum('draft', 'live', 'paused', 'archived', name='chatbot_status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('answer_language', sa.String(length=16), server_default='auto', nullable=False),
    sa.Column('template', sa.String(length=32), nullable=True),
    sa.Column('welcome_message', sa.Text(), server_default='', nullable=False),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.CheckConstraint('canary_percent BETWEEN 0 AND 100', name=op.f('ck_chatbots_canary_percent_range')),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_chatbots_owner_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_chatbots')),
    sa.UniqueConstraint('slug', name=op.f('uq_chatbots_slug'))
    )
    op.create_table('data_sources',
    sa.Column('type', sa.Enum('sharepoint', 'confluence', 'smb', 's3', 'website', 'database', 'upload', name='source_type', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('schedule', sa.String(length=64), nullable=True),
    sa.Column('status', sa.Enum('active', 'paused', 'error', 'disconnected', name='source_status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('owner_id', sa.Uuid(), nullable=True),
    sa.Column('uploaded_by', sa.Uuid(), nullable=True),
    sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_acl_synced_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('secret_ref', sa.String(length=512), nullable=True),
    sa.Column('secret_last4', sa.String(length=4), nullable=True),
    sa.Column('secret_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_data_sources_owner_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], name=op.f('fk_data_sources_uploaded_by_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_data_sources')),
    sa.UniqueConstraint('name', name=op.f('uq_data_sources_name'))
    )
    op.create_table('gdpr_requests',
    sa.Column('kind', sa.Enum('access', 'erasure', name='gdpr_kind', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('subject_user_id', sa.Uuid(), nullable=True),
    sa.Column('subject_email', sa.String(length=320), nullable=False),
    sa.Column('scope', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('status', sa.Enum('received', 'in_progress', 'blocked_legal_hold', 'completed', 'rejected', name='gdpr_status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('due_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('requested_by', sa.Uuid(), nullable=True),
    sa.Column('progress', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('report_key', sa.String(length=1024), nullable=True),
    sa.Column('report_signature', sa.Text(), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['requested_by'], ['users.id'], name=op.f('fk_gdpr_requests_requested_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['subject_user_id'], ['users.id'], name=op.f('fk_gdpr_requests_subject_user_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_gdpr_requests'))
    )
    op.create_table('groups',
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('keycloak_path', sa.String(length=1024), nullable=True),
    sa.Column('keycloak_id', sa.String(length=64), nullable=True),
    sa.Column('source', sa.Enum('keycloak', 'rule', 'manual', name='group_source', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('description', sa.Text(), server_default='', nullable=False),
    sa.Column('rule', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('owner_id', sa.Uuid(), nullable=True),
    sa.Column('cost_centre', sa.String(length=64), nullable=True),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_groups_owner_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_groups')),
    sa.UniqueConstraint('keycloak_id', name=op.f('uq_groups_keycloak_id')),
    sa.UniqueConstraint('keycloak_path', name=op.f('uq_groups_keycloak_path'))
    )
    op.create_table('legal_holds',
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('scope', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('released_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('released_by', sa.Uuid(), nullable=True),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_legal_holds_created_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['released_by'], ['users.id'], name=op.f('fk_legal_holds_released_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_legal_holds'))
    )
    op.create_table('mcp_servers',
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('url', sa.String(length=1024), nullable=False),
    sa.Column('transport', sa.Enum('streamable_http', 'sse', name='mcp_transport', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('auth', sa.Enum('none', 'bearer', 'oauth_client', 'delegated', name='mcp_auth', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('hosting', sa.String(length=16), nullable=False),
    sa.Column('status', sa.Enum('pending_review', 'active', 'disabled', 'error', name='mcp_status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('owner_id', sa.Uuid(), nullable=True),
    sa.Column('security_signoff_by', sa.Uuid(), nullable=True),
    sa.Column('security_signoff_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_discovered_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('secret_ref', sa.String(length=512), nullable=True),
    sa.Column('secret_last4', sa.String(length=4), nullable=True),
    sa.Column('secret_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_mcp_servers_owner_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['security_signoff_by'], ['users.id'], name=op.f('fk_mcp_servers_security_signoff_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_mcp_servers')),
    sa.UniqueConstraint('name', name=op.f('uq_mcp_servers_name'))
    )
    op.create_table('status_notices',
    sa.Column('kind', sa.Enum('incident', 'maintenance', 'info', name='status_notice_kind', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('components', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
    sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ends_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_status_notices_created_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_status_notices'))
    )
    op.create_table('access_review_items',
    sa.Column('review_id', sa.Uuid(), nullable=False),
    sa.Column('group_id', sa.Uuid(), nullable=False),
    sa.Column('owner_id', sa.Uuid(), nullable=True),
    sa.Column('status', sa.Enum('waiting', 'confirmed', 'overdue', name='access_review_item_status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('changes', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('decided_by', sa.Uuid(), nullable=True),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.ForeignKeyConstraint(['decided_by'], ['users.id'], name=op.f('fk_access_review_items_decided_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['group_id'], ['groups.id'], name=op.f('fk_access_review_items_group_id_groups'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_access_review_items_owner_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['review_id'], ['access_reviews.id'], name=op.f('fk_access_review_items_review_id_access_reviews'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_access_review_items')),
    sa.UniqueConstraint('review_id', 'group_id', name=op.f('uq_access_review_items_review_id'))
    )
    op.create_table('app_keys',
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('chatbot_id', sa.Uuid(), nullable=True),
    sa.Column('key_prefix', sa.String(length=16), nullable=False),
    sa.Column('key_hash', sa.String(length=128), nullable=False),
    sa.Column('scopes', postgresql.ARRAY(sa.String(length=64)), server_default='{}', nullable=False),
    sa.Column('rate_limit_per_minute', sa.Integer(), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.ForeignKeyConstraint(['chatbot_id'], ['chatbots.id'], name=op.f('fk_app_keys_chatbot_id_chatbots'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_app_keys_created_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_app_keys')),
    sa.UniqueConstraint('key_prefix', name=op.f('uq_app_keys_key_prefix'))
    )
    op.create_table('automations',
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('description', sa.Text(), server_default='', nullable=False),
    sa.Column('chatbot_id', sa.Uuid(), nullable=True),
    sa.Column('trigger', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('steps', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
    sa.Column('service_identity', sa.String(length=255), nullable=True),
    sa.Column('status', sa.Enum('draft', 'active', 'paused', name='automation_status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('owner_id', sa.Uuid(), nullable=True),
    sa.Column('next_run_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.ForeignKeyConstraint(['chatbot_id'], ['chatbots.id'], name=op.f('fk_automations_chatbot_id_chatbots'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_automations_owner_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_automations'))
    )
    op.create_table('channels',
    sa.Column('chatbot_id', sa.Uuid(), nullable=False),
    sa.Column('type', sa.Enum('teams', 'slack', 'web_widget', name='channel_type', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('status', sa.Enum('pending', 'connected', 'disconnected', 'error', name='channel_status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('secret_ref', sa.String(length=512), nullable=True),
    sa.Column('secret_last4', sa.String(length=4), nullable=True),
    sa.Column('secret_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['chatbot_id'], ['chatbots.id'], name=op.f('fk_channels_chatbot_id_chatbots'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_channels'))
    )
    op.create_table('conversations',
    sa.Column('chatbot_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('title', sa.String(length=255), server_default='', nullable=False),
    sa.Column('thread_id', sa.String(length=64), nullable=True),
    sa.Column('channel', sa.String(length=32), server_default='web', nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['chatbot_id'], ['chatbots.id'], name=op.f('fk_conversations_chatbot_id_chatbots'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_conversations_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_conversations')),
    sa.UniqueConstraint('thread_id', name=op.f('uq_conversations_thread_id'))
    )
    op.create_index(op.f('ix_conversations_chatbot_id'), 'conversations', ['chatbot_id'], unique=False)
    op.create_index(op.f('ix_conversations_user_id'), 'conversations', ['user_id'], unique=False)
    op.create_table('documents',
    sa.Column('source_id', sa.Uuid(), nullable=False),
    sa.Column('path', sa.String(length=2048), nullable=False),
    sa.Column('title', sa.String(length=1024), server_default='', nullable=False),
    sa.Column('url', sa.String(length=2048), nullable=True),
    sa.Column('mime_type', sa.String(length=255), nullable=True),
    sa.Column('size_bytes', sa.BigInteger(), nullable=True),
    sa.Column('language', sa.String(length=16), nullable=True),
    sa.Column('hash', sa.String(length=128), nullable=True),
    sa.Column('object_key', sa.String(length=1024), nullable=True),
    sa.Column('acl', postgresql.JSONB(astext_type=sa.Text()), server_default='{"users": [], "groups": []}', nullable=False),
    sa.Column('status', sa.Enum('pending', 'indexed', 'failed', 'deleted', name='document_status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('chunk_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('source_updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['source_id'], ['data_sources.id'], name=op.f('fk_documents_source_id_data_sources'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_documents')),
    sa.UniqueConstraint('source_id', 'path', name=op.f('uq_documents_source_id'))
    )
    op.create_table('eval_sets',
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('description', sa.Text(), server_default='', nullable=False),
    sa.Column('chatbot_id', sa.Uuid(), nullable=True),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.ForeignKeyConstraint(['chatbot_id'], ['chatbots.id'], name=op.f('fk_eval_sets_chatbot_id_chatbots'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_eval_sets_created_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_eval_sets')),
    sa.UniqueConstraint('name', name=op.f('uq_eval_sets_name'))
    )
    op.create_table('governance_rules',
    sa.Column('chatbot_id', sa.Uuid(), nullable=False),
    sa.Column('chat_retention_days', sa.Integer(), server_default='90', nullable=False),
    sa.Column('trace_retention_days', sa.Integer(), server_default='30', nullable=False),
    sa.Column('allowed_external_instance_ids', postgresql.ARRAY(sa.Uuid()), server_default='{}', nullable=False),
    sa.Column('allow_byok', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('mask_pii_before_external', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.ForeignKeyConstraint(['chatbot_id'], ['chatbots.id'], name=op.f('fk_governance_rules_chatbot_id_chatbots'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_governance_rules')),
    sa.UniqueConstraint('chatbot_id', name=op.f('uq_governance_rules_chatbot_id'))
    )
    op.create_table('knowledge_issues',
    sa.Column('kind', sa.Enum('stale', 'conflict', 'gap', 'parse_failure', name='knowledge_issue_kind', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('chatbot_id', sa.Uuid(), nullable=True),
    sa.Column('document_ids', postgresql.ARRAY(sa.Uuid()), server_default='{}', nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('owner_id', sa.Uuid(), nullable=True),
    sa.Column('status', sa.Enum('open', 'notified', 'resolved', 'dismissed', name='knowledge_issue_status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('notified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['chatbot_id'], ['chatbots.id'], name=op.f('fk_knowledge_issues_chatbot_id_chatbots'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_knowledge_issues_owner_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_knowledge_issues'))
    )
    op.create_table('memberships',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('group_id', sa.Uuid(), nullable=False),
    sa.Column('source', sa.Enum('keycloak', 'rule', 'manual', name='membership_source', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['group_id'], ['groups.id'], name=op.f('fk_memberships_group_id_groups'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_memberships_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'group_id', name=op.f('pk_memberships'))
    )
    op.create_index(op.f('ix_memberships_group_id'), 'memberships', ['group_id'], unique=False)
    op.create_table('pipeline_versions',
    sa.Column('chatbot_id', sa.Uuid(), nullable=False),
    sa.Column('number', sa.Integer(), nullable=False),
    sa.Column('spec', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('status', sa.Enum('draft', 'canary', 'live', 'archived', name='pipeline_status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('change_note', sa.Text(), server_default='', nullable=False),
    sa.Column('eval_run_id', sa.Uuid(), nullable=True),
    sa.Column('compiled', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.ForeignKeyConstraint(['chatbot_id'], ['chatbots.id'], name=op.f('fk_pipeline_versions_chatbot_id_chatbots'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_pipeline_versions_created_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_pipeline_versions')),
    sa.UniqueConstraint('chatbot_id', 'number', name=op.f('uq_pipeline_versions_chatbot_id'))
    )
    op.create_table('provider_instance_chatbots',
    sa.Column('provider_instance_id', sa.Uuid(), nullable=False),
    sa.Column('chatbot_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['chatbot_id'], ['chatbots.id'], name=op.f('fk_provider_instance_chatbots_chatbot_id_chatbots'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['provider_instance_id'], ['provider_instances.id'], name=op.f('fk_provider_instance_chatbots_provider_instance_id_provider_instances'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('provider_instance_id', 'chatbot_id', name=op.f('pk_provider_instance_chatbots'))
    )
    op.create_table('source_attachments',
    sa.Column('chatbot_id', sa.Uuid(), nullable=False),
    sa.Column('source_id', sa.Uuid(), nullable=False),
    sa.Column('scope', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('weight', sa.Float(), server_default='1.0', nullable=False),
    sa.Column('enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.CheckConstraint('weight > 0 AND weight <= 10', name=op.f('ck_source_attachments_weight_range')),
    sa.ForeignKeyConstraint(['chatbot_id'], ['chatbots.id'], name=op.f('fk_source_attachments_chatbot_id_chatbots'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_id'], ['data_sources.id'], name=op.f('fk_source_attachments_source_id_data_sources'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_source_attachments')),
    sa.UniqueConstraint('chatbot_id', 'source_id', name=op.f('uq_source_attachments_chatbot_id'))
    )
    op.create_table('tools',
    sa.Column('server_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('description', sa.Text(), server_default='', nullable=False),
    sa.Column('input_schema', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('access', sa.Enum('read', 'write', name='tool_access', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('enabled', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.ForeignKeyConstraint(['server_id'], ['mcp_servers.id'], name=op.f('fk_tools_server_id_mcp_servers'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tools')),
    sa.UniqueConstraint('server_id', 'name', name=op.f('uq_tools_server_id'))
    )
    op.create_table('eval_runs',
    sa.Column('eval_set_id', sa.Uuid(), nullable=False),
    sa.Column('pipeline_version_id', sa.Uuid(), nullable=False),
    sa.Column('baseline_version_id', sa.Uuid(), nullable=True),
    sa.Column('status', sa.Enum('queued', 'running', 'succeeded', 'failed', 'cancelled', name='eval_run_status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('use_llm_judge', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('scores', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('gate_passed', sa.Boolean(), nullable=True),
    sa.Column('gate_detail', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('report_key', sa.String(length=1024), nullable=True),
    sa.Column('started_by', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.ForeignKeyConstraint(['baseline_version_id'], ['pipeline_versions.id'], name=op.f('fk_eval_runs_baseline_version_id_pipeline_versions'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['eval_set_id'], ['eval_sets.id'], name=op.f('fk_eval_runs_eval_set_id_eval_sets'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['pipeline_version_id'], ['pipeline_versions.id'], name=op.f('fk_eval_runs_pipeline_version_id_pipeline_versions'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['started_by'], ['users.id'], name=op.f('fk_eval_runs_started_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_eval_runs'))
    )
    op.create_index(op.f('ix_eval_runs_pipeline_version_id'), 'eval_runs', ['pipeline_version_id'], unique=False)
    op.create_table('ingest_jobs',
    sa.Column('source_id', sa.Uuid(), nullable=False),
    sa.Column('document_id', sa.Uuid(), nullable=True),
    sa.Column('kind', sa.Enum('sync', 'reindex', 'ocr_retry', 'acl_sync', 'upload', name='ingest_job_kind', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('status', sa.Enum('queued', 'running', 'succeeded', 'failed', 'cancelled', name='ingest_job_status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('stats', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('triggered_by', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], name=op.f('fk_ingest_jobs_document_id_documents'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_id'], ['data_sources.id'], name=op.f('fk_ingest_jobs_source_id_data_sources'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['triggered_by'], ['users.id'], name=op.f('fk_ingest_jobs_triggered_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ingest_jobs'))
    )
    op.create_index(op.f('ix_ingest_jobs_source_id'), 'ingest_jobs', ['source_id'], unique=False)
    op.create_table('messages',
    sa.Column('conversation_id', sa.Uuid(), nullable=False),
    sa.Column('role', sa.Enum('user', 'assistant', 'tool', 'system', name='message_role', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('mode_requested', sa.Enum('auto', 'fast', 'agent', name='message_mode_requested', native_enum=False, create_constraint=True, length=32), nullable=True),
    sa.Column('mode_used', sa.Enum('fast', 'agent', name='message_mode_used', native_enum=False, create_constraint=True, length=32), nullable=True),
    sa.Column('route_reason', sa.Text(), nullable=True),
    sa.Column('pipeline_version_id', sa.Uuid(), nullable=True),
    sa.Column('tokens_in', sa.Integer(), server_default='0', nullable=False),
    sa.Column('tokens_out', sa.Integer(), server_default='0', nullable=False),
    sa.Column('cost', sa.Numeric(precision=12, scale=6), server_default='0', nullable=False),
    sa.Column('latency_ms', sa.Integer(), nullable=True),
    sa.Column('groundedness', sa.Float(), nullable=True),
    sa.Column('external_egress', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('trace_id', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], name=op.f('fk_messages_conversation_id_conversations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['pipeline_version_id'], ['pipeline_versions.id'], name=op.f('fk_messages_pipeline_version_id_pipeline_versions'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_messages'))
    )
    op.create_index(op.f('ix_messages_conversation_id'), 'messages', ['conversation_id'], unique=False)
    op.create_index(op.f('ix_messages_trace_id'), 'messages', ['trace_id'], unique=False)
    op.create_table('runs',
    sa.Column('kind', sa.Enum('chat_agent', 'automation', name='run_kind', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('automation_id', sa.Uuid(), nullable=True),
    sa.Column('conversation_id', sa.Uuid(), nullable=True),
    sa.Column('chatbot_id', sa.Uuid(), nullable=True),
    sa.Column('started_by', sa.Uuid(), nullable=True),
    sa.Column('status', sa.Enum('queued', 'running', 'waiting_approval', 'succeeded', 'failed', 'cancelled', name='run_status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('dry_run', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('thread_id', sa.String(length=64), nullable=True),
    sa.Column('checkpoint_id', sa.String(length=64), nullable=True),
    sa.Column('trace_id', sa.String(length=64), nullable=True),
    sa.Column('steps', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.ForeignKeyConstraint(['automation_id'], ['automations.id'], name=op.f('fk_runs_automation_id_automations'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['chatbot_id'], ['chatbots.id'], name=op.f('fk_runs_chatbot_id_chatbots'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], name=op.f('fk_runs_conversation_id_conversations'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['started_by'], ['users.id'], name=op.f('fk_runs_started_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_runs'))
    )
    op.create_index(op.f('ix_runs_automation_id'), 'runs', ['automation_id'], unique=False)
    op.create_table('tool_policies',
    sa.Column('tool_id', sa.Uuid(), nullable=False),
    sa.Column('chatbot_id', sa.Uuid(), nullable=True),
    sa.Column('requires_approval', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('approver_group_id', sa.Uuid(), nullable=True),
    sa.Column('allowed_recipients', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('rate_limit_per_minute', sa.Integer(), nullable=True),
    sa.Column('constraints', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.ForeignKeyConstraint(['approver_group_id'], ['groups.id'], name=op.f('fk_tool_policies_approver_group_id_groups'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['chatbot_id'], ['chatbots.id'], name=op.f('fk_tool_policies_chatbot_id_chatbots'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tool_id'], ['tools.id'], name=op.f('fk_tool_policies_tool_id_tools'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tool_policies')),
    sa.UniqueConstraint('tool_id', 'chatbot_id', name=op.f('uq_tool_policies_tool_id'))
    )
    op.create_table('approvals',
    sa.Column('run_id', sa.Uuid(), nullable=False),
    sa.Column('tool_id', sa.Uuid(), nullable=True),
    sa.Column('action_summary', sa.Text(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('requested_by', sa.Uuid(), nullable=True),
    sa.Column('approver_group_id', sa.Uuid(), nullable=True),
    sa.Column('approver_id', sa.Uuid(), nullable=True),
    sa.Column('delegate_id', sa.Uuid(), nullable=True),
    sa.Column('decision', sa.Enum('pending', 'approved', 'rejected', 'expired', name='approval_decision', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('interrupt_id', sa.String(length=128), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.ForeignKeyConstraint(['approver_group_id'], ['groups.id'], name=op.f('fk_approvals_approver_group_id_groups'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['approver_id'], ['users.id'], name=op.f('fk_approvals_approver_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['delegate_id'], ['users.id'], name=op.f('fk_approvals_delegate_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['requested_by'], ['users.id'], name=op.f('fk_approvals_requested_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['run_id'], ['runs.id'], name=op.f('fk_approvals_run_id_runs'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tool_id'], ['tools.id'], name=op.f('fk_approvals_tool_id_tools'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_approvals'))
    )
    op.create_index(op.f('ix_approvals_run_id'), 'approvals', ['run_id'], unique=False)
    op.create_table('citations',
    sa.Column('message_id', sa.Uuid(), nullable=False),
    sa.Column('document_id', sa.Uuid(), nullable=True),
    sa.Column('chunk_id', sa.String(length=128), nullable=False),
    sa.Column('ordinal', sa.SmallInteger(), nullable=False),
    sa.Column('quote', sa.Text(), nullable=False),
    sa.Column('score', sa.Float(), nullable=True),
    sa.Column('page', sa.Integer(), nullable=True),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], name=op.f('fk_citations_document_id_documents'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['message_id'], ['messages.id'], name=op.f('fk_citations_message_id_messages'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_citations'))
    )
    op.create_index(op.f('ix_citations_document_id'), 'citations', ['document_id'], unique=False)
    op.create_index(op.f('ix_citations_message_id'), 'citations', ['message_id'], unique=False)
    op.create_table('feedback',
    sa.Column('message_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('rating', sa.Enum('up', 'down', name='feedback_rating', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('reason', sa.String(length=64), nullable=True),
    sa.Column('comment', sa.Text(), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('reviewer_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.ForeignKeyConstraint(['message_id'], ['messages.id'], name=op.f('fk_feedback_message_id_messages'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['reviewer_id'], ['users.id'], name=op.f('fk_feedback_reviewer_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_feedback_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_feedback')),
    sa.UniqueConstraint('message_id', 'user_id', name=op.f('uq_feedback_message_id'))
    )
    op.create_table('handoffs',
    sa.Column('conversation_id', sa.Uuid(), nullable=False),
    sa.Column('message_id', sa.Uuid(), nullable=True),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('expert_group_id', sa.Uuid(), nullable=True),
    sa.Column('assignee_id', sa.Uuid(), nullable=True),
    sa.Column('status', sa.Enum('open', 'assigned', 'answered', 'closed', name='handoff_status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('question', sa.Text(), nullable=False),
    sa.Column('answer', sa.Text(), nullable=True),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['assignee_id'], ['users.id'], name=op.f('fk_handoffs_assignee_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], name=op.f('fk_handoffs_conversation_id_conversations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['expert_group_id'], ['groups.id'], name=op.f('fk_handoffs_expert_group_id_groups'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['message_id'], ['messages.id'], name=op.f('fk_handoffs_message_id_messages'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_handoffs_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_handoffs'))
    )
    op.create_table('saved_answers',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('message_id', sa.Uuid(), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('stale', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('refreshed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['message_id'], ['messages.id'], name=op.f('fk_saved_answers_message_id_messages'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_saved_answers_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_saved_answers'))
    )
    op.create_index(op.f('ix_saved_answers_user_id'), 'saved_answers', ['user_id'], unique=False)
    op.create_table('usage_records',
    sa.Column('ts', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=True),
    sa.Column('chatbot_id', sa.Uuid(), nullable=True),
    sa.Column('cost_centre', sa.String(length=64), nullable=True),
    sa.Column('provider_instance_id', sa.Uuid(), nullable=True),
    sa.Column('message_id', sa.Uuid(), nullable=True),
    sa.Column('app_key_id', sa.Uuid(), nullable=True),
    sa.Column('tokens_in', sa.Integer(), server_default='0', nullable=False),
    sa.Column('tokens_out', sa.Integer(), server_default='0', nullable=False),
    sa.Column('cost', sa.Numeric(precision=12, scale=6), server_default='0', nullable=False),
    sa.Column('external', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('byok', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.ForeignKeyConstraint(['app_key_id'], ['app_keys.id'], name=op.f('fk_usage_records_app_key_id_app_keys'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['chatbot_id'], ['chatbots.id'], name=op.f('fk_usage_records_chatbot_id_chatbots'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['message_id'], ['messages.id'], name=op.f('fk_usage_records_message_id_messages'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['provider_instance_id'], ['provider_instances.id'], name=op.f('fk_usage_records_provider_instance_id_provider_instances'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_usage_records_user_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_usage_records'))
    )
    op.create_index('ix_usage_records_ts_chatbot', 'usage_records', ['ts', 'chatbot_id'], unique=False)
    op.create_table('eval_cases',
    sa.Column('eval_set_id', sa.Uuid(), nullable=False),
    sa.Column('question', sa.Text(), nullable=False),
    sa.Column('expected_answer', sa.Text(), nullable=True),
    sa.Column('expected_sources', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
    sa.Column('expected_tools', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
    sa.Column('tags', postgresql.ARRAY(sa.String(length=64)), server_default='{}', nullable=False),
    sa.Column('origin', sa.Enum('manual', 'imported', 'generated', 'feedback', name='eval_case_origin', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('feedback_id', sa.Uuid(), nullable=True),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['eval_set_id'], ['eval_sets.id'], name=op.f('fk_eval_cases_eval_set_id_eval_sets'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['feedback_id'], ['feedback.id'], name=op.f('fk_eval_cases_feedback_id_feedback'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_eval_cases'))
    )
    op.create_index(op.f('ix_eval_cases_eval_set_id'), 'eval_cases', ['eval_set_id'], unique=False)
    op.create_table('saved_answer_shares',
    sa.Column('saved_answer_id', sa.Uuid(), nullable=False),
    sa.Column('group_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['group_id'], ['groups.id'], name=op.f('fk_saved_answer_shares_group_id_groups'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['saved_answer_id'], ['saved_answers.id'], name=op.f('fk_saved_answer_shares_saved_answer_id_saved_answers'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('saved_answer_id', 'group_id', name=op.f('pk_saved_answer_shares'))
    )

    # Circular references between chatbots, pipeline_versions and eval_runs.
    op.create_foreign_key(op.f("fk_chatbots_live_version_id_pipeline_versions"), "chatbots",
                          "pipeline_versions", ["live_version_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key(op.f("fk_chatbots_canary_version_id_pipeline_versions"), "chatbots",
                          "pipeline_versions", ["canary_version_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key(op.f("fk_pipeline_versions_eval_run_id_eval_runs"), "pipeline_versions",
                          "eval_runs", ["eval_run_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    op.drop_constraint(op.f("fk_pipeline_versions_eval_run_id_eval_runs"), "pipeline_versions",
                       type_="foreignkey")
    op.drop_constraint(op.f("fk_chatbots_canary_version_id_pipeline_versions"), "chatbots",
                       type_="foreignkey")
    op.drop_constraint(op.f("fk_chatbots_live_version_id_pipeline_versions"), "chatbots",
                       type_="foreignkey")
    op.drop_table('saved_answer_shares')
    op.drop_index(op.f('ix_eval_cases_eval_set_id'), table_name='eval_cases')
    op.drop_table('eval_cases')
    op.drop_index('ix_usage_records_ts_chatbot', table_name='usage_records')
    op.drop_table('usage_records')
    op.drop_index(op.f('ix_saved_answers_user_id'), table_name='saved_answers')
    op.drop_table('saved_answers')
    op.drop_table('handoffs')
    op.drop_table('feedback')
    op.drop_index(op.f('ix_citations_message_id'), table_name='citations')
    op.drop_index(op.f('ix_citations_document_id'), table_name='citations')
    op.drop_table('citations')
    op.drop_index(op.f('ix_approvals_run_id'), table_name='approvals')
    op.drop_table('approvals')
    op.drop_table('tool_policies')
    op.drop_index(op.f('ix_runs_automation_id'), table_name='runs')
    op.drop_table('runs')
    op.drop_index(op.f('ix_messages_trace_id'), table_name='messages')
    op.drop_index(op.f('ix_messages_conversation_id'), table_name='messages')
    op.drop_table('messages')
    op.drop_index(op.f('ix_ingest_jobs_source_id'), table_name='ingest_jobs')
    op.drop_table('ingest_jobs')
    op.drop_index(op.f('ix_eval_runs_pipeline_version_id'), table_name='eval_runs')
    op.drop_table('eval_runs')
    op.drop_table('tools')
    op.drop_table('source_attachments')
    op.drop_table('provider_instance_chatbots')
    op.drop_table('pipeline_versions')
    op.drop_index(op.f('ix_memberships_group_id'), table_name='memberships')
    op.drop_table('memberships')
    op.drop_table('knowledge_issues')
    op.drop_table('governance_rules')
    op.drop_table('eval_sets')
    op.drop_table('documents')
    op.drop_index(op.f('ix_conversations_user_id'), table_name='conversations')
    op.drop_index(op.f('ix_conversations_chatbot_id'), table_name='conversations')
    op.drop_table('conversations')
    op.drop_table('channels')
    op.drop_table('automations')
    op.drop_table('app_keys')
    op.drop_table('access_review_items')
    op.drop_table('status_notices')
    op.drop_table('mcp_servers')
    op.drop_table('legal_holds')
    op.drop_table('groups')
    op.drop_table('gdpr_requests')
    op.drop_table('data_sources')
    op.drop_table('chatbots')
    op.drop_table('byok_keys')
    op.drop_table('budgets')
    op.drop_table('access_reviews')
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_table('users')
    op.drop_table('provider_instances')
    op.drop_table('platform_settings')
    op.drop_index(op.f('ix_outbox_events_topic'), table_name='outbox_events')
    op.drop_index(op.f('ix_outbox_events_published_at'), table_name='outbox_events')
    op.drop_table('outbox_events')
    op.drop_index(op.f('ix_audit_events_ts'), table_name='audit_events')
    op.drop_index(op.f('ix_audit_events_actor_id'), table_name='audit_events')
    op.drop_index(op.f('ix_audit_events_action'), table_name='audit_events')
    op.drop_table('audit_events')

"""More data sources: Nextcloud/WebDAV, SharePoint Server, CMIS, Git, ServiceNow, Jira

Revision ID: 0027
Revises: 0026
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = ("sharepoint", "confluence", "smb", "s3", "website", "database", "upload")
_ADDED = ("webdav", "sharepoint_server", "cmis", "git", "servicenow", "jira")


def _types(values: tuple[str, ...]) -> None:
    # op.f: the name is final (the naming convention would prefix it again).
    name = op.f("ck_data_sources_source_type")
    op.drop_constraint(name, "data_sources", type_="check")
    listed = ", ".join(f"'{v}'" for v in values)
    op.create_check_constraint(name, "data_sources", f"type IN ({listed})")


def upgrade() -> None:
    _types((*_OLD, *_ADDED))


def downgrade() -> None:
    # Sources of the new kinds cannot exist under the old check: they are removed first.
    added = ", ".join(f"'{v}'" for v in _ADDED)
    op.execute(f"DELETE FROM data_sources WHERE type IN ({added})")
    _types(_OLD)

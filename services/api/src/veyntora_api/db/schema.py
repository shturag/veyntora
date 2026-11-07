"""The database schema this code needs: the newest Alembic revision.

Part of the version the launchers compare (infra/launcher.py), so an update that brings a
migration bootstraps again. Every image has this module; not every image has the migrations,
so it is a constant, and a test keeps it equal to the newest revision.
"""

SCHEMA_HEAD = "0028"

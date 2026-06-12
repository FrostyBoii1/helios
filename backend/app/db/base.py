"""Aggregates all models for Alembic autogenerate and metadata creation.

Import this module (not individual model modules) wherever you need every table
registered on `Base.metadata` — notably Alembic's env.py. Adding a new model?
Import it here.
"""

# ruff: noqa: F401  (imports are intentional side effects: model registration)
from app.db.base_class import Base
from app.models.activity import Activity
from app.models.customer import Customer
from app.models.document import Document
from app.models.job import Job
from app.models.role import Role
from app.models.task import Task
from app.models.user import User

__all__ = [
    "Base",
    "Activity",
    "Customer",
    "Document",
    "Job",
    "Role",
    "Task",
    "User",
]

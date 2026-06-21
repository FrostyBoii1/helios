"""Aggregates all models for Alembic autogenerate and metadata creation.

Import this module (not individual model modules) wherever you need every table
registered on `Base.metadata` — notably Alembic's env.py. Adding a new model?
Import it here.
"""

# ruff: noqa: F401  (imports are intentional side effects: model registration)
from app.db.base_class import Base
from app.models.activity import Activity
from app.models.customer import Customer
from app.models.customer_contact_variant import CustomerContactVariant
from app.models.document import Document
from app.models.hardware import HardwareAlias, HardwareCatalogue
from app.models.import_staging import ImportBatch, ImportIssue, ImportRow
from app.models.job import Job
from app.models.job_label import JobLabelAssignment, JobLabelDefinition
from app.models.role import Role
from app.models.task import Task
from app.models.user import User

__all__ = [
    "Base",
    "Activity",
    "Customer",
    "CustomerContactVariant",
    "Document",
    "HardwareAlias",
    "HardwareCatalogue",
    "ImportBatch",
    "ImportIssue",
    "ImportRow",
    "Job",
    "JobLabelAssignment",
    "JobLabelDefinition",
    "Role",
    "Task",
    "User",
]

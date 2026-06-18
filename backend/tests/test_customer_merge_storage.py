"""Tests for the B4-1 customer-merge STORAGE foundation (no execution).

``resolve_active_customer()`` walks the ``merged_into_customer_id`` chain to the
live winner; these prove its read-only resolution semantics. Synthetic data inside
the rolled-back ``db_session`` — nothing persists. There is NO merge execution yet
(B4-2+); tests set the storage columns directly to simulate a post-merge state.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.services.customers import resolve_active_customer


def _customer(db: Session, name: str, **kw) -> Customer:
    c = Customer(full_name=name, **kw)
    db.add(c)
    db.flush()
    return c


def test_normal_active_customer_resolves_to_itself(db_session: Session):
    c = _customer(db_session, "Active Only")
    assert resolve_active_customer(db_session, c.id) is c
    # never merged, never deleted (storage columns default NULL)
    assert c.merged_into_customer_id is None
    assert c.merged_at is None


def test_one_hop_loser_resolves_to_winner(db_session: Session):
    winner = _customer(db_session, "Winner")
    loser = _customer(db_session, "Loser")
    # simulate a B4-2 merge result: loser soft-deleted + pointed at the winner
    now = datetime.now(timezone.utc)
    loser.merged_into_customer_id = winner.id
    loser.merged_at = now
    loser.deleted_at = now
    db_session.flush()
    assert resolve_active_customer(db_session, loser.id) is winner


def test_multi_hop_chain_resolves_to_final_winner(db_session: Session):
    final = _customer(db_session, "Final Winner")
    mid = _customer(db_session, "Mid Winner")
    loser = _customer(db_session, "First Loser")
    now = datetime.now(timezone.utc)
    mid.merged_into_customer_id = final.id
    mid.merged_at = now
    mid.deleted_at = now
    loser.merged_into_customer_id = mid.id
    loser.merged_at = now
    loser.deleted_at = now
    db_session.flush()
    # loser -> mid -> final; resolving the head or the middle both reach `final`
    assert resolve_active_customer(db_session, loser.id) is final
    assert resolve_active_customer(db_session, mid.id) is final


def test_cycle_is_guarded_and_returns_none(db_session: Session):
    a = _customer(db_session, "Cycle A")
    b = _customer(db_session, "Cycle B")
    now = datetime.now(timezone.utc)
    a.merged_into_customer_id = b.id
    b.merged_into_customer_id = a.id
    a.deleted_at = now
    b.deleted_at = now
    db_session.flush()
    # must TERMINATE (cycle guard) and report no safe winner from either entry
    assert resolve_active_customer(db_session, a.id) is None
    assert resolve_active_customer(db_session, b.id) is None


def test_missing_customer_returns_none(db_session: Session):
    assert resolve_active_customer(db_session, 999_999_999) is None


def test_chain_ending_at_deleted_winner_returns_none(db_session: Session):
    # The chain's final node is soft-deleted but NOT further merged -> there is no
    # active customer to resolve to ("active when possible" yields None).
    dead_winner = _customer(db_session, "Dead Winner")
    loser = _customer(db_session, "Loser To Dead")
    now = datetime.now(timezone.utc)
    dead_winner.deleted_at = now  # deleted, merged_into stays NULL
    loser.merged_into_customer_id = dead_winner.id
    loser.merged_at = now
    loser.deleted_at = now
    db_session.flush()
    assert resolve_active_customer(db_session, loser.id) is None

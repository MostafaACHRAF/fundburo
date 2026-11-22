from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException

import main as app_main
from main import (
    ClaimCreate,
    ExtractedItemFields,
    FreeTextCreate,
    IntakeApproveRequest,
    MatchCreate,
    MatchItem,
    ReportCreate,
)
from models import AppUser, IntakeApprovalRecord, Item, ItemMatch


class _ScalarList:
    def __init__(self, values):
        self._values = values

    def all(self):
        return self._values


class ScriptedSession:
    def __init__(self, scalar_results=None, scalars_results=None):
        self.scalar_results = list(scalar_results or [])
        self.scalars_results = list(scalars_results or [])
        self.added = []
        self.commits = 0
        self.rollbacks = 0
        self._id = 0

    def scalar(self, _stmt):
        if not self.scalar_results:
            return None
        return self.scalar_results.pop(0)

    def scalars(self, _stmt):
        if not self.scalars_results:
            return _ScalarList([])
        return _ScalarList(self.scalars_results.pop(0))

    def add(self, obj):
        self.added.append(obj)

    def _assign_ids(self):
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                self._id += 1
                obj.id = self._id
            if isinstance(obj, Item) and getattr(obj, "status", None) is None:
                obj.status = "active"

    def flush(self):
        self._assign_ids()

    def commit(self):
        self.commits += 1
        self._assign_ids()

    def rollback(self):
        self.rollbacks += 1

    def refresh(self, obj):
        if getattr(obj, "id", None) is None:
            self._id += 1
            obj.id = self._id
        if isinstance(obj, Item) and getattr(obj, "status", None) is None:
            obj.status = "active"


def test_extract_freetext_returns_structured_fields():
    payload = FreeTextCreate(
        item_type="lost",
        free_text="I lost a black wallet near Warschauer Strasse, Berlin on 2026-11-10T18:50:00+01:00",
    )

    result = app_main.extract_freetext(payload)

    assert result.item_type == "lost"
    assert result.extracted_fields.description.startswith("I lost a black wallet")
    assert result.extracted_fields.address_text == "Warschauer Strasse, Berlin"
    assert result.extracted_fields.event_time is not None
    assert "description" not in result.missing_fields


def test_submit_claim_creates_item_with_embedding(monkeypatch):
    monkeypatch.setattr(app_main, "calculate_matches_for_item", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(app_main, "get_text_embedding", lambda _text: [0.1, 0.2, 0.3])

    user = AppUser(username="u", email="u@test.com", role="claimer")
    user.id = 10
    db = ScriptedSession(scalar_results=[user])
    payload = ClaimCreate(
        username="u",
        email="u@test.com",
        description="Lost black wallet",
        address_text="Berlin",
        lat=52.5,
        lng=13.4,
    )

    result = app_main.submit_claim(payload, db)

    created_item = next(obj for obj in db.added if isinstance(obj, Item))
    assert created_item.description_embedding == [0.1, 0.2, 0.3]
    assert result.user_id == 10
    assert result.item_id == created_item.id


def test_get_claims_returns_items():
    db = ScriptedSession(scalars_results=[[Item(user_id=1, item_type="lost", description="x")]])
    result = app_main.get_claims(db)
    assert len(result) == 1


def test_submit_report_creates_item_with_embedding(monkeypatch):
    monkeypatch.setattr(app_main, "calculate_matches_for_item", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(app_main, "get_text_embedding", lambda _text: [0.9, 0.8])

    user = AppUser(username="r", email="r@test.com", role="reporter")
    user.id = 20
    db = ScriptedSession(scalar_results=[user])
    payload = ReportCreate(
        username="r",
        email="r@test.com",
        description="Found black wallet",
        address_text="Berlin",
        lat=52.5,
        lng=13.4,
    )

    result = app_main.submit_report(payload, db)

    created_item = next(obj for obj in db.added if isinstance(obj, Item))
    assert created_item.description_embedding == [0.9, 0.8]
    assert result.user_id == 20


def test_get_reports_returns_items():
    db = ScriptedSession(scalars_results=[[Item(user_id=1, item_type="found", description="x")]])
    result = app_main.get_reports(db)
    assert len(result) == 1


def test_approve_intake_returns_existing_item_for_same_idempotency_key():
    existing_record = IntakeApprovalRecord(idempotency_key="same-key", item_id=55)
    existing_item = Item(user_id=7, item_type="lost", description="already")
    existing_item.id = 55
    existing_item.status = "active"
    db = ScriptedSession(scalar_results=[existing_record, existing_item])

    payload = IntakeApproveRequest(
        username="a",
        email="a@test.com",
        item_type="lost",
        idempotency_key="same-key",
        extracted_fields=ExtractedItemFields(
            description="already",
            address_text="Berlin",
            event_time=datetime.now(timezone.utc),
        ),
    )

    result = app_main.approve_intake(payload, db)

    assert result.item_id == 55
    assert result.user_id == 7


def test_approve_intake_fails_when_coordinates_missing(monkeypatch):
    monkeypatch.setattr(app_main, "resolve_coordinates", lambda **_kwargs: (None, None))

    user = AppUser(username="a", email="a@test.com", role="claimer")
    user.id = 7
    db = ScriptedSession(scalar_results=[None, user])
    payload = IntakeApproveRequest(
        username="a",
        email="a@test.com",
        item_type="lost",
        idempotency_key="new-key-1",
        extracted_fields=ExtractedItemFields(
            description="new item",
            address_text="Unknown place",
            event_time=datetime.now(timezone.utc),
        ),
    )

    with pytest.raises(HTTPException) as exc:
        app_main.approve_intake(payload, db)

    assert exc.value.status_code == 400
    assert "Unable to resolve coordinates" in str(exc.value.detail)


def test_approve_intake_creates_item_and_idempotency_record(monkeypatch):
    monkeypatch.setattr(app_main, "resolve_coordinates", lambda **_kwargs: (52.5, 13.4))
    monkeypatch.setattr(app_main, "calculate_matches_for_item", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(app_main, "get_text_embedding", lambda _text: [0.3, 0.4, 0.5])

    user = AppUser(username="a", email="a@test.com", role="claimer")
    user.id = 8
    db = ScriptedSession(scalar_results=[None, user])
    payload = IntakeApproveRequest(
        username="a",
        email="a@test.com",
        item_type="lost",
        idempotency_key="new-key-2",
        extracted_fields=ExtractedItemFields(
            description="new item",
            address_text="Berlin",
            event_time=datetime.now(timezone.utc),
        ),
    )

    result = app_main.approve_intake(payload, db)

    assert result.user_id == 8
    assert any(isinstance(obj, IntakeApprovalRecord) for obj in db.added)
    item = next(obj for obj in db.added if isinstance(obj, Item))
    assert item.description_embedding == [0.3, 0.4, 0.5]


def test_submit_match_returns_calculated_matches(monkeypatch):
    item = Item(user_id=1, item_type="lost", description="wallet")
    item.id = 9
    db = ScriptedSession(scalar_results=[item])
    expected = [
        MatchItem(found_item_id=2, lost_item_id=9, score=Decimal("0.71"), confidence="high")
    ]
    monkeypatch.setattr(app_main, "calculate_matches_for_item", lambda *_args, **_kwargs: expected)

    result = app_main.submit_match(MatchCreate(item_id=9), db)

    assert result.item_id == 9
    assert len(result.list_of_matches) == 1
    assert result.list_of_matches[0].found_item_id == 2


def test_submit_match_raises_for_missing_item():
    db = ScriptedSession(scalar_results=[None])
    with pytest.raises(HTTPException) as exc:
        app_main.submit_match(MatchCreate(item_id=999), db)
    assert exc.value.status_code == 404


def test_get_matches_returns_rows():
    match = ItemMatch(lost_item_id=1, found_item_id=2, score=Decimal("0.7"), confidence="medium")
    db = ScriptedSession(scalars_results=[[match]])
    result = app_main.get_matches(db)
    assert len(result) == 1

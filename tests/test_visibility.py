"""Task 4 Step 1：visible_to 谓词正反例。"""

import uuid

from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel, LibraryScope
from calliodesmo.interfaces.community_store import CommunityRecord
from calliodesmo.interfaces.vector_store import ChunkRecord
from calliodesmo.stores.visibility import visible_to


def _ctx(*, clearance=ClearanceLevel.INTERNAL, user=None, teams=(), projects=()) -> AccessContext:
    return AccessContext(
        user_id=user or uuid.uuid4(),
        username="u",
        clearance=clearance,
        team_ids=frozenset(teams),
        project_ids=frozenset(projects),
    )


def _record(
    scope=LibraryScope.PERSONAL, level=ClearanceLevel.INTERNAL, owner=None, project=None, team=None
):
    return ChunkRecord(
        chunk_id="c",
        doc_id="d",
        content="x",
        vector=[1.0],
        access_level=level,
        library_scope=scope,
        owner_id=owner,
        project_id=project,
        team_id=team,
    )


def test_clearance_ordered_comparison():
    owner = uuid.uuid4()
    rec = _record(level=ClearanceLevel.CONFIDENTIAL, owner=owner)
    assert visible_to(rec, _ctx(clearance=ClearanceLevel.SECRET, user=owner)) is True
    assert visible_to(rec, _ctx(clearance=ClearanceLevel.CONFIDENTIAL, user=owner)) is True
    assert visible_to(rec, _ctx(clearance=ClearanceLevel.INTERNAL, user=owner)) is False
    assert visible_to(rec, _ctx(clearance=ClearanceLevel.PUBLIC, user=owner)) is False


def test_personal_scope_owner_match():
    owner = uuid.uuid4()
    rec = _record(scope=LibraryScope.PERSONAL, owner=owner)
    assert visible_to(rec, _ctx(user=owner)) is True
    assert visible_to(rec, _ctx(user=uuid.uuid4())) is False


def test_project_scope_membership():
    pid = uuid.uuid4()
    rec = _record(scope=LibraryScope.PROJECT, project=pid)
    assert visible_to(rec, _ctx(projects=(pid,))) is True
    assert visible_to(rec, _ctx(projects=(uuid.uuid4(),))) is False


def test_team_scope_membership():
    tid = uuid.uuid4()
    rec = _record(scope=LibraryScope.TEAM, team=tid)
    assert visible_to(rec, _ctx(teams=(tid,))) is True
    assert visible_to(rec, _ctx(teams=(uuid.uuid4(),))) is False


def test_community_record_visible_to():
    owner = uuid.uuid4()
    rec = CommunityRecord(
        community_id="c",
        level=0,
        title="t",
        summary="s",
        access_level=ClearanceLevel.INTERNAL,
        library_scope=LibraryScope.PERSONAL,
        owner_id=owner,
    )
    assert visible_to(rec, _ctx(user=owner)) is True
    assert visible_to(rec, _ctx(user=uuid.uuid4())) is False

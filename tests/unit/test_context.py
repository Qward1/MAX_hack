from uuid import uuid4

import pytest

from domsignal.services.context import ScopeState, ScopeValue


def test_unknown_not_applicable_and_known_are_distinct_and_consistent() -> None:
    assert ScopeValue().state == ScopeState.UNKNOWN
    assert ScopeValue(ScopeState.NOT_APPLICABLE).value is None
    assert ScopeValue(ScopeState.KNOWN, uuid4()).value is not None
    with pytest.raises(ValueError):
        ScopeValue(ScopeState.KNOWN)
    with pytest.raises(ValueError):
        ScopeValue(ScopeState.UNKNOWN, uuid4())
    with pytest.raises(ValueError):
        ScopeValue(ScopeState.NOT_APPLICABLE, uuid4())

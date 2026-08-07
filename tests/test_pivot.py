import pytest
from core.pivot import Pivot

def test_pivot_creation():
    p = Pivot(
        index=10,
        price=65230.5,
        kind="HIGH"
    )

    assert p.index == 10
    assert p.price == 65230.5
    assert p.kind == "HIGH"
    assert p.strength == 0.0
    assert p.confirmed == False

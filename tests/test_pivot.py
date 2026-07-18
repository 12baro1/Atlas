from core.pivot import Pivot


def test_pivot_model_fields():
    pivot = Pivot(
        index=10,
        price=65230.5,
        kind="HIGH"
    )

    assert pivot.index == 10
    assert pivot.price == 65230.5
    assert pivot.kind == "HIGH"
    assert pivot.confirmed is False

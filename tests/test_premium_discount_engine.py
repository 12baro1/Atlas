import pytest

from premium_discount_engine import PremiumDiscountEngine


def test_premium_discount_accepts_numeric_exchange_values():
    engine = PremiumDiscountEngine()
    result = engine.calculate("110", "90", "105")
    assert result["valid"] is True
    assert result["premium"] is True
    assert result["discount"] is False
    assert result["equilibrium"] == pytest.approx(100)


def test_equilibrium_is_not_mislabeled_as_premium_or_discount():
    result = PremiumDiscountEngine().calculate(110, 90, 100)
    assert result["valid"] is False
    assert result["equilibrium_price"] is True
    assert result["premium"] is False
    assert result["discount"] is False


@pytest.mark.parametrize(
    "high,low,price",
    [
        (90, 110, 100),
        (110, 90, float("nan")),
        (110, 90, float("inf")),
        ("bad", 90, 100),
        (110, 90, 0),
    ],
)
def test_invalid_or_non_finite_premium_discount_inputs_fail_closed(high, low, price):
    result = PremiumDiscountEngine().calculate(high, low, price)
    assert result["valid"] is False
    assert result["premium"] is False
    assert result["discount"] is False
    assert result["equilibrium"] is None

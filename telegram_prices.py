"""Price levels shown in Telegram trade messages."""
import math


def format_price(value, *, grouping=True):
    """Format prices without hiding small-coin precision."""
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return str(value)
    if not math.isfinite(number):
        return "—"
    if number and abs(number) < 0.0000001:
        return str(number)
    rendered = f"{number:,.8f}" if grouping else f"{number:.8f}"
    rendered = rendered.rstrip("0").rstrip(".")
    if "." not in rendered:
        rendered += ".0"
    return rendered or "0"


def format_plan_levels(entry, stop, tp1, tp2, tp3, trailing_stop=None):
    prices = [format_price(value, grouping=False) for value in (entry, stop, tp1, tp2, tp3)]
    lines = [f"Giriş: {prices[0]} | Stop: {prices[1]}",
             f"TP1: {prices[2]} | TP2: {prices[3]} | TP3: {prices[4]}"]
    if trailing_stop is not None and trailing_stop != stop:
        lines.append(f"Güncel stop: {format_price(trailing_stop, grouping=False)}")
    return "\n".join(lines)


def tracked_levels(plan):
    return format_plan_levels(plan.get("entry"), plan.get("stop_loss"), plan.get("tp1"),
                              plan.get("tp2"), plan.get("tp3"), plan.get("trailing_stop"))


def confirmed_target_levels(plan):
    hits = set(plan.get("tps_hit") or ())
    return [level for level in (1, 2, 3) if level in hits or plan.get(f"hit_tp{level}")
            or plan.get("status") == f"TP{level}"]

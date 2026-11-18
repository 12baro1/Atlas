"""Tests for Telegram slash command definitions and BotFather integration."""

import os
from telegram_commands import (
    TELEGRAM_COMMANDS,
    TelegramCommand,
    get_botfather_commands,
    get_command_by_name,
    get_commands_by_category,
    get_all_categories,
    format_help_text,
)


def test_all_commands_have_required_fields():
    """Every command must have name, description, handler, category."""
    for cmd in TELEGRAM_COMMANDS:
        assert cmd.name, f"Missing name: {cmd}"
        assert cmd.description, f"Missing description: {cmd}"
        assert cmd.handler, f"Missing handler: {cmd}"
        assert cmd.category, f"Missing category: {cmd}"
        # Handler should be a valid method name (snake_case)
        assert cmd.handler.startswith("handle_"), f"Handler must start with 'handle_': {cmd.handler}"


def test_no_duplicate_command_names():
    """Command names must be unique (case-insensitive)."""
    names = [cmd.name.lower() for cmd in TELEGRAM_COMMANDS]
    assert len(names) == len(set(names)), "Duplicate command names found"


def test_command_categories_are_known():
    """All categories must be from the known set."""
    known = {"market", "scan", "setup", "performance", "system"}
    for cmd in TELEGRAM_COMMANDS:
        assert cmd.category in known, f"Unknown category: {cmd.category}"


def test_botfather_format():
    """BotFather commands must be valid format."""
    bf_commands = get_botfather_commands()
    assert isinstance(bf_commands, list)
    assert len(bf_commands) == len(TELEGRAM_COMMANDS)
    for item in bf_commands:
        assert "command" in item
        assert "description" in item
        # No leading slash
        assert not item["command"].startswith("/")
        # Description not empty
        assert item["description"]


def test_command_lookup():
    """get_command_by_name should find commands case-insensitively."""
    assert get_command_by_name("btc") is not None
    assert get_command_by_name("BTC") is not None
    assert get_command_by_name("Btc") is not None
    assert get_command_by_name("analiz") is not None
    assert get_command_by_name("ANALIZ") is not None
    assert get_command_by_name("nonexistent") is None


def test_parameterized_commands():
    """Commands that take parameters should be marked correctly."""
    param_commands = [cmd for cmd in TELEGRAM_COMMANDS if cmd.takes_parameter]
    param_names = {cmd.name for cmd in param_commands}
    # These should take parameters
    assert "analiz" in param_names
    assert "likidite" in param_names
    assert "tara" in param_names
    assert "setup" in param_names
    # These should NOT take parameters
    assert "btc" not in param_names
    assert "20tara" not in param_names
    assert "eniyi5" not in param_names
    assert "performans" not in param_names


def test_category_grouping():
    """get_commands_by_category should return correct commands."""
    market_cmds = get_commands_by_category("market")
    assert len(market_cmds) == 4  # btc, eth, sol, analiz
    assert {c.name for c in market_cmds} == {"btc", "eth", "sol", "analiz"}

    scan_cmds = get_commands_by_category("scan")
    assert len(scan_cmds) == 15

    setup_cmds = get_commands_by_category("setup")
    assert len(setup_cmds) == 6

    performance_cmds = get_commands_by_category("performance")
    assert len(performance_cmds) == 3  # performans, istatistik, ogrenme

    system_cmds = get_commands_by_category("system")
    assert len(system_cmds) == 6


def test_all_categories_ordered():
    """get_all_categories should return unique categories in declaration order."""
    cats = get_all_categories()
    assert cats == ["market", "scan", "setup", "performance", "system"]


def test_help_text_contains_all_commands():
    """format_help_text should include all commands."""
    help_text = format_help_text()
    for cmd in TELEGRAM_COMMANDS:
        assert f"/{cmd.name}" in help_text, f"Missing {cmd.name} in help text"
    assert "Atlas otomatik emir göndermez" in help_text
    assert "Sıralama puanı kazanma olasılığı değildir" in help_text


def test_command_count():
    """Verify expected total command count."""
    assert len(TELEGRAM_COMMANDS) == 34


def test_specific_commands_exist():
    """Verify all required commands from spec exist."""
    required = {
        "btc", "eth", "sol", "analiz",
        "tara", "20tara", "30tara", "50tara", "100tara", "200tara", "500tara", "1000tara",
        "tumtara", "eniyi5", "eniyi10",
        "taramadurum", "taramadurdur", "taramadevam", "yenile",
        "islemler", "likidite", "havuz", "havuzdurum", "setup", "gecmis",
        "performans", "istatistik", "ogrenme",
        "start", "durum", "motorlar", "veri", "sistem", "yardim",
    }
    actual = {cmd.name for cmd in TELEGRAM_COMMANDS}
    assert required == actual, f"Mismatch: missing={required-actual}, extra={actual-required}"


def test_botfather_commands_match_definitions():
    """BotFather command list should exactly match TELEGRAM_COMMANDS."""
    bf = get_botfather_commands()
    bf_names = {item["command"] for item in bf}
    def_names = {cmd.name for cmd in TELEGRAM_COMMANDS}
    assert bf_names == def_names


def test_botfather_no_leading_slash():
    """BotFather command names must not have leading slash."""
    for item in get_botfather_commands():
        assert not item["command"].startswith("/")


def test_handler_names_consistent():
    """Handler names should follow consistent pattern."""
    handlers = [cmd.handler for cmd in TELEGRAM_COMMANDS]
    # All should start with handle_
    assert all(h.startswith("handle_") for h in handlers)
    # Some handlers are shared (e.g., handle_analyze_symbol for btc, eth, sol, analiz)
    # This is intentional - they use the same handler with different parameters
    unique_handlers = set(handlers)
    assert len(unique_handlers) >= 10  # At least 10 unique handlers


if __name__ == "__main__":
    # Allow running directly
    import sys
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
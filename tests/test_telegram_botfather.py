"""Tests for Telegram BotFather command registration."""

from unittest.mock import patch, MagicMock

from telegram_botfather import (
    get_botfather_commands,
    verify_command_menu,
    register_bot_commands,
    get_current_commands,
    delete_bot_commands,
)
from telegram_commands import TELEGRAM_COMMANDS


def test_get_botfather_commands_format():
    """BotFather commands should have correct format."""
    commands = get_botfather_commands()
    assert isinstance(commands, list)
    assert len(commands) == len(TELEGRAM_COMMANDS)

    for item in commands:
        assert "command" in item
        assert "description" in item
        # No leading slash
        assert not item["command"].startswith("/")
        # Description not empty
        assert len(item["description"]) > 0
        # Command name matches definition
        assert item["command"] in [cmd.name for cmd in TELEGRAM_COMMANDS]


def test_botfather_commands_match_all_definitions():
    """Every command in TELEGRAM_COMMANDS should have a BotFather entry."""
    bf_commands = {item["command"] for item in get_botfather_commands()}
    def_commands = {cmd.name for cmd in TELEGRAM_COMMANDS}
    assert bf_commands == def_commands


def test_verify_command_menu_with_mock():
    """Test verify_command_menu with mocked API response."""
    from telegram_botfather import verify_command_menu

    # Mock get_current_commands to return matching commands
    with patch("telegram_botfather.get_current_commands") as mock_get:
        mock_get.return_value = [
            {"command": "btc", "description": "BTC analizi yap"},
            {"command": "eth", "description": "ETH analizi yap"},
        ]

        # This will fail because not all commands are present, but we can test the logic
        match, issues = verify_command_menu("fake_token")
        assert match is False
        assert len(issues) > 0
        assert any("Eksik" in issue for issue in issues)


def test_verify_command_menu_extra_commands():
    """Test detection of extra commands not in code."""
    with patch("telegram_botfather.get_current_commands") as mock_get:
        mock_get.return_value = [
            {"command": "btc", "description": "BTC analizi yap"},
            {"command": "eth", "description": "ETH analizi yap"},
            {"command": "extra_command", "description": "Not in code"},
        ]

        match, issues = verify_command_menu("fake_token")
        assert match is False
        assert any("Fazla" in issue for issue in issues)


def test_verify_command_menu_description_mismatch():
    """Test detection of description mismatches."""
    with patch("telegram_botfather.get_current_commands") as mock_get:
        mock_get.return_value = [
            {"command": "btc", "description": "Wrong description"},
            {"command": "eth", "description": "ETH analizi yap"},
        ]

        match, issues = verify_command_menu("fake_token")
        assert match is False
        assert any("Açıklama farklı" in issue for issue in issues)


def test_register_bot_commands_network_error():
    """Test register_bot_commands handles network errors gracefully."""
    with patch("telegram_botfather.requests.post") as mock_post:
        mock_post.side_effect = Exception("Network error")
        result = register_bot_commands("fake_token")
        assert result is False


def test_register_bot_commands_api_error():
    """Test register_bot_commands handles API errors."""
    with patch("telegram_botfather.requests.post") as mock_post:
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"ok": False, "description": "Bad Request"}
        mock_post.return_value = mock_response

        result = register_bot_commands("fake_token")
        assert result is False


def test_register_bot_commands_success():
    """Test successful command registration."""
    with patch("telegram_botfather.requests.post") as mock_post:
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"ok": True}
        mock_post.return_value = mock_response

        result = register_bot_commands("fake_token")
        assert result is True

        # Verify the call was made with correct payload
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert "json" in kwargs
        assert "commands" in kwargs["json"]
        assert len(kwargs["json"]["commands"]) == len(TELEGRAM_COMMANDS)


def test_get_current_commands_network_error():
    """Test get_current_commands handles network errors."""
    with patch("telegram_botfather.requests.get") as mock_get:
        mock_get.side_effect = Exception("Network error")
        result = get_current_commands("fake_token")
        assert result == []


def test_delete_bot_commands():
    """Test delete_bot_commands."""
    with patch("telegram_botfather.requests.post") as mock_post:
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"ok": True}
        mock_post.return_value = mock_response

        result = delete_bot_commands("fake_token")
        assert result is True


def test_auto_register_on_startup_disabled():
    """Test auto_register_on_startup respects disabled setting."""
    import os
    from telegram_botfather import auto_register_on_startup

    with patch.dict(os.environ, {"ATLAS_TELEGRAM_AUTO_REGISTER_COMMANDS": "0"}):
        # Should return True (no-op success) when disabled
        result = auto_register_on_startup()
        assert result is True


def test_auto_register_on_startup_no_token():
    """Test auto_register_on_startup with missing token."""
    import os
    from telegram_botfather import auto_register_on_startup

    with patch.dict(os.environ, {"ATLAS_TELEGRAM_BOT_TOKEN": ""}, clear=True):
        result = auto_register_on_startup()
        assert result is False


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
"""Telegram BotFather integration for command menu registration.

This module handles setting the bot's command menu via the Telegram
setMyCommands API, ensuring the menu matches the actual handlers.
"""

import logging
import os
import requests

from telegram_commands import get_botfather_commands

LOGGER = logging.getLogger("atlas.telegram.botfather")

TELEGRAM_API = "https://api.telegram.org"


def register_bot_commands(token: str) -> bool:
    """Register bot commands with Telegram BotFather via setMyCommands.

    Args:
        token: Bot token from BotFather

    Returns:
        True if successful, False otherwise
    """
    if not token:
        LOGGER.warning("Bot token missing; skipping BotFather command registration")
        return False

    commands = get_botfather_commands()
    url = f"{TELEGRAM_API}/bot{token}/setMyCommands"
    payload = {"commands": commands}

    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        result = response.json()
        if result.get("ok"):
            LOGGER.info("BotFather command menu registered: %d commands", len(commands))
            return True
        else:
            LOGGER.error("BotFather registration failed: %s", result.get("description"))
            return False
    except requests.RequestException as exc:
        LOGGER.error("BotFather registration network error: %s", exc)
        return False
    except Exception:
        LOGGER.exception("BotFather registration error")
        return False


def get_current_commands(token: str) -> list[dict]:
    """Get currently registered commands from Telegram."""
    if not token:
        return []
    url = f"{TELEGRAM_API}/bot{token}/getMyCommands"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        result = response.json()
        if result.get("ok"):
            return result.get("result", [])
        return []
    except Exception:
        LOGGER.exception("Failed to get current commands")
        return []


def delete_bot_commands(token: str) -> bool:
    """Delete all bot commands (useful for cleanup)."""
    if not token:
        return False
    url = f"{TELEGRAM_API}/bot{token}/deleteMyCommands"
    try:
        response = requests.post(url, json={}, timeout=10)
        response.raise_for_status()
        result = response.json()
        return result.get("ok", False)
    except Exception:
        LOGGER.exception("Failed to delete commands")
        return False


def verify_command_menu(token: str) -> tuple[bool, list[str]]:
    """Verify that registered commands match expected commands.

    Returns:
        (match, issues) - match is True if commands match, issues lists discrepancies
    """
    expected = {cmd["command"]: cmd["description"] for cmd in get_botfather_commands()}
    current = {cmd["command"]: cmd["description"] for cmd in get_current_commands(token)}

    issues = []

    # Check for missing commands
    for cmd, desc in expected.items():
        if cmd not in current:
            issues.append(f"Eksik: /{cmd} — {desc}")
        elif current[cmd] != desc:
            issues.append(f"Açıklama farklı: /{cmd} (beklenen: {desc}, mevcut: {current[cmd]})")

    # Check for extra commands
    for cmd in current:
        if cmd not in expected:
            issues.append(f"Fazla (kodda yok): /{cmd} — {current[cmd]}")

    return len(issues) == 0, issues


def sync_bot_commands(token: str, force: bool = False) -> bool:
    """Sync bot commands with code definitions.

    Args:
        token: Bot token
        force: If True, always update even if commands match

    Returns:
        True if sync successful
    """
    match, issues = verify_command_menu(token)
    if match and not force:
        LOGGER.info("BotFather command menu already in sync")
        return True

    if issues:
        LOGGER.info("BotFather command menu out of sync: %s", "; ".join(issues))

    return register_bot_commands(token)


def auto_register_on_startup() -> bool:
    """Auto-register commands on service startup if enabled.

    Reads ATLAS_TELEGRAM_BOT_TOKEN from environment.
    Controlled by ATLAS_TELEGRAM_AUTO_REGISTER_COMMANDS (default: true).
    """
    auto_register = os.getenv("ATLAS_TELEGRAM_AUTO_REGISTER_COMMANDS", "1").strip().lower() in {"1", "true", "yes", "on"}
    if not auto_register:
        LOGGER.info("Auto BotFather command registration disabled")
        return True

    token = os.getenv("ATLAS_TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        LOGGER.warning("ATLAS_TELEGRAM_BOT_TOKEN not set; skipping auto-registration")
        return False

    return sync_bot_commands(token)


if __name__ == "__main__":
    # CLI for manual testing
    import sys

    logging.basicConfig(level=logging.INFO)
    token = os.getenv("ATLAS_TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("ATLAS_TELEGRAM_BOT_TOKEN not set")
        sys.exit(1)

    if len(sys.argv) > 1 and sys.argv[1] == "verify":
        match, issues = verify_command_menu(token)
        print(f"Match: {match}")
        for issue in issues:
            print(f"  - {issue}")
        sys.exit(0 if match else 1)

    if len(sys.argv) > 1 and sys.argv[1] == "delete":
        if delete_bot_commands(token):
            print("Commands deleted")
        else:
            print("Failed to delete")
        sys.exit(0)

    success = sync_bot_commands(token, force=True)
    print(f"Registration: {'OK' if success else 'FAILED'}")
    sys.exit(0 if success else 1)
"""Whole-repository Python source parsing and live-label contract."""
from pathlib import Path
import ast
import re

ROOT = Path(__file__).resolve().parents[1]


def test_all_repository_python_sources_parse():
    """Parse every source line; catches syntax regressions in unimported modules."""
    ignored = {".git", ".venv", "venv", "node_modules", "build", "dist", "__pycache__"}
    files = sorted(
        path for path in ROOT.rglob("*.py")
        if not (set(path.relative_to(ROOT).parts) & ignored)
    )
    assert len(files) >= 300, "Repository source coverage unexpectedly shrank"
    for path in files:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_live_entrypoints_have_no_old_seven_generator_user_facing_labels():
    """Archived research docs are intentionally excluded from live UI checks."""
    entrypoints = [
        "telegram_command_service.py", "telegram_commands.py",
        "atlas_tui.py", "atlas_service.py", "engine.py",
        "utils/signal_card.py", "strategy_backtest.py",
    ]
    pattern = re.compile(
        r"seven[- ]strateg(?:y|ies)|7[- ]strateg(?:y|ies)|"
        r"7[- ]stratej(?:i|isi)|yedi stratej|SEVEN_STRATEGY_SELECTOR",
        flags=re.IGNORECASE,
    )
    stale = []
    for name in entrypoints:
        text = (ROOT / name).read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), 1):
            if pattern.search(line):
                stale.append(f"{name}:{line_no}: {line.strip()}")
    assert not stale, "\n".join(stale)

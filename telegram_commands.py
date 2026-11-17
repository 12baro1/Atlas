"""Telegram slash command definitions and BotFather integration.

This module defines all supported Telegram commands in a centralized way,
ensuring the command parser, handler registration, and BotFather menu
are always in sync.
"""

from dataclasses import dataclass
from typing import Callable, Optional


@dataclass(frozen=True)
class TelegramCommand:
    """Definition of a single Telegram slash command."""
    name: str                    # Command name without '/', e.g., "btc", "analiz"
    description: str             # Short description for BotFather menu
    handler: str                 # Handler method name in TelegramCommandService
    category: str                # Category for grouping: "market", "scan", "setup", "performance", "system"
    takes_parameter: bool = False  # Whether command accepts a parameter (e.g., "/analiz BTC")
    parameter_name: str = ""     # Name of parameter for help text (e.g., "symbol")


# All supported Telegram commands - single source of truth
TELEGRAM_COMMANDS = [
    # Piyasa analizi
    TelegramCommand("btc", "BTC analizi yap", "handle_analyze_symbol", "market"),
    TelegramCommand("eth", "ETH analizi yap", "handle_analyze_symbol", "market"),
    TelegramCommand("sol", "SOL analizi yap", "handle_analyze_symbol", "market"),
    TelegramCommand("analiz", "Belirtilen coin analizi (örn: /analiz BTC)", "handle_analyze_symbol", "market", True, "symbol"),

    # Piyasa tarama (gerçek scan queue üzerinden; kalıcı, devam edebilir)
    TelegramCommand("20tara", "20 piyasa tara", "handle_scan", "scan"),
    TelegramCommand("30tara", "30 piyasa tara", "handle_scan", "scan"),
    TelegramCommand("50tara", "50 piyasa tara", "handle_scan", "scan"),
    TelegramCommand("100tara", "100 piyasa tara", "handle_scan", "scan"),
    TelegramCommand("200tara", "200 piyasa tara", "handle_scan", "scan"),
    TelegramCommand("500tara", "500 piyasa tara", "handle_scan", "scan"),
    TelegramCommand("1000tara", "1000 piyasa tara", "handle_scan", "scan"),
    TelegramCommand("tumtara", "Tüm desteklenen USDT perpetual piyasaları tara", "handle_scan_all", "scan"),
    TelegramCommand("taramadurum", "Tarama durumu (kuyruk, ilerleme, checkpoint)", "handle_scan_status", "scan"),
    TelegramCommand("taramadurdur", "Arka plan taramasını durdur", "handle_scan_stop", "scan"),
    TelegramCommand("taramadevam", "Duraklatılmış taramayı kaldığı yerden sürdür", "handle_scan_resume", "scan"),
    TelegramCommand("yenile", "Gate.io piyasa envanterini yenile", "handle_refresh", "scan"),
    TelegramCommand("eniyi5", "Havuzdan en iyi 5 setup (salt okunur, yeni tarama başlatmaz)", "handle_best_five", "scan"),
    TelegramCommand("eniyi10", "Havuzdan en iyi 10 setup (salt okunur, yeni tarama başlatmaz)", "handle_best_ten", "scan"),
    TelegramCommand("havuzdurum", "Setup havuzu ve kuyruk durumu", "handle_pool_status", "setup"),

    # Setup ve takip
    TelegramCommand("mevcut", "Bugünün setup ve işlem takibi", "handle_mevcut", "setup"),
    TelegramCommand("setuplar", "Aktif setup havuzunu listele", "handle_setuplar", "setup"),
    TelegramCommand("takip", "Açık sinyal takibi", "handle_takip", "setup"),
    TelegramCommand("likidite", "Belirtilen coin için likidite haritası (örn: /likidite BTC)", "handle_liquidity", "setup", True, "symbol"),

    # Performans ve öğrenme
    TelegramCommand("performans", "Tüm geçmiş performans istatistikleri", "handle_performance", "performance"),
    TelegramCommand("istatistik", "Sinyal ve manuel işlem istatistikleri", "handle_statistics", "performance"),
    TelegramCommand("ogrenme", "Öğrenme motoru verisi", "handle_learning", "performance"),

    # Sistem ve yardım
    TelegramCommand("start", "Atlas komutlarını göster", "handle_start", "system"),
    TelegramCommand("durum", "Bot ve servis durumu (VPS, tarama, bağlantı)", "handle_status", "system"),
    TelegramCommand("sistem", "Sistem kaynakları ve çalışma durumu", "handle_system", "system"),
    TelegramCommand("yardim", "Komut listesi ve kullanım", "handle_help", "system"),
]


def get_botfather_commands() -> list[dict]:
    """Return command list formatted for Telegram BotFather setMyCommands API.

    BotFather format: [{"command": "name", "description": "desc"}, ...]
    Command names must NOT include '/'.
    """
    return [
        {"command": cmd.name, "description": cmd.description}
        for cmd in TELEGRAM_COMMANDS
    ]


def get_command_by_name(name: str) -> Optional[TelegramCommand]:
    """Look up command definition by name (without '/')."""
    name_lower = name.lower()
    for cmd in TELEGRAM_COMMANDS:
        if cmd.name.lower() == name_lower:
            return cmd
    return None


def get_commands_by_category(category: str) -> list[TelegramCommand]:
    """Get all commands in a specific category."""
    return [cmd for cmd in TELEGRAM_COMMANDS if cmd.category == category]


def get_all_categories() -> list[str]:
    """Get all unique categories in order."""
    seen = set()
    ordered = []
    for cmd in TELEGRAM_COMMANDS:
        if cmd.category not in seen:
            seen.add(cmd.category)
            ordered.append(cmd.category)
    return ordered


CATEGORY_LABELS = {
    "market": "📊 Piyasa Analizi",
    "scan": "🔍 Piyasa Tarama",
    "setup": "📈 Setup ve Takip",
    "performance": "📊 Performans ve Öğrenme",
    "system": "⚙️ Sistem ve Yardım",
}


def format_help_text() -> str:
    """Generate formatted help text grouped by category."""
    lines = ["ATLAS TELEGRAM KOMUTLARI", ""]
    for category in get_all_categories():
        lines.append(CATEGORY_LABELS.get(category, category.upper()))
        for cmd in get_commands_by_category(category):
            if cmd.takes_parameter:
                lines.append(f"  /{cmd.name} <{cmd.parameter_name}> — {cmd.description}")
            else:
                lines.append(f"  /{cmd.name} — {cmd.description}")
        lines.append("")
    lines.extend([
        "Atlas otomatik emir göndermez.",
        "Sıralama puanı kazanma olasılığı değildir.",
        "Komutlar büyük/küçük harf duyarsızdır.",
        "Bot username eklenmiş biçim de çalışır: /btc@BotAdi",
    ])
    return "\n".join(lines)
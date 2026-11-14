"""Configurable sector peer universe shared by live analysis and replay."""
from __future__ import annotations

import json
import os


def configured_sector_peers(symbol, max_peers=6):
    """Read user-configured liquid peers from ATLAS_SECTOR_PEERS_JSON.

    Example: {"SOL":["AVAX/USDT:USDT","ADA/USDT:USDT"]}.
    Unknown assets intentionally receive no invented sector classification.
    """
    base = str(symbol or "").split("/", 1)[0].split(":", 1)[0].upper()
    raw = os.getenv("ATLAS_SECTOR_PEERS_JSON", "").strip()
    if not raw:
        return []
    try:
        mapping = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(mapping, dict):
        return []
    peers = mapping.get(base) or []
    if not isinstance(peers, list):
        return []
    output = []
    seen = {str(symbol).upper()}
    for item in peers:
        peer = str(item or "").strip()
        if not peer or "/" not in peer or peer.upper() in seen:
            continue
        seen.add(peer.upper())
        output.append(peer)
        if len(output) >= max(1, int(max_peers)):
            break
    return output

"""Canonical setup-feature schema shared by SetupQualityEngine, LearningEngine and journal.

tek kanonik isimle aynı özelliği iki farklı adla temsil etmeyi önler.

Özellik (feature) isimleri SetupQualityEngine modül anahtarlarıyla hizalıdır,
böylece geçmiş manuel işlem öğrenmesi yeni setup'ın aynı modüllerine
birebir bağlanabilir (exact bucket eşleşmesi).
"""

# SetupQualityEngine.module_scores anahtarlarıyla hizalı kanonik modül adları.
CANONICAL_MODULES = {
    "market_structure",
    "liquidity_sweep",
    "order_block",
    "fvg",
    "premium_discount",
    "mtf_alignment",
    "momentum_volatility",
    "manipulation_filter",
    "session",
    "entry_quality",
    "external_confluence",
}

# Eski/üçüncü parti kayıtlarda geçebilecek kısaltma/alias -> kanonik isim.
_FEATURE_ALIASES = {
    "ms": "market_structure",
    "market_structure": "market_structure",
    "structure": "market_structure",
    "ls": "liquidity_sweep",
    "sweep": "liquidity_sweep",
    "liquidity": "liquidity_sweep",
    "ob": "order_block",
    "order_block": "order_block",
    "orderblock": "order_block",
    "block": "order_block",
    "fvg": "fvg",
    "pd": "premium_discount",
    "premium_discount": "premium_discount",
    "premium": "premium_discount",
    "discount": "premium_discount",
    "mtf": "mtf_alignment",
    "mtf_alignment": "mtf_alignment",
    "htf": "mtf_alignment",
    "momentum": "momentum_volatility",
    "momentum_volatility": "momentum_volatility",
    "volatility": "momentum_volatility",
    "manipulation": "manipulation_filter",
    "manipulation_filter": "manipulation_filter",
    "session": "session",
    "killzone": "session",
    "kill_zone": "session",
    "entry": "entry_quality",
    "entry_quality": "entry_quality",
    "confirmation": "entry_quality",
    "external": "external_confluence",
    "external_confluence": "external_confluence",
    "confluence": "external_confluence",
}

# Learning kolonlarında / bucket key bölümlerinde ayrıca hesaba katılan
# bağlam anahtarları (setup.nın kendisi değil; grouping alanları).
CONTEXT_FIELDS = ("regime", "timeframe", "direction")


def canonical_feature(token):
    """Tek bir token'ı kanonik özellik adına eşleştirir."""
    if not token:
        return None
    key = str(token).strip().lower().replace(" ", "-")
    # Direkt kanonik ya da alias araması.
    if key in CANONICAL_MODULES:
        return key
    if key in _FEATURE_ALIASES:
        return _FEATURE_ALIASES[key]
    return key


def normalize_features(features):
    """Liste/iterable -> sıralı kanonik feature adları (regime eski değerlere korur)."""
    out = set()
    for item in features or []:
        name = canonical_feature(item)
        if name:
            out.add(name)
    return sorted(out)


def feature_delimiters():
    return "|", "+", "/", ",", ":"


def parse_fingerprint(token):
    """setup_fingerprint metnini kanonik feature set'ine çevirir."""
    if not token:
        return []
    text = str(token)
    for delim in feature_delimiters():
        text = text.replace(delim, "|")
    return normalize_features(text.split("|"))


def build_fingerprint(features):
    """Kanonik feature set'inden canonical fingerprint metni üretir."""
    parts = normalize_features(features)
    return "|".join(parts) if parts else "UNKNOWN"


def fingerprint_features(payload):
    """'setup_fingerprint' ya da 'features' alanından kanonik küme çıkarır."""
    if isinstance(payload, dict):
        fpr = payload.get("setup_fingerprint")
        if isinstance(fpr, str):
            return set(parse_fingerprint(fpr))
        feats = payload.get("features")
        if feats:
            return set(normalize_features(feats))
    return set()
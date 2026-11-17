import logging
import threading

from atlas_runtime import AtlasRuntime


class FakeManualService:
    def __init__(self, resolved=None, error=None):
        self.resolved = resolved
        self.error = error
        self.calls = []

    def resolve_signal_id(self, *, symbol=None, direction=None, signal_id=None):
        self.calls.append({
            "symbol": symbol,
            "direction": direction,
            "signal_id": signal_id,
        })
        if self.error:
            raise self.error
        return signal_id or self.resolved


def make_runtime(service):
    runtime = AtlasRuntime.__new__(AtlasRuntime)
    runtime.manual_service = service
    runtime._journal_lock = threading.RLock()
    runtime.logger = logging.getLogger("tests.atlas_runtime")
    return runtime


def test_resolve_signal_id_prefers_id_attached_to_result():
    service = FakeManualService(resolved="fallback-id")
    runtime = make_runtime(service)

    assert runtime._resolve_signal_id({
        "signal_id": "explicit-id",
        "symbol": "BTC/USDT:USDT",
        "signal": {"signal": "LONG"},
    }) == "explicit-id"
    assert service.calls == []


def test_resolve_signal_id_reads_journal_id():
    service = FakeManualService()
    runtime = make_runtime(service)

    assert runtime._resolve_signal_id({
        "journal": {"signal_id": "journal-id"},
        "signal": {"signal": "SHORT"},
    }) == "journal-id"
    assert service.calls == []


def test_resolve_signal_id_uses_shared_manual_service_for_actionable_signal():
    service = FakeManualService(resolved="outcome-123")
    runtime = make_runtime(service)

    assert runtime._resolve_signal_id({
        "symbol": "BTC/USDT:USDT",
        "signal": {"signal": "LONG"},
    }) == "outcome-123"
    assert service.calls == [{
        "symbol": "BTC/USDT:USDT",
        "direction": "LONG",
        "signal_id": None,
    }]


def test_resolve_signal_id_does_not_resolve_wait_or_missing_symbol():
    service = FakeManualService(resolved="must-not-match")
    runtime = make_runtime(service)

    assert runtime._resolve_signal_id({
        "symbol": "BTC/USDT:USDT",
        "signal": {"signal": "WAIT"},
    }) is None
    assert runtime._resolve_signal_id({
        "signal": {"signal": "SHORT"},
    }) is None
    assert service.calls == []


def test_resolve_signal_id_service_error_does_not_break_analysis_registration():
    service = FakeManualService(error=RuntimeError("journal unavailable"))
    runtime = make_runtime(service)

    assert runtime._resolve_signal_id({
        "symbol": "BTC/USDT:USDT",
        "signal": {"signal": "SHORT"},
    }) is None
    assert len(service.calls) == 1

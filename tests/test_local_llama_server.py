from pathlib import Path

from ai.local_llama_server import LocalLlamaServerManager


class _AutoConfig:
    AI_LOCAL_CONTEXT = 0
    AI_LOCAL_THREADS = 0
    AI_LOCAL_THREADS_BATCH = 0
    AI_LOCAL_BATCH_SIZE = 0
    AI_LOCAL_UBATCH_SIZE = 0
    AI_LOCAL_PARALLEL_SLOTS = 0


def test_mobile_auto_tuning_profile(monkeypatch):
    manager = LocalLlamaServerManager(repo_root=Path(__file__).resolve().parent.parent, config=_AutoConfig)

    monkeypatch.setattr("ai.local_llama_server.os.cpu_count", lambda: 8)
    monkeypatch.setattr(manager, "_system_memory_mib", lambda: 7534)

    assert manager._resolved_context() == 2048
    assert manager._resolved_threads() == 6
    assert manager._resolved_threads_batch() == 8
    assert manager._resolved_batch_size() == 256
    assert manager._resolved_ubatch_size(batch_size=256) == 64
    assert manager._resolved_parallel_slots() == 1

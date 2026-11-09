from core.plugin_manager import PluginManager


class _Plugin:
    def __init__(self, name, *, valid=True, transform=None):
        self.name = name
        self.valid = valid
        self.transform = transform
        self.calls = 0

    def validate(self, state):
        return self.valid

    def run(self, state):
        self.calls += 1
        if self.transform:
            return self.transform(state)
        state.setdefault("ran", []).append(self.name)
        return state


def test_plugin_manager_skips_invalid_plugins_and_preserves_mutated_state():
    manager = PluginManager()
    enabled = _Plugin("enabled")
    disabled = _Plugin("disabled", valid=False)
    assert manager.register(enabled) is True
    assert manager.register(disabled) is True
    assert manager.register(enabled) is False

    state = manager.run({})
    assert state == {"ran": ["enabled"]}
    assert enabled.calls == 1
    assert disabled.calls == 0


def test_plugin_manager_uses_returned_state_from_plugin():
    manager = PluginManager()
    manager.register(_Plugin("replace", transform=lambda state: {"replaced": True}))
    manager.register(_Plugin("mutate"))
    result = manager.run({})
    assert result == {"replaced": True, "ran": ["mutate"]}


def test_plugin_manager_unregister_reports_result_and_snapshot_isolated():
    manager = PluginManager()
    plugin = _Plugin("one")
    manager.register(plugin)
    snapshot = manager.plugins()
    snapshot.clear()

    assert len(manager.plugins()) == 1
    assert manager.unregister(plugin) is True
    assert manager.unregister(plugin) is False

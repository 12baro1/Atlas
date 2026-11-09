"""Small, deterministic plugin lifecycle manager for legacy plugin adapters."""


class PluginManager:
    def __init__(self):
        self._plugins = []

    def register(self, plugin):
        if plugin is None:
            raise TypeError("plugin cannot be None")
        if plugin in self._plugins:
            return False
        self._plugins.append(plugin)
        return True

    def unregister(self, plugin):
        if plugin in self._plugins:
            self._plugins.remove(plugin)
            return True
        return False

    def clear(self):
        self._plugins.clear()

    def plugins(self):
        return list(self._plugins)

    def run(self, state):
        """Run only validated plugins; support both in-place and returned state."""
        current_state = state
        for plugin in tuple(self._plugins):
            validator = getattr(plugin, "validate", None)
            if callable(validator) and not validator(current_state):
                continue
            result = plugin.run(current_state)
            if result is not None:
                current_state = result
        return current_state

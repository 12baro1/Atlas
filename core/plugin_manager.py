"""
core/plugin_manager.py
Atlas Plugin Manager v1
"""

class PluginManager:
    def __init__(self):
        self._plugins = []

    def register(self, plugin):
        self._plugins.append(plugin)

    def unregister(self, plugin):
        if plugin in self._plugins:
            self._plugins.remove(plugin)

    def clear(self):
        self._plugins.clear()

    def plugins(self):
        return list(self._plugins)

    def run(self, state):
        for plugin in self._plugins:
            plugin.run(state)
        return state

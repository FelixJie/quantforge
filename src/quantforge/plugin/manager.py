"""Plugin manager — discovers, loads, and dispatches hooks to plugins."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from quantforge.plugin.hooks import HookContext

if TYPE_CHECKING:
    from quantforge.plugin.base import BasePlugin


class PluginManager:
    """Manages plugin lifecycle and hook dispatch.

    Usage:
        mgr = PluginManager()
        mgr.register_directory("plugins/")          # auto-discover
        mgr.register(MyPlugin())                     # manual register

        # Then in backtest engine:
        await mgr.fire("on_backtest_start", strategy_name="DualMA", ...)
    """

    def __init__(self):
        self._plugins: dict[str, BasePlugin] = {}

    # ── Registration ─────────────────────────────────────────────────

    async def register(self, plugin: BasePlugin) -> None:
        """Manually register a plugin instance."""
        if plugin.name in self._plugins:
            logger.warning(f"Plugin {plugin.name!r} already registered, skipping.")
            return
        ctx = HookContext(plugin_name=plugin.name, hook_name="on_load")
        await plugin.on_load(ctx)
        self._plugins[plugin.name] = plugin
        logger.info(f"Plugin loaded: {plugin.name} v{plugin.version} — {plugin.description}")

    async def register_directory(self, directory: str | Path) -> int:
        """Scan a directory for plugin modules and auto-register them.

        Each .py file in the directory is imported.  If it exposes a
        module-level ``plugin`` attribute (BasePlugin instance), that
        plugin is registered.

        Returns the number of plugins loaded.
        """
        directory = Path(directory)
        if not directory.exists():
            logger.debug(f"Plugin directory {directory} does not exist — skipping.")
            return 0

        count = 0
        for py_file in sorted(directory.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            try:
                spec = importlib.util.spec_from_file_location(
                    f"_plugin_{py_file.stem}", py_file
                )
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                plugin_obj = getattr(mod, "plugin", None)
                if plugin_obj is not None:
                    await self.register(plugin_obj)
                    count += 1
            except Exception as e:
                logger.warning(f"Failed to load plugin from {py_file}: {e}")

        return count

    async def unload(self, plugin_name: str) -> None:
        """Unload a named plugin."""
        plugin = self._plugins.pop(plugin_name, None)
        if plugin:
            ctx = HookContext(plugin_name=plugin_name, hook_name="on_unload")
            await plugin.on_unload(ctx)
            logger.info(f"Plugin unloaded: {plugin_name}")

    # ── Hook dispatch ─────────────────────────────────────────────────

    async def fire(self, hook_name: str, **ctx_kwargs) -> None:
        """Call the named hook on every registered plugin.

        Extra keyword arguments are forwarded as HookContext fields.
        """
        for name, plugin in list(self._plugins.items()):
            hook = getattr(plugin, hook_name, None)
            if hook is None:
                continue
            ctx = HookContext(plugin_name=name, hook_name=hook_name, **ctx_kwargs)
            try:
                await hook(ctx)
            except Exception as e:
                logger.warning(f"Plugin {name!r} raised in {hook_name}: {e}")

    # ── Introspection ─────────────────────────────────────────────────

    def list_plugins(self) -> list[dict]:
        return [
            {"name": p.name, "version": p.version, "description": p.description}
            for p in self._plugins.values()
        ]

    def __len__(self) -> int:
        return len(self._plugins)


# Module-level singleton (used by BacktestEngine and API)
_default_manager: PluginManager | None = None


def get_plugin_manager() -> PluginManager:
    global _default_manager
    if _default_manager is None:
        _default_manager = PluginManager()
    return _default_manager

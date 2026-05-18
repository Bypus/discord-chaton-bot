import asyncio
import importlib
import sys
from pathlib import Path

from discord.ext import commands


class HotReloadCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._watch_task: asyncio.Task | None = None
        self._support_extension_dependencies: dict[str, set[str]] = {
            "cogs.twitter_handler": {"cogs.message_handlers"},
        }

    async def cog_load(self):
        self._watch_task = asyncio.create_task(self._watch_and_reload())

    async def cog_unload(self):
        if self._watch_task is not None:
            self._watch_task.cancel()
            try:
                await self._watch_task
            except asyncio.CancelledError:
                pass

    async def _watch_and_reload(self):
        try:
            from watchfiles import awatch, PythonFilter
        except ImportError:
            print("[hot-reload] watchfiles not installed; hot reload disabled.")
            return

        cogs_dir = Path(__file__).resolve().parent
        project_root = cogs_dir.parent
        print("[hot-reload] Watching cogs directory for changes...")

        async for changes in awatch(str(cogs_dir), watch_filter=PythonFilter()):
            support_modules = self._changed_support_modules(changes, project_root)
            self._reload_modules(support_modules)
            extensions = self._changed_extensions(changes, project_root)
            extensions.update(self._dependent_extensions_for_support_modules(support_modules))
            for extension in sorted(extensions):
                await self._reload_extension(extension)

    def _dependent_extensions_for_support_modules(self, modules: set[str]) -> set[str]:
        dependent_extensions: set[str] = set()
        for module_name in modules:
            for extension in self._support_extension_dependencies.get(module_name, set()):
                if extension in self.bot.extensions:
                    dependent_extensions.add(extension)
        return dependent_extensions

    def _changed_support_modules(self, changes, project_root: Path) -> set[str]:
        modules: set[str] = set()

        for _change, changed_path in changes:
            path_obj = Path(changed_path)
            if path_obj.suffix != ".py":
                continue

            try:
                rel_parts = path_obj.resolve().relative_to(project_root.resolve()).with_suffix("").parts
            except Exception:
                continue

            if not rel_parts or rel_parts[0] != "cogs":
                continue
            if rel_parts[-1] == "__init__":
                continue

            module_name = ".".join(rel_parts)
            if module_name in {"cogs.hot_reload"}:
                continue

            if module_name not in self.bot.extensions:
                modules.add(module_name)

        return modules

    @staticmethod
    def _reload_modules(modules: set[str]):
        for module_name in sorted(modules):
            module = sys.modules.get(module_name)
            if module is None:
                continue
            try:
                importlib.reload(module)
                print(f"[hot-reload] Reloaded module {module_name}")
            except Exception as error:
                print(f"[hot-reload] Failed to reload module {module_name}: {error}")

    def _changed_extensions(self, changes, project_root: Path) -> set[str]:
        extensions: set[str] = set()

        for _change, changed_path in changes:
            path_obj = Path(changed_path)
            if path_obj.suffix != ".py":
                continue

            try:
                rel_parts = path_obj.resolve().relative_to(project_root.resolve()).with_suffix("").parts
            except Exception:
                continue

            if not rel_parts or rel_parts[0] != "cogs":
                continue
            if rel_parts[-1] == "__init__":
                continue

            module_name = ".".join(rel_parts)
            if module_name == "cogs.hot_reload":
                continue

            if module_name in self.bot.extensions:
                extensions.add(module_name)

        return extensions

    async def _reload_extension(self, extension: str):
        try:
            if extension in self.bot.extensions:
                await self.bot.reload_extension(extension)
                print(f"[hot-reload] Reloaded {extension}")
            else:
                await self.bot.load_extension(extension)
                print(f"[hot-reload] Loaded {extension}")

            if extension == "cogs.slash_commands":
                synced = await self.bot.tree.sync()
                print(f"[hot-reload] Slash commands synced: {len(synced)}")
        except Exception as error:
            print(f"[hot-reload] Failed to reload {extension}: {error}")


async def setup(bot: commands.Bot):
    await bot.add_cog(HotReloadCog(bot))
from __future__ import annotations

import importlib
import pkgutil
import sys
import os
from pathlib import Path
from typing import Dict, Any


def _fallback_load_with_future_annotations(plugins_dir: Path, mod_name: str):
    try:
        file = plugins_dir / f"{mod_name}.py"
        pkg_init = plugins_dir / mod_name / "__init__.py"
        src_path = None
        is_pkg = False
        if file.exists():
            src_path = file
        elif pkg_init.exists():
            src_path = pkg_init
            is_pkg = True
        else:
            print(f"[startup] Direct load failed: {mod_name}: source not found")
            return None

        import types, __future__
        code_text = src_path.read_text(encoding="utf-8")
        flags = __future__.annotations.compiler_flag
        code_obj = compile(code_text, str(src_path), "exec", flags=flags, dont_inherit=True)
        module = types.ModuleType(mod_name)
        module.__file__ = str(src_path)
        module.__package__ = mod_name if is_pkg else ""
        if is_pkg:
            module.__path__ = [str(src_path.parent)]  # type: ignore[attr-defined]
        sys.modules[mod_name] = module
        exec(code_obj, module.__dict__)
        print(f"[startup] Fallback loaded with future-annotations: {src_path.name}")
        return module
    except Exception as e2:
        print(f"[startup] Direct load failed: {mod_name}: {e2}")
        return None


def load_gpio_plugins(base_ref: Path | None = None) -> Dict[str, Any]:
    """Load GPIO sensor plugins from the project-level plugins directories.

    If SENSOR_PLUGINS_DIR env var is set, that directory is searched first.
    """
    plugins: Dict[str, Any] = {}
    try:
        # Derive project root: if base_ref provided, go up until plugins folder found
        if base_ref is None:
            base_ref = Path(__file__).resolve().parent.parent  # sensorapp/.. (project root)
        env_dir = os.environ.get("SENSOR_PLUGINS_DIR")
        candidate_dirs = []
        if env_dir:
            candidate_dirs.append(Path(env_dir))
        candidate_dirs.extend([base_ref / "plugins", base_ref / "Plugins"])
        print("[startup] Searching plugins in:")
        for d in candidate_dirs:
            print(f"  - {d} {'(exists)' if d.exists() else '(missing)'}")
        for plugins_dir in candidate_dirs:
            if not plugins_dir.exists():
                continue
            if str(plugins_dir) not in sys.path:
                sys.path.insert(0, str(plugins_dir))
            for m_info in pkgutil.iter_modules([str(plugins_dir)]):
                mod_name = m_info.name
                if mod_name in {"__init__", "base"}:
                    continue
                print(f"[startup] Loading module '{mod_name}'...")
                module = None
                try:
                    module = importlib.import_module(mod_name)
                except Exception as e:
                    print(f"[startup] Import failed: {mod_name}: {e}")
                    module = _fallback_load_with_future_annotations(plugins_dir, mod_name)
                if module is None:
                    continue
                get_plugin = getattr(module, "get_plugin", None)
                if not callable(get_plugin):
                    continue
                try:
                    instance = get_plugin()
                    name = getattr(instance, "name", None)
                    if not name:
                        continue
                    plugins[name] = instance
                    print(f"[startup] Plugin registered: {name}")
                    print(f"[startup]  → Auto-Detection: {'enabled' if getattr(instance, 'auto_detectable', False) else 'disabled'}")
                except Exception:
                    continue
    except Exception:
        pass
    return plugins


def build_plugin_options(plugins: Dict[str, Any]):
    """Build selection options including role-specific entries for multi-pin plugins.

    Example: TM1637 with pin_roles=["CLK","DIO"] becomes options
    ("TM1637:CLK","TM1637:CLK") and ("TM1637:DIO","TM1637:DIO").
    """
    opts = []
    try:
        for name in sorted(plugins.keys()):
            plugin = plugins.get(name)
            roles = getattr(plugin, "pin_roles", None)
            if isinstance(roles, (list, tuple)) and roles:
                for role in roles:
                    label = f"{name}:{role}"
                    opts.append((label, label))
            else:
                opts.append((name, name))
    except Exception:
        pass
    opts.append(("I2C Device", "I2C"))
    return opts

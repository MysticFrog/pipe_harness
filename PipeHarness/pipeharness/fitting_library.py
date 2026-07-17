"""Loads the data-driven fitting standard/size library from data/fitting_standards.json.

Adding a new standard or size means editing that JSON file, not this module.
"""
import json
import os

_DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "fitting_standards.json")
_DASH_SIZE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "dash_sizes.json")

_cache = None
_dash_cache = None


def _load():
    global _cache
    if _cache is None:
        with open(_DATA_PATH, "r") as f:
            _cache = json.load(f)
    return _cache


def _load_dash_sizes():
    global _dash_cache
    if _dash_cache is None:
        with open(_DASH_SIZE_PATH, "r") as f:
            data = json.load(f)
        _dash_cache = {k: v for k, v in data.items() if not k.startswith("_")}
    return _dash_cache


def dash_sizes():
    """Ordered list of dash size codes, e.g. ['-4', '-6', ..., '-32']."""
    return list(_load_dash_sizes().keys())


def dash_size_od_mm(size):
    """Approximate hose outer diameter (mm) for a given dash size code."""
    sizes = _load_dash_sizes()
    return sizes.get(size, next(iter(sizes.values())))


def standard_codes():
    """Ordered list of standard codes, e.g. ['JIC', 'BSP', 'ORFS', 'UNSET']."""
    return list(_load().keys())


def standard_label(code):
    return _load().get(code, {}).get("label", code)


def sizes_for(code):
    """Sizes available for a given standard code."""
    return list(_load().get(code, {}).get("sizes", ["(unset)"]))


def reload():
    """Force re-read of the JSON files (useful after editing them during a FreeCAD session)."""
    global _cache, _dash_cache
    _cache = None
    _dash_cache = None
    _load()
    return _load_dash_sizes()

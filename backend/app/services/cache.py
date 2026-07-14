import hashlib
import logging
from collections import OrderedDict
from typing import Dict, Optional, Any

logger = logging.getLogger(__name__)

# Bounded LRU (was an unbounded module dict). In-process only — documented as such;
# a multi-worker deployment would move this to Redis. Stores source-of-truth only
# ({ir, plantuml_code}); the SVG is re-rendered on demand, never cached.
_MAX_ENTRIES = 256
_cache: "OrderedDict[str, dict]" = OrderedDict()


def _key(prompt_context: str, diagram_type: str) -> str:
    return hashlib.sha256(f"{prompt_context.strip()}:{diagram_type.strip()}".encode("utf-8")).hexdigest()


def get_cached_diagram(prompt_context: str, diagram_type: str) -> Optional[Dict[str, Any]]:
    key = _key(prompt_context, diagram_type)
    if key in _cache:
        _cache.move_to_end(key)  # mark most-recently-used
        logger.info("Cache hit for diagram type '%s'.", diagram_type)
        return _cache[key]
    logger.info("Cache miss for diagram type '%s'.", diagram_type)
    return None


def set_cached_diagram(prompt_context: str, diagram_type: str, result: Dict[str, Any]) -> None:
    # Never cache a failed/fallback result — otherwise a transient outage would be served forever.
    if result.get("_fallback") or (result.get("ir") or {}).get("_fallback"):
        return
    key = _key(prompt_context, diagram_type)
    _cache[key] = result
    _cache.move_to_end(key)
    while len(_cache) > _MAX_ENTRIES:
        evicted, _ = _cache.popitem(last=False)
        logger.debug("Cache evicted LRU entry %s", evicted[:8])
    logger.info("Cached diagram results for type '%s'.", diagram_type)

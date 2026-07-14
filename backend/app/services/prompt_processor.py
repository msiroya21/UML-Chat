from typing import List


def build_context(prompts: List[str]) -> str:
    """
    Build the full-history generation context from a session's ordered prompts (oldest
    first, the last item being the current turn). This replaces the old one-level bundle,
    so the original requirements are never dropped after multiple updates.
    """
    cleaned = [p.strip() for p in prompts if p and p.strip()]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]

    parts = [f"Original requirements:\n{cleaned[0]}"]
    for i, p in enumerate(cleaned[1:-1], start=1):
        parts.append(f"Update {i}:\n{p}")
    parts.append(f"Latest update (apply this to the design so far):\n{cleaned[-1]}")
    return "\n\n---\n\n".join(parts)

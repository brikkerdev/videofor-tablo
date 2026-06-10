from .state import Indicator


def render_text(indicators: list[Indicator], values: dict[str, int]) -> str:
    """Текст для табло. Формат уточняется после спецификации API табло."""
    if not indicators:
        return ""
    width = max(len(ind.display_name) for ind in indicators) + 1
    return "\n".join(
        f"{(ind.display_name + ':').ljust(width)} {values.get(ind.key, 0)}"
        for ind in indicators
    )

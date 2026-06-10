from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    event_type: str
    checkpoint: str | None
    indicator_key: str
    op: str


def match_rules(rules: list[Rule], event_type: str, checkpoint: str | None) -> list[Rule]:
    return [
        r
        for r in rules
        if r.event_type == event_type
        and (r.checkpoint is None or r.checkpoint == checkpoint)
    ]


def apply_op(op: str, current: int, value: int) -> int:
    if op == "inc":
        return current + value
    if op == "dec":
        return max(0, current - value)
    if op == "set":
        return max(0, value)
    raise ValueError(f"Unknown op: {op}")

"""Selection within the parsed sequence; navigation has no terminal effects."""

from bisect import bisect_left, bisect_right

from .engine import Step


class Cursor:
    def __init__(self, steps: list[Step]) -> None:
        self.steps = steps
        self.stops = [i for i, step in enumerate(steps) if step.kind != "run"]
        self.index = 0
        self.finished = False

    @property
    def item(self) -> int:
        return bisect_right(self.stops, self.index) - 1

    def navigate(self, direction: str) -> None:
        if direction == "back":
            position = max(0, bisect_left(self.stops, self.index) - 1)
        else:
            position = min(len(self.stops) - 1, bisect_right(self.stops, self.index))
        target = self.stops[position]
        if target != self.index:
            self.index = target
            self.finished = False

    def advanced(self) -> None:
        if self.steps[self.index].kind == "end":
            self.finished = True
        else:
            self.index += 1

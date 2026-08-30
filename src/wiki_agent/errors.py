from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class WikiAgentError(Exception):
    code: str
    message: str
    details: dict[str, Any] | None = None

    def __str__(self) -> str:
        return self.message

    def payload(self) -> dict[str, Any]:
        result: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            result.update(self.details)
        return result

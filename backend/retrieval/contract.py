"""The vocabulary retrieval speaks to its callers.

Everything that crosses the package boundary lives here: what goes in
(`HistoryMessage`), and what comes back when the pipeline stops early (`Refusal`).
Callers import this module and nothing deeper — the stage packages are internal.
Purely declarative: no I/O.
"""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel


class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True)
class Refusal:
    """The pipeline stopped before retrieving anything; `text` is what streams instead."""

    text: str

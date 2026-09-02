"""LLM utilities with lazy imports so cached demo output needs no provider SDK."""

from typing import Any

__all__ = ["generate_finance_report"]


def __getattr__(name: str) -> Any:
    if name == "generate_finance_report":
        from .report_generator import generate_finance_report

        return generate_finance_report
    raise AttributeError(name)

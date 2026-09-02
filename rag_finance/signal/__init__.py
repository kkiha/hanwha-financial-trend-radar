"""Signal input contracts for the trend radar."""

from .loader import load_signal
from .schema import Evidence, Signal

__all__ = ["Evidence", "Signal", "load_signal"]

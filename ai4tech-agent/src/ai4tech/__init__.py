"""AI4Tech Intelligence Agent.

A standing pipeline that turns external content (podcasts first) into a themed,
role-relevant briefing with grounded recommended actions. See the PRD and
README for the architecture; ``pipeline.Pipeline`` is the entry point.
"""

from __future__ import annotations

__version__ = "0.1.0"

from .config import AppConfig, load_config
from .pipeline import Pipeline, RunResult

__all__ = ["AppConfig", "load_config", "Pipeline", "RunResult", "__version__"]

"""Input readers: YAML config (now), KiCad ``.kicad_pcb`` (stage 6), Gerber (later)."""

from __future__ import annotations

from pcbsim.io.config import (
    AnalysisConfig,
    LoadedConfig,
    MeshOptions,
    load_config,
    load_config_dict,
)

__all__ = ["AnalysisConfig", "LoadedConfig", "MeshOptions", "load_config", "load_config_dict"]

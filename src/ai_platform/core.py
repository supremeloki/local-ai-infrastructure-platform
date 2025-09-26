from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Sequence


class PlatformError(Exception):
    pass


class ServiceStateError(PlatformError):
    pass


class PipelineStageError(PlatformError):
    def __init__(self, stage: str, cause: Exception) -> None:
        super().__init__(f"pipeline stage {stage!r} failed: {cause}")
        self.stage = stage
        self.cause = cause


class ServiceState(str, Enum):
    REGISTERED = "registered"
    STARTING = "starting"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    STOPPED = "stopped"


@dataclass(frozen=True)
class ServiceReport:
    name: str
    state: ServiceState
    startup_ms: float

    @property
    def is_usable(self) -> bool:
        return self.state in {ServiceState.HEALTHY, ServiceState.DEGRADED}


@dataclass(frozen=True)
class HealthCheckResult:
    service: str
    healthy: bool
    detail: str


class ManagedService:
    name: str = "service"

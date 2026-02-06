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

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def health(self) -> tuple[bool, str]:
        return True, "ok"


@dataclass(frozen=True)
class StoredBlob:
    key: str
    payload: str
    stored_at: float


class BlobStorage:
    def __init__(self, root: Path | None = None) -> None:
        self._root = root
        self._blobs: dict[str, StoredBlob] = {}
        if root is not None and (root / "index.json").exists():
            self._load()

    def put(self, key: str, payload: str) -> None:
        blob = StoredBlob(key=key, payload=payload, stored_at=time.time())
        self._blobs[key] = blob
        if self._root is not None:
            self._persist(blob)

    def get(self, key: str) -> StoredBlob | None:
        return self._blobs.get(key)

    def delete(self, key: str) -> bool:
        return self._blobs.pop(key, None) is not None

    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._blobs))

    def _persist(self, blob: StoredBlob) -> None:
        index = self._root / "index.json"
        existing: dict[str, Any] = {}
        if index.exists():
            try:
                existing = json.loads(index.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                existing = {}
        existing[blob.key] = {"payload": blob.payload, "stored_at": blob.stored_at}
        index.parent.mkdir(parents=True, exist_ok=True)
        index.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")

    def _load(self) -> None:
        index = self._root / "index.json"
        try:
            raw = json.loads(index.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise PlatformError(f"corrupt storage index: {exc}") from exc
        for key, entry in raw.items():
            self._blobs[key] = StoredBlob(
                key=key, payload=entry["payload"], stored_at=entry["stored_at"]
            )


PipelineStep = Callable[[dict[str, Any]], dict[str, Any]]


class InferencePipeline:
    def __init__(self, steps: Sequence[tuple[str, PipelineStep]]) -> None:
        names = [name for name, _ in steps]
        if len(names) != len(set(names)):
            raise PlatformError(f"duplicate pipeline stages: {names}")
        self._steps = list(steps)

    @property
    def stage_names(self) -> tuple[str, ...]:
        return tuple(name for name, _ in self._steps)

    def run(self, initial_context: dict[str, Any]) -> dict[str, Any]:
        context = dict(initial_context)
        for name, step in self._steps:
            started = time.perf_counter()
            try:
                result = step(context)
                if isinstance(result, dict):
                    context.update(result)
            except PlatformError:
                raise
            except Exception as exc:
                raise PipelineStageError(name, exc) from exc
            context.setdefault("_timings", {})[name] = round(
                (time.perf_counter() - started) * 1000, 3
            )
        return context


class AiInfrastructurePlatform:
    def __init__(self, storage_root: Path | None = None) -> None:
        self._services: dict[str, ManagedService] = {}
        self._states: dict[str, ServiceState] = {}
        self._startup_times: dict[str, float] = {}
        self.storage = BlobStorage(storage_root)
        self.pipelines: dict[str, InferencePipeline] = {}

    def register_service(self, service: ManagedService) -> "AiInfrastructurePlatform":
        if service.name in self._services:
            raise ServiceStateError(f"service already registered: {service.name!r}")
        self._services[service.name] = service
        self._states[service.name] = ServiceState.REGISTERED
        return self

    def start_all(self) -> list[ServiceReport]:
        reports: list[ServiceReport] = []
        for name in sorted(self._services):
            reports.append(self.start_service(name))
        return reports

    def start_service(self, name: str) -> ServiceReport:
        service = self._require(name)
        if self._states[name] == ServiceState.HEALTHY:
            raise ServiceStateError(f"{name!r} already running")
        self._states[name] = ServiceState.STARTING
        started = time.perf_counter()
        try:
            service.start()
        except Exception as exc:
            self._states[name] = ServiceState.STOPPED
            raise ServiceStateError(f"start failed for {name!r}: {exc}") from exc
        duration = (time.perf_counter() - started) * 1000
        self._startup_times[name] = duration
        healthy, _detail = service.health()
        self._states[name] = ServiceState.HEALTHY if healthy else ServiceState.DEGRADED
        return ServiceReport(
            name=name,
            state=self._states[name],
            startup_ms=round(duration, 3),
        )

    def stop_service(self, name: str) -> None:
        service = self._require(name)
        if self._states[name] != ServiceState.HEALTHY:
            raise ServiceStateError(f"{name!r} is not running")
        service.stop()
        self._states[name] = ServiceState.STOPPED

    def stop_all(self) -> None:
        for name in sorted(self._services, reverse=True):
            if self._states.get(name) == ServiceState.HEALTHY:
                self.stop_service(name)

    def health_report(self) -> list[HealthCheckResult]:
        results: list[HealthCheckResult] = []
        for name in sorted(self._services):
            if self._states[name] not in {ServiceState.HEALTHY, ServiceState.DEGRADED}:
                continue
            healthy, detail = self._services[name].health()
            results.append(HealthCheckResult(service=name, healthy=healthy, detail=detail))
        return results

    def run_pipeline(self, pipeline_name: str, context: dict[str, Any]) -> dict[str, Any]:
        pipeline = self.pipelines.get(pipeline_name)
        if pipeline is None:
            raise PlatformError(f"unknown pipeline: {pipeline_name!r}")
        return pipeline.run(context)

    def platform_status(self) -> dict[str, Any]:
        return {
            "services": {
                name: state.value for name, state in sorted(self._states.items())
            },
            "pipelines": sorted(self.pipelines),
            "storage_keys": len(self.storage.keys()),
        }

    def _require(self, name: str) -> ManagedService:
        service = self._services.get(name)
        if service is None:
            raise ServiceStateError(f"unknown service: {name!r}")
        return service

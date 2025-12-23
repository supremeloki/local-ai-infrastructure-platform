import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from ai_platform import (
    AiInfrastructurePlatform,
    BlobStorage,
    InferencePipeline,
    ManagedService,
    PipelineStageError,
    PlatformError,
    ServiceState,
    ServiceStateError,
)


class FakeModelService(ManagedService):
    name = "model_runtime"

    def __init__(self, healthy: bool = True) -> None:
        self.started = False
        self.stopped = False
        self._healthy = healthy

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def health(self):
        return self._healthy, "ok" if self._healthy else "degraded probe"


@pytest.fixture
def platform():
    app = AiInfrastructurePlatform()
    app.register_service(FakeModelService())
    return app


def test_register_and_start(platform):
    reports = platform.start_all()
    assert len(reports) == 1
    assert reports[0].is_usable
    assert platform.platform_status()["services"]["model_runtime"] == "healthy"


def test_duplicate_service_rejected():
    app = AiInfrastructurePlatform()
    app.register_service(FakeModelService())
    with pytest.raises(ServiceStateError):
        app.register_service(FakeModelService())


def test_unknown_service_rejected():
    with pytest.raises(ServiceStateError):
        AiInfrastructurePlatform().start_service("ghost")


def test_double_start_rejected(platform):
    platform.start_all()
    with pytest.raises(ServiceStateError):
        platform.start_service("model_runtime")


def test_stop_requires_running(platform):
    with pytest.raises(ServiceStateError):
        platform.stop_service("model_runtime")
    platform.start_all()
    platform.stop_service("model_runtime")
    assert platform.platform_status()["services"]["model_runtime"] == "stopped"


def test_degraded_state_when_unhealthy_probe():
    app = AiInfrastructurePlatform()
    app.register_service(FakeModelService(healthy=False))
    report = app.start_all()[0]
    assert report.state == ServiceState.DEGRADED
    assert report.is_usable


def test_health_report_only_live_services(platform):
    platform.start_all()
    results = platform.health_report()
    assert results[0].healthy
    platform.stop_all()
    assert platform.health_report() == []


def test_blob_storage_roundtrip(tmp_path):
    storage = BlobStorage(root=tmp_path / "blobs")
    storage.put("doc:1", "payload-one")
    reopened = BlobStorage(root=tmp_path / "blobs")
    assert reopened.get("doc:1").payload == "payload-one"
    assert storage.delete("doc:1") is True
    assert storage.get("doc:1") is None


def test_pipeline_executes_stages_with_timings():
    pipeline = InferencePipeline([
        ("normalize", lambda ctx: {"clean": ctx["text"].strip()}),
        ("score", lambda ctx: {"score": len(ctx["clean"]) * 0.1}),
    ])
    result = pipeline.run({"text": "  hello  "})
    assert result["clean"] == "hello"
    assert result["score"] == pytest.approx(0.5)
    assert set(result["_timings"]) == {"normalize", "score"}


def test_pipeline_wraps_stage_failures():
    def boom(ctx):
        raise KeyError("missing")

    pipeline = InferencePipeline([("bad_stage", boom)])
    with pytest.raises(PipelineStageError) as excinfo:
        pipeline.run({})
    assert excinfo.value.stage == "bad_stage"


def test_pipeline_duplicate_stages_rejected():
    with pytest.raises(PlatformError):
        InferencePipeline([("same", lambda c: c), ("same", lambda c: c)])


def test_platform_pipeline_dispatch(platform):
    platform.pipelines["demo"] = InferencePipeline([
        ("double", lambda ctx: {"value": ctx["x"] * 2}),
    ])
    assert platform.run_pipeline("demo", {"x": 21})["value"] == 42

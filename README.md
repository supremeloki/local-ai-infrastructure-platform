# ai-platform

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A local AI infrastructure platform: managed service lifecycle, blob storage with persistence, named inference pipelines with per-stage timings — the composition layer where runtime, storage, and orchestration meet.

## 🚀 Overview

The flagship capstone of the 2025 roadmap and the bridge to FAAVA. `ai-platform` composes the year's building blocks into one platform object: **services** (model runtime, vector store, …) register once and get lifecycle management with health probes; **pipelines** chain named stages with automatic timing collection and stage-level error wrapping; **blob storage** persists documents across restarts with a JSON index. Everything reports through a single status snapshot.

## ✨ Features

- **Service lifecycle:** `REGISTERED → STARTING → HEALTHY/DEGRADED → STOPPED` with illegal transitions rejected
- **Health probing:** live services report health; degraded-but-usable states distinguished from down
- **Named pipelines:** duplicate stage names rejected; every stage timed in `_timings`; failures wrapped as `PipelineStageError(stage)`
- **Blob storage:** file-backed JSON index survives restarts; typed corruption errors
- **Status snapshot:** one call returns services, pipelines, and storage counts
- **Zero dependencies**

## 🚧 Structure

```
local-ai-infrastructure-platform/
├── src/ai_platform/
│   ├── __init__.py
│   ├── core.py
│   ├── orchestration/
│   ├── runtime/
│   └── storage/
├── tests/
│   └── test_core.py
├── README.md
└── pyproject.toml
```

## 📦 Installation

```bash
git clone https://github.com/supremeloki/local-ai-infrastructure-platform.git
cd local-ai-infrastructure-platform
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

## 📋 Requirements

- Python 3.11+
- No runtime dependencies

## 🏃 Quick Start

```python
from pathlib import Path
from ai_platform import AiInfrastructurePlatform, InferencePipeline

platform = AiInfrastructurePlatform(storage_root=Path("./blobs"))
# platform.register_service(model_runtime_service)
reports = platform.start_all()

platform.pipelines["ask"] = InferencePipeline([
    ("normalize", lambda ctx: {"clean": ctx["text"].strip()}),
    ("retrieve", retrieve_step),
    ("answer", answer_step),
])
result = platform.run_pipeline("ask", {"text": "  سلام  "})
print(result["answer"], result["_timings"])
print(platform.platform_status())
```

## 🔧 Error Handling

```text
PlatformError
├── ServiceStateError      # unknown/duplicate services, bad transitions
└── PipelineStageError     # .stage + .cause for failing pipeline steps
```

## 🧪 Testing

```bash
pytest tests/ -v
```

## 📝 Code Quality

- Full type hints (`X | None` style), frozen contracts
- Zero comments — names carry the meaning
- Lifecycle transitions validated against an explicit state model

## 📄 License

MIT — see [LICENSE](LICENSE).

## 👤 Author

**Kooroush Masoumi** - [kooroushmasoumi@gmail.com](mailto:kooroushmasoumi@gmail.com)

---

⭐ Star this repo if you find it useful!

import json
import time
from pathlib import Path

_LOG_PATHS = (
    Path("/debug-logs/debug-1e6034.log"),
    Path("/home/neosoft/Indusbot/.cursor/debug-1e6034.log"),
    Path(__file__).resolve().parents[2] / ".cursor" / "debug-1e6034.log",
)


def debug_log(
    *,
    hypothesis_id: str,
    location: str,
    message: str,
    data: dict | None = None,
    run_id: str = "startup",
) -> None:
    # region agent log
    payload = {
        "sessionId": "1e6034",
        "runId": run_id,
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data or {},
        "timestamp": int(time.time() * 1000),
    }
    line = json.dumps(payload) + "\n"
    for path in _LOG_PATHS:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(line)
            return
        except OSError:
            continue
    # endregion

"""Dashboard endpoints for in-app updates (the sidebar pill and Settings).

- GET  /api/update               -> the UpdateManager status payload
- POST /api/update/check         -> 202 status (check now)
- POST /api/update/download      -> 202 status | 409 not-available / unsupported
- POST /api/update/install       -> 202 status | 409 not-ready / unsupported /
                                    <busy reason> with `blocked_by`
                                    {"force": true}: the user confirmed; skips
                                    only the game and Arena gates
                                    {"when": "idle"}: install after this game
- POST /api/update/skip          {"version": "x" | null} -> 200 status
- POST /api/update/acknowledge   -> 200 status (dismiss "Updated to vX")

`install` answers before the hand-off starts: the manager runs it on its own
thread after a short delay, so the 202 always reaches the browser. The POST
branch in dashboard.py requires a local Origin and a JSON body.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

Response = Tuple[int, Dict[str, Any]]


def _manager() -> Any:
    from .updater import get_manager

    return get_manager()


def handle_get(path: str, query: Optional[Dict[str, List[str]]] = None) -> Optional[Response]:
    if path != "/api/update":
        return None
    try:
        return 200, _manager().status()
    except Exception as exc:  # pragma: no cover - defensive surface
        return 500, {"error": f"{type(exc).__name__}: {exc}"}


def _blocked(exc: Any) -> Response:
    body: Dict[str, Any] = {"error": str(exc), "code": exc.code}
    blocked_by = getattr(exc, "blocked_by", None)
    if blocked_by is not None:
        body["blocked_by"] = list(blocked_by)
    return int(getattr(exc, "status", 409) or 409), body


def handle_post(path: str, payload: Dict[str, Any]) -> Optional[Response]:
    from .updater import UpdateError

    if not path.startswith("/api/update/"):
        return None
    action = path[len("/api/update/") :]
    payload = payload if isinstance(payload, dict) else {}
    manager = _manager()
    try:
        if action == "check":
            return 202, manager.check_now()
        if action == "download":
            return 202, manager.download()
        if action == "install":
            force = payload.get("force", False)
            when = payload.get("when", "now")
            if not isinstance(force, bool):
                return 400, {"error": "'force' must be a boolean", "code": "bad-request"}
            if when not in ("now", "idle"):
                return 400, {"error": '\'when\' must be "now" or "idle"', "code": "bad-request"}
            return 202, manager.request_install(force=force, when=when)
        if action == "skip":
            version = payload.get("version")
            if version is not None and not isinstance(version, str):
                return 400, {"error": "'version' must be a string or null", "code": "bad-request"}
            return 200, manager.skip(version)
        if action == "acknowledge":
            return 200, manager.acknowledge()
    except UpdateError as exc:
        return _blocked(exc)
    except Exception as exc:  # pragma: no cover - defensive surface
        return 500, {"error": f"{type(exc).__name__}: {exc}"}
    return None

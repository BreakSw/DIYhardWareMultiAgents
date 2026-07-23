from typing import Any


def success(data: Any = None, message: str = "ok") -> dict[str, Any]:
    return {"code": 0, "message": message, "data": data}


def failure(message: str, code: int = 400, data: Any = None) -> dict[str, Any]:
    return {"code": code, "message": message, "data": data}

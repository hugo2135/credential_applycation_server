import contextvars

from fastapi import Request
from sqlalchemy.orm import Session

from app.models import AccessLog


def client_ip(request: Request) -> str | None:
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else None


# /mcp 的驗證點（mcp.py 的 _JwtTokenVerifier）拿不到 Request 物件，只有 token 字串，
# 沒辦法像 auth.py／credential.py 那樣直接從 Request 取得 IP／method。改成在 main.py
# 的 ASGI 層（比 FastAPI 的 Request 更早、更底層）從原始 scope 讀出來，存進這個
# contextvar，_JwtTokenVerifier 再讀出來寫進 log。因為同一個請求從 ASGI 入口到
# verify_token() 都在同一個 async task 裡執行，contextvar 會自然帶過去，且每個
# 並發請求各自獨立、不會互相污染。
_mcp_request_context: contextvars.ContextVar[dict] = contextvars.ContextVar(
    "_mcp_request_context", default={"ip": None, "method": None}
)


def set_mcp_request_context(*, ip: str | None, method: str | None) -> None:
    _mcp_request_context.set({"ip": ip, "method": method})


def get_mcp_request_context() -> dict:
    return _mcp_request_context.get()


def record_access(
    db: Session,
    *,
    user_id: str | None,
    email: str | None,
    auth_method: str,
    path: str,
    method: str | None = None,
    ip_address: str | None = None,
    detail: str | None = None,
) -> None:
    db.add(AccessLog(
        user_id=user_id,
        email=email,
        path=path,
        method=method,
        auth_method=auth_method,
        ip_address=ip_address,
        detail=detail,
    ))
    db.commit()

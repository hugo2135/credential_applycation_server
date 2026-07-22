from fastapi import Request
from sqlalchemy.orm import Session

from app.models import AccessLog


def client_ip(request: Request) -> str | None:
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else None


def record_access(
    db: Session,
    *,
    user_id: str | None,
    email: str | None,
    auth_method: str,
    path: str,
    method: str | None = None,
    ip_address: str | None = None,
) -> None:
    db.add(AccessLog(
        user_id=user_id,
        email=email,
        path=path,
        method=method,
        auth_method=auth_method,
        ip_address=ip_address,
    ))
    db.commit()

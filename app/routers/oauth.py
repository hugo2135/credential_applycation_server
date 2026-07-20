import html
import os
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import OAuthAuthorizationCode, OAuthClient, OAuthRefreshToken, User
from app.security import (
    generate_authorization_code,
    generate_refresh_token,
    hash_opaque_token,
    issue_mcp_access_token,
    verify_password,
    verify_pkce,
)

router = APIRouter(tags=["oauth"])

AUTH_CODE_TTL_SECONDS = 300
REFRESH_TOKEN_TTL_DAYS = 90


def _issuer() -> str:
    domain = os.getenv("SITE_DOMAIN", "")
    return f"https://{domain}" if domain else "http://localhost:8000"


# ── Metadata (RFC 8414 / RFC 9728) ──────────────────────────────────────────

@router.get("/.well-known/oauth-authorization-server")
def authorization_server_metadata():
    issuer = _issuer()
    return {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/oauth/authorize",
        "token_endpoint": f"{issuer}/oauth/token",
        "registration_endpoint": f"{issuer}/oauth/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
    }


@router.get("/.well-known/oauth-protected-resource")
@router.get("/.well-known/oauth-protected-resource/mcp")
def protected_resource_metadata():
    # 註冊兩個路徑：裸路徑給只查根路徑的 client，/mcp 後綴路徑是因為 MCP
    # server 掛在 /mcp 底下，RFC 9728 §3.1 的 resource path 後綴規則會要求
    # 401 回應的 WWW-Authenticate 指向這個帶後綴的路徑。
    issuer = _issuer()
    return {
        "resource": f"{issuer}/mcp",
        "authorization_servers": [issuer],
    }


# ── Dynamic Client Registration (RFC 7591) ──────────────────────────────────

class RegisterClientRequest(BaseModel):
    redirect_uris: list[str]
    client_name: str | None = None


@router.post("/oauth/register", status_code=201)
def register_client(body: RegisterClientRequest, db: Session = Depends(get_db)):
    if not body.redirect_uris:
        raise HTTPException(status_code=400, detail="redirect_uris 不可為空")
    client = OAuthClient(client_name=body.client_name, redirect_uris=body.redirect_uris)
    db.add(client)
    db.commit()
    db.refresh(client)
    return {
        "client_id": client.client_id,
        "client_id_issued_at": int(client.created_at.timestamp()),
        "redirect_uris": client.redirect_uris,
        "client_name": client.client_name,
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
    }


# ── Authorize (login + consent) ─────────────────────────────────────────────

def _render_authorize_page(
    *, client: OAuthClient, error: str | None,
    response_type: str, client_id: str, redirect_uri: str,
    code_challenge: str, code_challenge_method: str, state: str, scope: str,
) -> str:
    client_name = html.escape(client.client_name or client.client_id)
    error_html = f'<p style="color:#c0392b">{html.escape(error)}</p>' if error else ""
    hidden_fields = "".join(
        f'<input type="hidden" name="{k}" value="{html.escape(v)}">'
        for k, v in {
            "response_type": response_type,
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
            "state": state,
            "scope": scope,
        }.items()
    )
    return f"""<!DOCTYPE html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<title>授權要求</title>
<style>
body {{ font-family: system-ui, sans-serif; max-width: 420px; margin: 60px auto; padding: 0 16px; color: #303133; }}
h1 {{ font-size: 18px; }}
label {{ display: block; margin-top: 12px; font-size: 14px; }}
input[type=email], input[type=password] {{ width: 100%; padding: 8px; margin-top: 4px; box-sizing: border-box; }}
button {{ margin-top: 20px; padding: 8px 20px; margin-right: 8px; }}
.deny {{ background: none; border: 1px solid #ccc; }}
</style></head>
<body>
<h1>{client_name} 想要存取你的 PBI 語意模型資料</h1>
<p style="font-size:13px;color:#666">請使用你在 PBI Credential 申請程式的帳號登入並同意授權。</p>
{error_html}
<form method="post" action="/oauth/authorize">
{hidden_fields}
<label>Email<input type="email" name="email" required></label>
<label>密碼<input type="password" name="password" required></label>
<button type="submit" name="action" value="approve">登入並授權</button>
<button type="submit" name="action" value="deny" class="deny">拒絕</button>
</form>
</body></html>"""


@router.get("/oauth/authorize", response_class=HTMLResponse)
def authorize_page(
    response_type: str = Query(...),
    client_id: str = Query(...),
    redirect_uri: str = Query(...),
    code_challenge: str = Query(...),
    code_challenge_method: str = Query("S256"),
    state: str = Query(""),
    scope: str = Query(""),
    db: Session = Depends(get_db),
):
    if response_type != "code":
        raise HTTPException(status_code=400, detail="僅支援 response_type=code")
    if code_challenge_method != "S256":
        raise HTTPException(status_code=400, detail="僅支援 code_challenge_method=S256")
    client = db.query(OAuthClient).filter(OAuthClient.client_id == client_id).first()
    if not client:
        raise HTTPException(status_code=400, detail="未知的 client_id")
    if redirect_uri not in client.redirect_uris:
        raise HTTPException(status_code=400, detail="redirect_uri 未在註冊清單中")

    return _render_authorize_page(
        client=client, error=None,
        response_type=response_type, client_id=client_id, redirect_uri=redirect_uri,
        code_challenge=code_challenge, code_challenge_method=code_challenge_method,
        state=state, scope=scope,
    )


@router.post("/oauth/authorize")
def authorize_submit(
    response_type: str = Form(...),
    client_id: str = Form(...),
    redirect_uri: str = Form(...),
    code_challenge: str = Form(...),
    code_challenge_method: str = Form("S256"),
    state: str = Form(""),
    scope: str = Form(""),
    email: str = Form(...),
    password: str = Form(...),
    action: str = Form(...),
    db: Session = Depends(get_db),
):
    client = db.query(OAuthClient).filter(OAuthClient.client_id == client_id).first()
    if not client or redirect_uri not in client.redirect_uris:
        raise HTTPException(status_code=400, detail="無效的 client_id 或 redirect_uri")

    if action == "deny":
        return RedirectResponse(f"{redirect_uri}?error=access_denied&state={state}", status_code=302)

    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.password_hash):
        return HTMLResponse(
            _render_authorize_page(
                client=client, error="帳號或密碼錯誤",
                response_type=response_type, client_id=client_id, redirect_uri=redirect_uri,
                code_challenge=code_challenge, code_challenge_method=code_challenge_method,
                state=state, scope=scope,
            ),
            status_code=401,
        )
    if not user.is_active:
        return HTMLResponse(
            _render_authorize_page(
                client=client, error="帳號尚未開通，請聯絡管理員",
                response_type=response_type, client_id=client_id, redirect_uri=redirect_uri,
                code_challenge=code_challenge, code_challenge_method=code_challenge_method,
                state=state, scope=scope,
            ),
            status_code=403,
        )

    code = generate_authorization_code()
    db.add(OAuthAuthorizationCode(
        code=code,
        client_id=client_id,
        user_id=user.id,
        redirect_uri=redirect_uri,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        expires_at=datetime.utcnow() + timedelta(seconds=AUTH_CODE_TTL_SECONDS),
    ))
    db.commit()
    return RedirectResponse(f"{redirect_uri}?code={code}&state={state}", status_code=302)


# ── Token exchange ───────────────────────────────────────────────────────────

@router.post("/oauth/token")
def token_endpoint(
    grant_type: str = Form(...),
    code: str | None = Form(None),
    redirect_uri: str | None = Form(None),
    client_id: str | None = Form(None),
    code_verifier: str | None = Form(None),
    refresh_token: str | None = Form(None),
    db: Session = Depends(get_db),
):
    if grant_type == "authorization_code":
        if not (code and redirect_uri and client_id and code_verifier):
            raise HTTPException(status_code=400, detail="缺少必要參數")
        auth_code = db.query(OAuthAuthorizationCode).filter(OAuthAuthorizationCode.code == code).first()
        if not auth_code or auth_code.used:
            raise HTTPException(status_code=400, detail="invalid_grant")
        if auth_code.expires_at < datetime.utcnow():
            raise HTTPException(status_code=400, detail="authorization code 已過期")
        if auth_code.client_id != client_id or auth_code.redirect_uri != redirect_uri:
            raise HTTPException(status_code=400, detail="invalid_grant")
        if not verify_pkce(code_verifier, auth_code.code_challenge, auth_code.code_challenge_method):
            raise HTTPException(status_code=400, detail="PKCE 驗證失敗")

        user = db.query(User).filter(User.id == auth_code.user_id).first()
        if not user or not user.is_active:
            raise HTTPException(status_code=400, detail="使用者不存在或未開通")

        auth_code.used = True
        raw_refresh = generate_refresh_token()
        db.add(OAuthRefreshToken(
            token_hash=hash_opaque_token(raw_refresh),
            client_id=client_id,
            user_id=user.id,
            expires_at=datetime.utcnow() + timedelta(days=REFRESH_TOKEN_TTL_DAYS),
        ))
        db.commit()

        return {
            "access_token": issue_mcp_access_token(user.id, user.email, client_id),
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": raw_refresh,
        }

    if grant_type == "refresh_token":
        if not (refresh_token and client_id):
            raise HTTPException(status_code=400, detail="缺少必要參數")
        token_hash = hash_opaque_token(refresh_token)
        record = db.query(OAuthRefreshToken).filter(OAuthRefreshToken.token_hash == token_hash).first()
        if not record or record.revoked or record.client_id != client_id:
            raise HTTPException(status_code=400, detail="invalid_grant")
        if record.expires_at < datetime.utcnow():
            raise HTTPException(status_code=400, detail="refresh token 已過期")

        user = db.query(User).filter(User.id == record.user_id).first()
        if not user or not user.is_active:
            raise HTTPException(status_code=400, detail="使用者不存在或未開通")

        # 輪換 refresh token：舊的作廢、發一個新的
        record.revoked = True
        raw_refresh = generate_refresh_token()
        db.add(OAuthRefreshToken(
            token_hash=hash_opaque_token(raw_refresh),
            client_id=client_id,
            user_id=user.id,
            expires_at=datetime.utcnow() + timedelta(days=REFRESH_TOKEN_TTL_DAYS),
        ))
        db.commit()

        return {
            "access_token": issue_mcp_access_token(user.id, user.email, client_id),
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": raw_refresh,
        }

    raise HTTPException(status_code=400, detail="不支援的 grant_type")

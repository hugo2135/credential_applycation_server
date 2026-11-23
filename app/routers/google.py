"""Google 登入的路由（核心邏輯在 app/google_login.py）。

全部放在 /oauth/google/ 底下：/oauth/ 在 IP 白名單豁免清單裡，MCP 授權頁本來就要給外網的
瀏覽器用，Google 跳回來打 callback 的也是使用者的瀏覽器，不是 Google 的伺服器。使用者／
管理員網頁登入走這裡拿到的 session JWT，之後打 /auth/*、/api/admin/* 仍然受 IP 白名單限制，
所以不會因此繞過「網頁只限內網」。

一個 callback 服務三個入口（flow）：
  user  → 使用者網頁登入，成功導回 /login#google_token=...（SPA 從 fragment 取出存起來）
  admin → 管理後台登入（限 is_admin 的既有帳號，不建帳號），成功導回 /admin/login#google_token=...
  mcp   → MCP 授權頁，成功直接發 authorization code 導回 MCP client
token 放 URL fragment 而不是 query string：fragment 不會送到伺服器，不會出現在任何存取 log。
"""

import html
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.google_login import (
    GoogleLoginError,
    authorization_url,
    fetch_id_token,
    issue_flow_state,
    load_config,
    read_flow_state,
    require_config,
    resolve_user,
    validate_claims,
)
from app.models import OAuthClient
from app.routers.oauth import (
    _issuer,
    issue_authorization_code,
    render_authorize_page,
    validate_authorize_request,
)
from app.security import admin_login_denial, issue_admin_jwt, issue_user_jwt

router = APIRouter(prefix="/oauth/google", tags=["google-login"])

STATE_COOKIE = "google_login_state"
_FLOW_LOGIN_PAGES = {"user": "/login", "admin": "/admin/login"}
_MCP_PARAMS = ("response_type", "client_id", "redirect_uri", "code_challenge", "code_challenge_method", "state", "scope")


def _callback_url() -> str:
    # 必須跟 Google Cloud Console 登記的「已授權的重新導向 URI」一字不差
    return f"{_issuer()}/oauth/google/callback"


def _to_login_page(flow: str, **fragment: str) -> RedirectResponse:
    return RedirectResponse(f"{_FLOW_LOGIN_PAGES[flow]}#{urlencode(fragment)}", status_code=302)


def _mcp_error_page(db: Session, params: dict, error: str) -> HTMLResponse:
    client = db.query(OAuthClient).filter(OAuthClient.client_id == params.get("client_id")).first()
    if not client:
        raise HTTPException(status_code=400, detail=error)
    return HTMLResponse(
        render_authorize_page(db, client=client, error=error, **{k: params.get(k, "") for k in _MCP_PARAMS}),
        status_code=403,
    )


@router.get("/status")
def google_login_status(db: Session = Depends(get_db)):
    """登入頁用來決定要不要顯示「用 Google 登入」按鈕。"""
    return {"enabled": load_config(db) is not None}


@router.get("/start")
def google_login_start(
    request: Request,
    flow: str = Query(...),
    db: Session = Depends(get_db),
):
    if flow not in ("user", "admin", "mcp"):
        raise HTTPException(status_code=400, detail="未知的 flow")

    params = {}
    if flow == "mcp":
        params = {k: request.query_params.get(k, "") for k in _MCP_PARAMS}
        params["code_challenge_method"] = params["code_challenge_method"] or "S256"
        if not params["code_challenge"]:
            raise HTTPException(status_code=400, detail="缺少 code_challenge")
        validate_authorize_request(
            db, response_type=params["response_type"], client_id=params["client_id"],
            redirect_uri=params["redirect_uri"], code_challenge_method=params["code_challenge_method"],
        )

    try:
        config = require_config(db)
    except GoogleLoginError as e:
        if flow == "mcp":
            return _mcp_error_page(db, params, str(e))
        return _to_login_page(flow, google_error=str(e))

    cookie, state, nonce = issue_flow_state(flow, params)
    response = RedirectResponse(authorization_url(config, _callback_url(), state, nonce), status_code=302)
    response.set_cookie(
        STATE_COOKIE, cookie,
        max_age=600, path="/oauth/google", httponly=True,
        # Lax：Google 導回來是 top-level GET，Lax 會帶 cookie；跨站的子請求則不會
        samesite="lax", secure=_issuer().startswith("https://"),
    )
    return response


@router.get("/callback")
def google_login_callback(
    request: Request,
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
    db: Session = Depends(get_db),
):
    flow_state = read_flow_state(request.cookies.get(STATE_COOKIE))
    if not flow_state or not state or state != flow_state["state"]:
        # cookie 不見（逾時、換了瀏覽器）或 state 對不上：無法得知原本是哪個入口，只能請他重來
        response = HTMLResponse(_message_page(
            "登入逾時或驗證失敗",
            "請回到原本的登入頁重新點「用 Google 登入」。",
        ), status_code=400)
        response.delete_cookie(STATE_COOKIE, path="/oauth/google")
        return response

    flow = flow_state["flow"]
    params = flow_state["params"]
    response = _finish(db, flow, params, code, error, flow_state["nonce"])
    response.delete_cookie(STATE_COOKIE, path="/oauth/google")
    return response


def _finish(db: Session, flow: str, params: dict, code: str | None, error: str | None, nonce: str):
    try:
        if error or not code:
            # 使用者在 Google 畫面按取消，或 Google 拒絕（例如 Internal app 但用了外部帳號）
            raise GoogleLoginError("已取消 Google 登入" if error == "access_denied" else "Google 登入未完成，請重試")
        config = require_config(db)
        claims = validate_claims(config, fetch_id_token(config, code, _callback_url()), nonce)

        user, linked = resolve_user(db, config, claims, create=flow != "admin")
        if flow == "admin":
            denial = admin_login_denial(user)
            if denial:
                raise GoogleLoginError(denial)
            return _to_login_page("admin", google_token=issue_admin_jwt(str(user.id), user.email))
    except GoogleLoginError as e:
        if flow == "mcp":
            return _mcp_error_page(db, params, str(e))
        return _to_login_page(flow, google_error=str(e))

    if flow == "user":
        # 跟帳密登入一樣，沒開通也可以登入網頁看自己的狀態，只是什麼都不能做
        fragment = {"google_token": issue_user_jwt(str(user.id), user.email), "email": user.email}
        if linked:
            fragment["google_linked"] = "1"
        return _to_login_page("user", **fragment)

    if not user.is_active:
        return _mcp_error_page(db, params, "帳號尚未開通，請聯絡管理員")
    code = issue_authorization_code(
        db, client_id=params["client_id"], user=user, redirect_uri=params["redirect_uri"],
        code_challenge=params["code_challenge"], code_challenge_method=params["code_challenge_method"],
    )
    target = f"{params['redirect_uri']}?{urlencode({'code': code, 'state': params['state']})}"
    if linked:
        # 綁定的那一次先告知原密碼失效，按繼續才回到 MCP client（authorization code 5 分鐘內有效）
        return HTMLResponse(_message_page(
            "已綁定 Google 帳號",
            f"這個 Google 帳號已綁定到既有帳號 {user.email}。原本的密碼已經失效，"
            "之後請使用「用 Google 登入」。",
            continue_url=target,
        ))
    return RedirectResponse(target, status_code=302)


def _message_page(title: str, message: str, continue_url: str | None = None) -> str:
    button = f'<a class="btn" href="{html.escape(continue_url)}">繼續</a>' if continue_url else ""
    return f"""<!DOCTYPE html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
body {{ font-family: system-ui, sans-serif; max-width: 420px; margin: 60px auto; padding: 0 16px; color: #303133; }}
h1 {{ font-size: 18px; }}
p {{ font-size: 14px; line-height: 1.7; }}
.btn {{ display: inline-block; margin-top: 12px; padding: 8px 24px; background: #409eff; color: #fff;
  border-radius: 4px; text-decoration: none; }}
</style></head>
<body>
<h1>{html.escape(title)}</h1>
<p>{html.escape(message)}</p>
{button}
</body></html>"""

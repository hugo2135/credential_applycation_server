"""Google 登入（OpenID Connect authorization code flow）。

設定都在 /admin/settings（見 system_settings 的 google_* 與 allowed_email_domains），
路由在 app/routers/google.py。三個入口共用這裡的邏輯：使用者網頁登入、MCP 授權頁、管理後台登入。

帳號一律用 id_token 的 `sub`（Google 帳號 ID，不會變也不會重複使用）連結，email 只拿來
判斷網域與第一次登入時找要綁定的既有帳號，理由見 models.User.google_sub。
"""

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from jose import JWTError, jwt
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import User
from app.security import JWT_ALGORITHM, _get_secret, hash_password
from app.system_settings import get_secret, get_setting

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")
FLOW_STATE_TTL_SECONDS = 600


class GoogleLoginError(Exception):
    """訊息會直接顯示給使用者，寫成看得懂、知道下一步找誰的句子。"""


@dataclass(frozen=True)
class GoogleConfig:
    client_id: str
    client_secret: str
    allowed_domains: list[str]
    auto_activate: bool
    auto_link: bool
    admin_emails: list[str]


def load_config(db: Session) -> GoogleConfig | None:
    """沒啟用或設定不完整時回傳 None。網域清單是空的也算不完整：Google 登入會自動開通帳號，
    不能在沒限制網域時對所有 Google 帳號開放。"""
    if not get_setting(db, "google_login_enabled"):
        return None
    client_id = get_setting(db, "google_client_id")
    client_secret = get_secret(db, "google_client_secret")
    domains = get_setting(db, "allowed_email_domains")
    if not (client_id and client_secret and domains):
        return None
    return GoogleConfig(
        client_id=client_id,
        client_secret=client_secret,
        allowed_domains=domains,
        auto_activate=get_setting(db, "google_auto_activate"),
        auto_link=get_setting(db, "google_auto_link"),
        admin_emails=get_setting(db, "google_admin_emails"),
    )


def require_config(db: Session) -> GoogleConfig:
    config = load_config(db)
    if config is None:
        raise GoogleLoginError("Google 登入尚未啟用，請改用帳號密碼登入或聯絡管理員")
    return config


# ── 跳去 Google 前後的狀態 ──────────────────────────────────────────────────
# 存在簽章過的 cookie 裡（不另開資料表）：state 同時放 cookie 與 Google 帶回來的參數，
# 兩邊一致才代表是同一個瀏覽器發起的（防 login CSRF）；nonce 綁住 id_token 防重放；
# MCP 授權頁的原始 OAuth 參數也放這裡，回來後才接得回原本的授權流程。

def issue_flow_state(flow: str, params: dict | None = None) -> tuple[str, str, str]:
    """回傳 (cookie 值, state, nonce)。"""
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    now = datetime.now(timezone.utc)
    token = jwt.encode({
        "iss": "google-login-state",
        "flow": flow,
        "params": params or {},
        "state": state,
        "nonce": nonce,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=FLOW_STATE_TTL_SECONDS)).timestamp()),
    }, _get_secret(), algorithm=JWT_ALGORITHM)
    return token, state, nonce


def read_flow_state(cookie: str | None) -> dict | None:
    """cookie 不存在、過期或被竄改都回傳 None。"""
    if not cookie:
        return None
    try:
        payload = jwt.decode(cookie, _get_secret(), algorithms=[JWT_ALGORITHM])
    except JWTError:
        return None
    if payload.get("iss") != "google-login-state":
        return None
    return payload


def authorization_url(config: GoogleConfig, redirect_uri: str, state: str, nonce: str) -> str:
    params = {
        "client_id": config.client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        # 只要 openid（sub、hd）跟 email，不要 profile：用不到就不索取
        "scope": "openid email",
        "state": state,
        "nonce": nonce,
        "prompt": "select_account",
        # hd 只是讓 Google 登入畫面預設選那個網域，使用者改網址就能繞過，
        # 真正的檢查在 validate_claims。多個網域時用 "*"（只提示要 Workspace 帳號）。
        "hd": config.allowed_domains[0] if len(config.allowed_domains) == 1 else "*",
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


# ── 回來之後 ────────────────────────────────────────────────────────────────

def fetch_id_token(config: GoogleConfig, code: str, redirect_uri: str) -> str:
    """用 authorization code 跟 Google 換 id_token。一般 FastAPI 同步端點跑在 thread pool，
    這裡用同步 httpx 沒問題（同 query_check.py）。"""
    try:
        res = httpx.post(GOOGLE_TOKEN_URL, data={
            "code": code,
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }, timeout=10)
    except httpx.HTTPError:
        raise GoogleLoginError("無法連線到 Google，請稍後再試") from None
    if res.status_code != 200:
        # 最常見是 client secret 填錯或過期（invalid_client），或 code 已用過（invalid_grant）
        try:
            reason = res.json().get("error", res.status_code)
        except ValueError:
            reason = res.status_code
        raise GoogleLoginError(f"Google 登入失敗（{reason}），請聯絡管理員確認 Google 登入設定")
    id_token = res.json().get("id_token")
    if not id_token:
        raise GoogleLoginError("Google 沒有回傳身分資訊，請聯絡管理員確認 Google 登入設定")
    return id_token


def validate_claims(config: GoogleConfig, id_token: str, nonce: str) -> dict:
    """驗證 id_token 並回傳 claims。

    不驗簽章：這個 token 是我們自己透過 TLS 直接跟 Google token endpoint 拿的，不是經過
    瀏覽器轉交，OpenID Connect Core 3.1.3.7 明定這種情況可以用 TLS 取代簽章驗證，
    省掉抓 Google 公鑰、處理金鑰輪替。其餘 claim 照規定一項不少地檢查。
    """
    try:
        claims = jwt.get_unverified_claims(id_token)
    except JWTError:
        raise GoogleLoginError("Google 回傳的身分資訊格式不正確") from None

    aud = claims.get("aud")
    if claims.get("iss") not in GOOGLE_ISSUERS or config.client_id not in (aud if isinstance(aud, list) else [aud]):
        raise GoogleLoginError("Google 回傳的身分資訊不是發給本系統的")
    if not isinstance(claims.get("exp"), (int, float)) or claims["exp"] < datetime.now(timezone.utc).timestamp():
        raise GoogleLoginError("Google 登入已逾時，請重新登入")
    if not nonce or not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise GoogleLoginError("登入驗證失敗，請重新登入")
    if not claims.get("sub") or not claims.get("email"):
        raise GoogleLoginError("Google 沒有提供帳號 email，請聯絡管理員")
    if claims.get("email_verified") is not True:
        raise GoogleLoginError("這個 Google 帳號的 email 尚未驗證")

    # hd 是公司 Workspace 的網域，個人 Google 帳號沒有。只看 email 網域不夠：有人可以用公司
    # email 註冊「個人」Google 帳號（離職後仍然能登入），那種帳號沒有 hd，在這裡會被擋。
    hd = str(claims.get("hd", "")).lower()
    email_domain = claims["email"].rsplit("@", 1)[-1].lower()
    if not hd or hd not in config.allowed_domains or email_domain not in config.allowed_domains:
        raise GoogleLoginError(f"{claims['email']} 不是允許登入的公司帳號，請改用公司的 Google 帳號")
    return claims


def resolve_user(db: Session, config: GoogleConfig, claims: dict) -> tuple[User, bool]:
    """依 Google 帳號找出（或建立）使用者，回傳 (user, 這次是否新綁定既有帳號)。呼叫端負責檢查 is_active。

    順序：sub 找到 → 直接登入；沒有再用 email 找 → 還沒綁過就綁定（要開自動綁定），
    綁的是別的 sub 就拒絕（通常是離職者的 email 被重新分配）；都找不到 → 建立新帳號。
    綁定只寫 google_sub，不動原帳號任何其他欄位（包括是否開通）。
    """
    sub = str(claims["sub"])
    email = claims["email"]

    user = db.query(User).filter(User.google_sub == sub).first()
    if user:
        return user, False

    user = db.query(User).filter(func.lower(User.email) == email.lower()).first()
    if user:
        if user.google_sub:
            raise GoogleLoginError(f"{email} 已綁定其他 Google 帳號，請聯絡管理員")
        if not config.auto_link:
            raise GoogleLoginError(f"{email} 已有帳號，請改用帳號密碼登入；要改用 Google 登入請聯絡管理員")
        user.google_sub = sub
        db.commit()
        return user, True

    user = User(
        email=email,
        # 不會被用到（有 google_sub 時帳密登入一律拒絕），只是欄位不可為空；隨機值確保
        # 管理員日後解除綁定時這個帳號也沒有可用的密碼。
        password_hash=hash_password(secrets.token_urlsafe(32)),
        google_sub=sub,
        is_active=config.auto_activate,
        query_execution=get_setting(db, "default_query_execution"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user, False


def check_admin(config: GoogleConfig, claims: dict) -> None:
    if claims["email"].lower() not in config.admin_emails:
        raise GoogleLoginError(f"{claims['email']} 沒有管理後台權限")

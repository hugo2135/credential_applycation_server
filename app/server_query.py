"""Server 查詢模式：由 server 用使用者的 SP 代為執行 DAX，結果直接回給 MCP tool（v2.0）。

跟 edge 模式（skill 拿一次性 ticket、查詢腳本自己打 Power BI）並存，使用者層級切換
（`User.query_execution`）。server 模式的好處是 client 端不需要 code execution，也不用把
`SITE_DOMAIN`／`api.powerbi.com` 加進沙盒的 network egress 白名單。

早期版本也讓 server 代跑過查詢，後來拿掉，因為那時在 MCP tool 裡用同步網路呼叫，並發時
卡住整個 event loop（MCP tool 沒有 FastAPI 端點那種自動 thread pool offload）。這裡的
規則就是為了不重蹈覆轍：
- 打 Power BI 一律用 `httpx.AsyncClient`；MSAL 換 token 是同步呼叫，丟到 thread 跑。
- 同時進行中的查詢數有上限（`server_query_max_concurrency`），超過的排隊，保護小 VM。
- 整段（含排隊）有 timeout，回傳列數有上限——結果會整包進入對話上下文。
- 呼叫端在 await 期間不要握著 DB session：一個查詢可能等上幾十秒。
"""

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace

import anyio
import httpx
from fastapi import HTTPException

from app.query_check import _POWERBI_HINTS, explain_aad_error
from app.routers.credential import acquire_powerbi_token

_RAW_ERROR_MAX_CHARS = 1000


class ServerQueryError(Exception):
    """查詢失敗，訊息會原樣交給 AI（DAX 錯誤時 AI 據此修正後重試）。"""


@dataclass(frozen=True)
class QueryTarget:
    """執行一次查詢需要的全部資料。刻意是純值：呼叫端讀完 DB 就關掉 session，
    await 期間不碰任何 ORM 物件（commit 後屬性會 expire，跨 session 讀取會出錯）。"""
    tenant_id: str
    client_id: str
    client_secret_enc: str
    workspace_id: str
    dataset_id: str


@dataclass(frozen=True)
class QueryLimits:
    max_concurrency: int
    max_rows: int
    timeout_seconds: int


# CapacityLimiter 綁定建立它的 event loop；正式環境只有一個 loop，但測試每個 client
# 各自起 loop，所以記下 loop、換了就重建。
_limiter_state: tuple[asyncio.AbstractEventLoop, anyio.CapacityLimiter] | None = None


def _limiter(total: int) -> anyio.CapacityLimiter:
    global _limiter_state
    loop = asyncio.get_running_loop()
    if _limiter_state is None or _limiter_state[0] is not loop:
        _limiter_state = (loop, anyio.CapacityLimiter(total))
    limiter = _limiter_state[1]
    # 管理員在設定頁改了上限，下一個查詢就生效（調低時已在跑的查詢不受影響，只是之後少放行）
    limiter.total_tokens = total
    return limiter


def _http_client() -> httpx.AsyncClient:
    # 獨立成函式讓測試可以換成 MockTransport；直接 patch httpx.AsyncClient 會連 MCP 測試
    # client 自己的連線一起換掉
    return httpx.AsyncClient()


def _powerbi_error_detail(res: httpx.Response) -> str:
    """從 Power BI 的錯誤回應抽出 DAX 錯誤說明（在 error.pbi.error.details[].detail.value）。"""
    try:
        body = res.json()
    except ValueError:
        return res.text[:_RAW_ERROR_MAX_CHARS]
    return _error_from_body(body.get("error") or {}) or res.text[:_RAW_ERROR_MAX_CHARS]


def _error_from_body(error: dict) -> str:
    details = (error.get("pbi.error") or {}).get("details") or []
    messages = [
        d["detail"]["value"] for d in details
        if isinstance(d.get("detail"), dict) and d["detail"].get("value")
    ]
    return "; ".join(messages) or error.get("message") or error.get("code") or ""


# 超過 Power BI 單次查詢上限時，executeQueries 照樣回 HTTP 200、只給部分資料，錯誤碼藏在
# 某一層的 error 裡（官方文件沒說哪一層，最外層／單一查詢結果／資料表都有 error 欄位）。
# 沒有 truncated 之類的欄位，只能靠錯誤碼判斷。
_POWERBI_LIMIT_CODES = {
    "DaxRowCountNotSupported": "powerbi_row_limit",   # 超過 10 萬列或 100 萬個值
    "DaxByteCountNotSupported": "powerbi_byte_limit",  # 超過 15MB
}
_LIMIT_DESCRIPTIONS = {
    "powerbi_row_limit": "10 萬列或 100 萬個值",
    "powerbi_byte_limit": "15MB",
}


def _find_limit_error(node) -> str | None:
    """掃整個回應找上限錯誤碼，回傳 truncated_reason。跳過 rows：資料內容剛好含有
    這個字串時不能誤判。"""
    if isinstance(node, dict):
        for key, value in node.items():
            if key != "rows" and (reason := _find_limit_error(value)):
                return reason
    elif isinstance(node, list):
        for item in node:
            if reason := _find_limit_error(item):
                return reason
    elif isinstance(node, str):
        for code, reason in _POWERBI_LIMIT_CODES.items():
            if code in node:
                return reason
    return None


def _shape_tables(results: list, max_rows: int, limit_reason: str | None) -> list[dict]:
    tables = []
    for result in results:
        if result.get("error") and not _find_limit_error(result["error"]):
            raise ServerQueryError(f"DAX 執行錯誤：{_error_from_body(result['error']) or result['error']}")
        for table in result.get("tables") or []:
            rows = table.get("rows") or []
            # Power BI 已經截斷時 row_count 只是拿到的列數、不是總數，原因以 Power BI 為準
            reason = limit_reason or ("max_rows" if len(rows) > max_rows else None)
            # rows 放最後：client 端從尾巴截斷過長的回傳時，截斷標記才不會跟著不見
            tables.append({
                "columns": list(rows[0].keys()) if rows else [],
                "row_count": len(rows),
                "truncated": reason is not None,
                "truncated_reason": reason,
                "rows": rows[:max_rows],
            })
    return tables


async def execute_dax(target: QueryTarget, dax: str, limits: QueryLimits) -> dict:
    url = (
        f"https://api.powerbi.com/v1.0/myorg/groups/{target.workspace_id}"
        f"/datasets/{target.dataset_id}/executeQueries"
    )
    acquired = False
    try:
        with anyio.fail_after(limits.timeout_seconds):
            async with _limiter(limits.max_concurrency):
                acquired = True
                try:
                    # acquire_powerbi_token 只讀這三個屬性，用純值物件傳進去
                    creds = SimpleNamespace(
                        tenant_id=target.tenant_id,
                        client_id=target.client_id,
                        client_secret_enc=target.client_secret_enc,
                    )
                    token = (await anyio.to_thread.run_sync(acquire_powerbi_token, creds))["access_token"]
                except HTTPException as e:
                    raise ServerQueryError(
                        f"Azure AD 驗證失敗：{explain_aad_error(str(e.detail))}，請聯絡管理員"
                    ) from None

                async with _http_client() as client:
                    try:
                        res = await client.post(
                            url,
                            json={"queries": [{"query": dax}], "serializerSettings": {"includeNulls": True}},
                            headers={"Authorization": f"Bearer {token}"},
                            timeout=limits.timeout_seconds,
                        )
                    except httpx.HTTPError as e:
                        raise ServerQueryError(f"無法連線到 Power BI：{type(e).__name__}") from None
    except TimeoutError:
        if not acquired:
            raise ServerQueryError("目前查詢量較大，排隊逾時，請稍後再試") from None
        raise ServerQueryError(
            f"查詢超過 {limits.timeout_seconds} 秒仍未完成，請簡化 DAX（例如先彙總、加篩選或用 TOPN 限制列數）"
        ) from None

    if res.status_code != 200:
        try:
            limit_reason = _find_limit_error(res.json())
        except ValueError:
            limit_reason = None
        if limit_reason:
            # 不是 DAX 寫錯，不能報成「DAX 執行錯誤」讓 AI 去改語法
            raise ServerQueryError(
                f"查詢結果超過 Power BI 單次查詢上限（{_LIMIT_DESCRIPTIONS[limit_reason]}），"
                f"Power BI 沒有回傳資料。請告知使用者，並詢問是否改成分批查詢（會額外消耗 token）："
                f"{_powerbi_error_detail(res)}"
            )
    if res.status_code == 400:
        # executeQueries 的 DAX 語法／語意錯誤都是 400，錯誤說明交給 AI 修正
        raise ServerQueryError(f"DAX 執行錯誤：{_powerbi_error_detail(res)}")
    if res.status_code != 200:
        hint = _POWERBI_HINTS.get(res.status_code, f"Power BI 回應 HTTP {res.status_code}")
        raise ServerQueryError(f"{hint}（HTTP {res.status_code}）")

    try:
        body = res.json()
    except ValueError:
        raise ServerQueryError("Power BI 回應格式無法解析") from None
    tables = _shape_tables(body.get("results") or [], limits.max_rows, _find_limit_error(body))
    return {"tables": tables, "max_rows": limits.max_rows}

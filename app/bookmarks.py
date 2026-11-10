"""書籤（使用者存下來的常用查詢）的共用邏輯。MCP tool（mcp.py）跟使用者網頁的
REST API（auth.py 的 /auth/bookmarks）都走這裡，兩邊的驗證規則與上限保證一致。

只能存取「目前仍被指派」的模型的書籤：管理員取消指派後，書籤留在 DB 但不會出現，
重新指派就回來，不需要使用者重存。
"""

from datetime import datetime

from sqlalchemy.orm import Session

from app.model_versions import serving_model_version
from app.models import Bookmark, PbiConfig, UserPbiConfig

# 上限是為了保護 1GB RAM 的小 VM：書籤是讓使用者無限寫入的資料，不設限就可能被灌爆。
MAX_BOOKMARKS_PER_USER = 100
MAX_TITLE_CHARS = 100
MAX_DAX_CHARS = 20000
MAX_QUESTION_CHARS = 2000

EXPORT_FORMAT = "nl-to-dax-bookmarks"
EXPORT_VERSION = 1


class BookmarkError(Exception):
    """可以直接顯示給使用者的錯誤訊息。"""


def _accessible_configs(db: Session, user_id: str) -> dict[str, PbiConfig]:
    rows = (
        db.query(PbiConfig)
        .join(UserPbiConfig, UserPbiConfig.pbi_config_id == PbiConfig.id)
        .filter(UserPbiConfig.user_id == user_id)
        .all()
    )
    return {c.id: c for c in rows}


def bookmark_dict(b: Bookmark, config_name: str | None, current_version: int | None) -> dict:
    return {
        "id": b.id,
        "pbi_config_id": b.pbi_config_id,
        "pbi_config_name": config_name,
        "title": b.title,
        "dax": b.dax,
        "question": b.question,
        "model_version": b.model_version,
        "current_model_version": current_version,
        # 存檔後模型升過版，DAX 引用的表/欄位可能已經改名或刪除，skill 應改用
        # question 重新生成，或至少先跟使用者確認
        "possibly_outdated": (
            b.model_version is not None and current_version is not None and current_version != b.model_version
        ),
        "created_at": b.created_at,
        "updated_at": b.updated_at,
    }


def list_bookmarks(db: Session, user_id: str, pbi_config_id: str | None = None) -> list[dict]:
    configs = _accessible_configs(db, user_id)
    if pbi_config_id is not None:
        if pbi_config_id not in configs:
            raise BookmarkError("無此 PBI 設定的存取權")
        configs = {pbi_config_id: configs[pbi_config_id]}
    if not configs:
        return []

    # 跟 MCP 實際提供的版本比，不是跟最新版比：管理員退回舊版時，新版上存的書籤要標成可能過時
    versions = {cid: serving_model_version(db, cid) for cid in configs}
    rows = (
        db.query(Bookmark)
        .filter(Bookmark.user_id == user_id, Bookmark.pbi_config_id.in_(list(configs)))
        .order_by(Bookmark.updated_at.desc())
        .all()
    )
    return [bookmark_dict(b, configs[b.pbi_config_id].name, versions[b.pbi_config_id]) for b in rows]


def _validate(title: str, dax: str, question: str | None) -> tuple[str, str, str | None]:
    title = (title or "").strip()
    dax = (dax or "").strip()
    question = (question or "").strip() or None
    if not title:
        raise BookmarkError("書籤標題不可為空")
    if not dax:
        raise BookmarkError("DAX 不可為空")
    if len(title) > MAX_TITLE_CHARS:
        raise BookmarkError(f"書籤標題最多 {MAX_TITLE_CHARS} 字")
    if len(dax) > MAX_DAX_CHARS:
        raise BookmarkError(f"DAX 最多 {MAX_DAX_CHARS} 字")
    if question and len(question) > MAX_QUESTION_CHARS:
        raise BookmarkError(f"原始問題最多 {MAX_QUESTION_CHARS} 字")
    return title, dax, question


def save_bookmark(
    db: Session,
    user_id: str,
    pbi_config_id: str,
    title: str,
    dax: str,
    question: str | None = None,
    overwrite: bool = False,
    model_version: int | None = None,
) -> tuple[str, Bookmark]:
    """回傳 (status, bookmark)。status：
    - "created"：新增
    - "overwritten"：同名書籤已存在且 overwrite=True，已覆蓋
    - "conflict"：同名書籤已存在但 overwrite=False，什麼都沒改，回傳的是既有那筆

    model_version 留空代表「存檔當下 MCP 提供的版本」；匯入時會帶匯出檔裡的版本，讓別人
    分享來的舊書籤仍然能被正確標成可能過時。
    """
    configs = _accessible_configs(db, user_id)
    if pbi_config_id not in configs:
        raise BookmarkError("無此 PBI 設定的存取權")
    title, dax, question = _validate(title, dax, question)
    if model_version is None:
        model_version = serving_model_version(db, pbi_config_id)

    existing = db.query(Bookmark).filter(
        Bookmark.user_id == user_id,
        Bookmark.pbi_config_id == pbi_config_id,
        Bookmark.title == title,
    ).first()
    if existing:
        if not overwrite:
            return "conflict", existing
        existing.dax = dax
        existing.question = question
        existing.model_version = model_version
        existing.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(existing)
        return "overwritten", existing

    count = db.query(Bookmark).filter(Bookmark.user_id == user_id).count()
    if count >= MAX_BOOKMARKS_PER_USER:
        raise BookmarkError(f"書籤已達上限 {MAX_BOOKMARKS_PER_USER} 筆，請先刪除不需要的書籤")
    bookmark = Bookmark(
        user_id=user_id,
        pbi_config_id=pbi_config_id,
        title=title,
        dax=dax,
        question=question,
        model_version=model_version,
    )
    db.add(bookmark)
    db.commit()
    db.refresh(bookmark)
    return "created", bookmark


def delete_bookmark(db: Session, user_id: str, bookmark_id: str) -> bool:
    bookmark = db.query(Bookmark).filter(Bookmark.id == bookmark_id, Bookmark.user_id == user_id).first()
    if not bookmark:
        return False
    db.delete(bookmark)
    db.commit()
    return True


def export_bookmarks(db: Session, user_id: str) -> dict:
    """匯出檔不含 id／時間戳記這類只對本人本機有意義的欄位，方便分享給別人匯入。
    pbi_config_name 只是給人看的，匯入時以 pbi_config_id 為準。"""
    return {
        "format": EXPORT_FORMAT,
        "version": EXPORT_VERSION,
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "bookmarks": [
            {
                "pbi_config_id": b["pbi_config_id"],
                "pbi_config_name": b["pbi_config_name"],
                "title": b["title"],
                "dax": b["dax"],
                "question": b["question"],
                "model_version": b["model_version"],
            }
            for b in list_bookmarks(db, user_id)
        ],
    }


def import_bookmarks(db: Session, user_id: str, data: dict, on_conflict: str = "skip") -> dict:
    """匯入別人分享或自己先前匯出的書籤檔。on_conflict：同名時 "skip"（略過）或
    "overwrite"（覆蓋）。沒有存取權的模型、格式錯誤的單筆都不會讓整批失敗，
    而是逐筆記在結果裡回報，讓使用者知道哪些沒匯進來、為什麼。"""
    if on_conflict not in ("skip", "overwrite"):
        raise BookmarkError("on_conflict 只能是 skip 或 overwrite")
    if not isinstance(data, dict) or data.get("format") != EXPORT_FORMAT:
        raise BookmarkError("不是書籤匯出檔（format 欄位不符）")
    if data.get("version") != EXPORT_VERSION:
        raise BookmarkError(f"不支援的書籤檔版本：{data.get('version')}")
    items = data.get("bookmarks")
    if not isinstance(items, list):
        raise BookmarkError("書籤檔格式錯誤：缺少 bookmarks 陣列")

    result = {"created": 0, "overwritten": 0, "skipped": [], "failed": []}
    for item in items:
        if not isinstance(item, dict):
            result["failed"].append({"title": None, "reason": "格式錯誤"})
            continue
        title = item.get("title")
        model_version = item.get("model_version")
        try:
            status, _ = save_bookmark(
                db,
                user_id,
                pbi_config_id=str(item.get("pbi_config_id") or ""),
                title=str(title or ""),
                dax=str(item.get("dax") or ""),
                question=item.get("question"),
                overwrite=(on_conflict == "overwrite"),
                model_version=model_version if isinstance(model_version, int) else None,
            )
        except BookmarkError as e:
            name = item.get("pbi_config_name")
            reason = str(e)
            if reason == "無此 PBI 設定的存取權" and name:
                reason = f"你沒有「{name}」這個模型的存取權"
            result["failed"].append({"title": title, "reason": reason})
            continue
        if status == "conflict":
            result["skipped"].append({"title": title, "reason": "已有同名書籤"})
        else:
            result[status] += 1
    return result

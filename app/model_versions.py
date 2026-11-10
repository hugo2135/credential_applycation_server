"""語意模型版本的共用邏輯：版本號配發、「目前提供哪一版」、刪除表／欄位／量值另存新版本。

**同一個版本號的內容永遠不變**是整套設計的前提：get_model_detail 的快取 key 是
(pbi_config_id, model_version)，書籤用版本號判斷 DAX 是否可能過時。所以：
- 版本號只增不減，刪掉的號碼不再使用（allocate_model_version）。
- 刪除表／欄位／量值不修改原版本，而是另存成新版本（apply_removal）。

DAX 引用分析（dax_references／find_broken_measures）是啟發式的：只抓直接寫出名稱的
引用，用來在刪除前提醒管理員，不是 DAX parser。前端 admin-frontend/src/components/pbi/
modelDeps.ts 有同一套邏輯做即時預覽，這裡是存檔時的最後檢查，兩邊規則要一致。
"""

import re

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import ModelChunk, PbiConfig


def allocate_model_version(db: Session, config: PbiConfig) -> int:
    # 取計數欄位與現存最大版本的較大者：v1.6 之前建立的設定沒有計數值，靠現存版本補上
    current_max = (
        db.query(func.max(ModelChunk.model_version))
        .filter(ModelChunk.pbi_config_id == config.id)
        .scalar()
    )
    next_version = max(config.last_model_version or 0, current_max or 0) + 1
    config.last_model_version = next_version
    return next_version


def serving_model_version(db: Session, pbi_config_id: str) -> int | None:
    """MCP／legacy API 實際提供的版本號：有指定且該版本還在就用指定的，否則用最新版。
    只 select 版本號欄位，不讀 relationships/tables 這兩個大 JSON。"""
    pinned = db.query(PbiConfig.active_model_version).filter(PbiConfig.id == pbi_config_id).scalar()
    if pinned is not None:
        exists = db.query(ModelChunk.id).filter(
            ModelChunk.pbi_config_id == pbi_config_id,
            ModelChunk.model_version == pinned,
        ).first()
        # 指定的版本理論上刪不掉（delete 端點會擋），找不到時退回最新版而不是讓 MCP 報錯
        if exists:
            return pinned
    row = (
        db.query(ModelChunk.model_version)
        .filter(ModelChunk.pbi_config_id == pbi_config_id)
        .order_by(ModelChunk.model_version.desc())
        .first()
    )
    return row[0] if row else None


def serving_chunk(db: Session, pbi_config_id: str) -> ModelChunk | None:
    version = serving_model_version(db, pbi_config_id)
    if version is None:
        return None
    return db.query(ModelChunk).filter(
        ModelChunk.pbi_config_id == pbi_config_id,
        ModelChunk.model_version == version,
    ).first()


# ── DAX 引用分析 ────────────────────────────────────────────────────────────

# 先把註解和字串整段吃掉，裡面出現的表名不算引用（例如 "Returns"、// 排除 Returns）
_TOKEN_RE = re.compile(
    r"""
      (?P<comment>//[^\n]*|--[^\n]*|/\*.*?\*/)
    | (?P<string>"(?:[^"]|"")*")
    | (?P<quoted>'(?:[^']|'')*')
    | (?P<bracket>\[(?:[^\]]|\]\])*\])
    | (?P<ident>[^\W\d]\w*)
    | (?P<other>\S)
    """,
    re.S | re.X,
)


def _tokens(expr: str) -> list[tuple[str, str]]:
    out = []
    for m in _TOKEN_RE.finditer(expr or ""):
        kind = m.lastgroup
        text = m.group()
        if kind in ("comment", "string"):
            continue
        if kind == "quoted":
            text = text[1:-1].replace("''", "'")
        elif kind == "bracket":
            text = text[1:-1].replace("]]", "]")
        out.append((kind, text))
    return out


def dax_references(expr: str, table_names: set[str]) -> dict:
    """回傳 {"tables": {表}, "qualified": {(表, 名稱)}, "unqualified": {名稱}}，一律小寫
    （DAX 名稱不分大小寫）。table_names 是模型裡所有表名（小寫），用來判斷沒加引號的
    識別字是不是表名——函式名稱、VAR 變數也是識別字，不在表名清單裡的一律忽略。"""
    toks = _tokens(expr)
    tables: set[str] = set()
    qualified: set[tuple[str, str]] = set()
    unqualified: set[str] = set()
    for i, (kind, text) in enumerate(toks):
        nxt = toks[i + 1] if i + 1 < len(toks) else None
        if kind in ("quoted", "ident"):
            name = text.lower()
            # 後面接左括號的是函式呼叫，例如 DATE(2024,1,1) 不是引用名為 Date 的表
            if kind == "ident" and nxt == ("other", "("):
                continue
            if kind == "ident" and name not in table_names:
                continue
            tables.add(name)
            if nxt and nxt[0] == "bracket":
                qualified.add((name, nxt[1].lower()))
        elif kind == "bracket":
            prev = toks[i - 1] if i > 0 else None
            if prev and prev[0] in ("quoted", "ident") and prev[1].lower() in tables:
                continue  # 已經算在 qualified 裡
            unqualified.add(text.lower())
    return {"tables": tables, "qualified": qualified, "unqualified": unqualified}


def _lower_pairs(items: list[tuple[str, str]]) -> set[tuple[str, str]]:
    return {(a.lower(), b.lower()) for a, b in items}


def find_broken_measures(
    tables: list[dict],
    removed_tables: list[str],
    removed_columns: list[tuple[str, str]],
    removed_measures: list[tuple[str, str]],
) -> list[dict]:
    """找出刪除後仍保留、但運算式引用到被刪除項目的量值。被刪除的表裡的量值、欄位
    視同一起刪除。回傳 [{"table", "measure", "reasons": [...]}]。"""
    table_names = {t["table"].lower() for t in tables}
    gone_tables = {t.lower() for t in removed_tables}
    gone_columns = _lower_pairs(removed_columns)
    gone_measures = _lower_pairs(removed_measures)

    measure_home: dict[str, str] = {}  # 量值名稱 → 所在表（DAX 量值名稱整個模型唯一）
    for t in tables:
        for m in t.get("measures", []):
            measure_home[m["measure"].lower()] = t["table"].lower()
    gone_measure_names = {
        name for name, home in measure_home.items()
        if home in gone_tables or (home, name) in gone_measures
    }

    broken = []
    for t in tables:
        tname = t["table"].lower()
        if tname in gone_tables:
            continue
        for m in t.get("measures", []):
            mname = m["measure"].lower()
            if (tname, mname) in gone_measures:
                continue
            refs = dax_references(m.get("expression", ""), table_names)
            reasons: list[str] = []
            for ref_table in sorted(refs["tables"] & gone_tables):
                reasons.append(f"引用了被刪除的表 {ref_table}")
            for ref_table, name in sorted(refs["qualified"]):
                if ref_table in gone_tables:
                    continue
                if (ref_table, name) in gone_columns:
                    reasons.append(f"引用了被刪除的欄位 {ref_table}[{name}]")
                elif name in gone_measure_names:
                    reasons.append(f"引用了被刪除的量值 [{name}]")
            # 沒加表名的 [X]：量值優先；不是量值時，看它是不是自己這張表、或運算式裡
            # 引用到的表裡被刪掉的欄位（迭代函式的 row context，例如 SUMX(Sales, [qty])）
            context_tables = refs["tables"] | {tname}
            for name in sorted(refs["unqualified"]):
                if name in gone_measure_names:
                    reasons.append(f"引用了被刪除的量值 [{name}]")
                elif name not in measure_home and any((ct, name) in gone_columns for ct in context_tables):
                    reasons.append(f"引用了被刪除的欄位 [{name}]")
            if reasons:
                broken.append({"table": t["table"], "measure": m["measure"], "reasons": reasons})
    return broken


def apply_removal(
    relationships: dict,
    tables: list[dict],
    removed_tables: list[str],
    removed_columns: list[tuple[str, str]],
    removed_measures: list[tuple[str, str]],
) -> tuple[dict, list[dict], int]:
    """回傳 (新 relationships, 新 tables, 被連帶刪除的關聯數)。不修改傳入的物件。
    欄位和量值全被刪光的表視同整張刪除（跟 chunk_model.parse_model 丟掉空表的規則一致）。"""
    gone_tables = {t.lower() for t in removed_tables}
    gone_columns = _lower_pairs(removed_columns)
    gone_measures = _lower_pairs(removed_measures)

    new_tables = []
    for t in tables:
        tname = t["table"].lower()
        if tname in gone_tables:
            continue
        columns = [c for c in t.get("columns", []) if (tname, (c.get("column") or "").lower()) not in gone_columns]
        measures = [m for m in t.get("measures", []) if (tname, (m.get("measure") or "").lower()) not in gone_measures]
        if not columns and not measures:
            gone_tables.add(tname)
            continue
        new_tables.append({**t, "columns": columns, "measures": measures})

    def rel_kept(r: dict) -> bool:
        ft, tt = (r.get("fromTable") or "").lower(), (r.get("toTable") or "").lower()
        if ft in gone_tables or tt in gone_tables:
            return False
        if (ft, (r.get("fromColumn") or "").lower()) in gone_columns:
            return False
        if (tt, (r.get("toColumn") or "").lower()) in gone_columns:
            return False
        return True

    old_rels = (relationships or {}).get("relationships", [])
    new_rels = [r for r in old_rels if rel_kept(r)]
    return {**(relationships or {}), "relationships": new_rels}, new_tables, len(old_rels) - len(new_rels)

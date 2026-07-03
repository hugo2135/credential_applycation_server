import json
import os
import re
import shutil
import sys


def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>| ]', '_', name)


def parse_model(data: dict) -> tuple[dict, list]:
    """
    接受原始 PBI JSON 或簡化語意格式，回傳 (relationships_dict, tables_list)。

    支援的外層結構：
      A. root.updatedModel.clientDataModel.dataModel  （Power BI refresh export）
      B. root.clientDataModel.dataModel               （舊版 export）
      C. root（直接是 dataModel，簡化語意格式）
    """
    # 剝掉 updatedModel 外殼（格式 A）
    if "updatedModel" in data:
        data = data["updatedModel"]

    if "clientDataModel" in data:
        data_model = data["clientDataModel"]["dataModel"]
        fmt = "raw"
    else:
        data_model = data
        fmt = "semantic"

    # ── Relationships ─────────────────────────────────────────
    relationships: list = []
    for rel in data_model.get("relationships", []):
        if fmt == "raw":
            from_table = rel.get("fromTableRef", {}).get("name", "")
            to_table   = rel.get("toTableRef",   {}).get("name", "")
            direction_map = {"OneDirection": "Single", "BothDirections": "Both"}
            chunk = {
                "fromTable":            from_table,
                "fromColumn":           rel.get("fromColumnRef", {}).get("name", ""),
                "toTable":              to_table,
                "toColumn":             rel.get("toColumnRef",   {}).get("name", ""),
                "cardinality":          f"{rel.get('fromCardinality','Many')}To{rel.get('toCardinality','One')}",
                "crossFilterDirection": direction_map.get(rel.get("crossFilteringBehavior", "OneDirection"), "Single"),
                "isActive":             rel.get("isActive", True),
            }
        else:
            from_table = rel.get("fromTable", "")
            to_table   = rel.get("toTable",   "")
            chunk = {
                "fromTable":            from_table,
                "fromColumn":           rel.get("fromColumn", ""),
                "toTable":              to_table,
                "toColumn":             rel.get("toColumn", ""),
                "cardinality":          rel.get("cardinality", ""),
                "crossFilterDirection": rel.get("crossFilterDirection", "Single"),
                "isActive":             rel.get("isActive", True),
            }

        if any(n.startswith(("LocalDateTable_", "DateTableTemplate_")) for n in [from_table, to_table]):
            continue
        relationships.append(chunk)

    # ── Tables ────────────────────────────────────────────────
    tables: list = []
    for table in data_model.get("tables", []):
        name = table.get("name", "")
        if name.startswith(("LocalDateTable_", "DateTableTemplate_")):
            continue

        entry = {
            "table":       name,
            "description": table.get("description", ""),
            "columns":     [],
            "measures":    [],
        }
        for col in table.get("columns", []):
            if col.get("columnType") == "RowNumber":
                continue
            entry["columns"].append({
                "column":      col.get("name"),
                "dataType":    col.get("dataType"),
                "description": col.get("description", ""),
            })
        for meas in table.get("measures", []):
            entry["measures"].append({
                "measure":     meas.get("name"),
                "expression":  meas.get("expression", ""),
                "description": meas.get("description", ""),
            })

        if entry["columns"] or entry["measures"]:
            tables.append(entry)

    return {"relationships": relationships}, tables


def _write_to_files(relationships: dict, tables: list, output_dir: str) -> None:
    tables_dir = os.path.join(output_dir, "tables")
    rel_path   = os.path.join(output_dir, "relationships.json")

    if os.path.exists(rel_path):
        os.remove(rel_path)
    if os.path.exists(tables_dir):
        shutil.rmtree(tables_dir)
    os.makedirs(tables_dir)

    with open(rel_path, 'w', encoding='utf-8') as f:
        json.dump(relationships, f, ensure_ascii=False, indent=2)
    print(f"關聯性：{len(relationships['relationships'])} 筆 -> {rel_path}")

    for entry in tables:
        path = os.path.join(tables_dir, f"table_{sanitize_filename(entry['table'])}.json")
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(entry, f, ensure_ascii=False, indent=2)
    print(f"資料表：{len(tables)} 張 -> {tables_dir}/")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

    if len(sys.argv) < 2:
        print("使用方式：python scripts/chunk_model.py <JSON檔案路徑>")
        sys.exit(1)

    input_path = sys.argv[1]
    output_dir = os.path.join(os.getcwd(), "output")

    print(f"輸出目錄：{output_dir}")
    print(f"讀取：{input_path}")

    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            raw_data = json.load(f)
    except FileNotFoundError:
        print(f"找不到檔案：{input_path}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"JSON 格式錯誤：{e}")
        sys.exit(1)

    _top = raw_data.get("updatedModel", raw_data)
    print(f"格式：{'原始 Power BI' if 'clientDataModel' in _top else '簡化語意模型'}")
    relationships, tables = parse_model(raw_data)
    _write_to_files(relationships, tables, output_dir)
    print("完成")

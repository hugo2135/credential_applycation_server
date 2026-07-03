import json
import os
import re
import shutil
import sys

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')


def sanitize_filename(name):
    return re.sub(r'[\\/*?:"<>| ]', '_', name)


def process_and_chunk_model(input_json_path):
    output_dir = os.path.join(os.getcwd(), "output")
    tables_dir = os.path.join(output_dir, "tables")
    rel_path   = os.path.join(output_dir, "relationships.json")

    # 清除上次結果
    if os.path.exists(rel_path):
        os.remove(rel_path)
    if os.path.exists(tables_dir):
        shutil.rmtree(tables_dir)
    os.makedirs(tables_dir)

    print(f"輸出目錄：{output_dir}")
    print(f"讀取：{input_json_path}")

    try:
        with open(input_json_path, 'r', encoding='utf-8') as f:
            raw_data = json.load(f)
    except FileNotFoundError:
        print(f"找不到檔案：{input_json_path}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"JSON 格式錯誤：{e}")
        sys.exit(1)

    if "clientDataModel" in raw_data:
        data_model = raw_data["clientDataModel"]["dataModel"]
        fmt = "raw"
    else:
        data_model = raw_data
        fmt = "semantic"

    print(f"格式：{'原始 Power BI' if fmt == 'raw' else '簡化語意模型'}")

    # ── Relationships ─────────────────────────────────────────
    relationships_output = {"relationships": []}

    for rel in data_model.get("relationships", []):
        if fmt == "raw":
            from_table = rel.get("fromTableRef", {}).get("name", "")
            to_table   = rel.get("toTableRef",   {}).get("name", "")
            direction_map = {"OneDirection": "Single", "BothDirections": "Both"}
            rel_chunk = {
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
            rel_chunk = {
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
        relationships_output["relationships"].append(rel_chunk)

    with open(rel_path, 'w', encoding='utf-8') as f:
        json.dump(relationships_output, f, ensure_ascii=False, indent=2)
    print(f"關聯性：{len(relationships_output['relationships'])} 筆 -> {rel_path}")

    # ── Tables ────────────────────────────────────────────────
    table_count = 0
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
            path = os.path.join(tables_dir, f"table_{sanitize_filename(name)}.json")
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(entry, f, ensure_ascii=False, indent=2)
            table_count += 1

    print(f"資料表：{table_count} 張 -> {tables_dir}/")
    print("完成")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("使用方式：python scripts/chunk_model.py <JSON檔案路徑>")
        sys.exit(1)
    process_and_chunk_model(sys.argv[1])

// 「刪除項目並另存新版本」畫面的 DAX 引用分析，規則跟後端 app/model_versions.py 一致：
// 這裡負責勾選時的即時預覽，後端在存檔時再檢查一次。只抓直接寫出名稱的引用，是啟發式，
// 不是 DAX parser。DAX 名稱不分大小寫，比對一律轉小寫。

export interface ModelColumn {
  column: string
  dataType?: string
  description?: string
}
export interface ModelMeasure {
  measure: string
  expression?: string
  description?: string
}
export interface ModelTable {
  table: string
  description?: string
  columns: ModelColumn[]
  measures: ModelMeasure[]
}
export interface ModelRelationship {
  fromTable: string
  fromColumn: string
  toTable: string
  toColumn: string
  cardinality?: string
  isActive?: boolean
}

export interface DaxRefs {
  tables: Set<string>
  /** pairKey(表, 名稱)：可能是欄位，也可能是加了表名的量值 */
  qualified: Set<string>
  unqualified: Set<string>
}

const lower = (s: string | null | undefined) => (s ?? '').toLowerCase()
export const pairKey = (table: string, name: string) => `${lower(table)}\u0000${lower(name)}`
export function splitKey(key: string): [string, string] {
  const i = key.indexOf('\u0000')
  return [key.slice(0, i), key.slice(i + 1)]
}

// 先把註解和字串整段吃掉，裡面出現的表名不算引用
const TOKEN_RE =
  /(\/\/[^\n]*|--[^\n]*|\/\*[\s\S]*?\*\/)|("(?:[^"]|"")*")|('(?:[^']|'')*')|(\[(?:[^\]]|\]\])*\])|([\p{L}_][\p{L}\p{N}_]*)|(\S)/gu

type Token = { kind: 'quoted' | 'bracket' | 'ident' | 'other'; text: string }

function tokens(expr: string): Token[] {
  const out: Token[] = []
  for (const m of expr.matchAll(TOKEN_RE)) {
    if (m[1] || m[2]) continue
    if (m[3]) out.push({ kind: 'quoted', text: m[3].slice(1, -1).replace(/''/g, "'") })
    else if (m[4]) out.push({ kind: 'bracket', text: m[4].slice(1, -1).replace(/\]\]/g, ']') })
    else if (m[5]) out.push({ kind: 'ident', text: m[5] })
    else out.push({ kind: 'other', text: m[6] ?? '' })
  }
  return out
}

export function daxReferences(expr: string | undefined, tableNames: Set<string>): DaxRefs {
  const toks = tokens(expr ?? '')
  const refs: DaxRefs = { tables: new Set(), qualified: new Set(), unqualified: new Set() }
  toks.forEach((tok, i) => {
    const next = toks[i + 1]
    if (tok.kind === 'quoted' || tok.kind === 'ident') {
      const name = lower(tok.text)
      // 後面接左括號的是函式呼叫，例如 DATE(2024,1,1) 不是引用名為 Date 的表
      if (tok.kind === 'ident' && next?.kind === 'other' && next.text === '(') return
      if (tok.kind === 'ident' && !tableNames.has(name)) return
      refs.tables.add(name)
      if (next?.kind === 'bracket') refs.qualified.add(pairKey(name, next.text))
    } else if (tok.kind === 'bracket') {
      const prev = toks[i - 1]
      if (prev && (prev.kind === 'quoted' || prev.kind === 'ident') && refs.tables.has(lower(prev.text))) return
      refs.unqualified.add(lower(tok.text))
    }
  })
  return refs
}

export interface MeasureInfo {
  key: string
  table: string
  measure: string
  expression: string
  refs: DaxRefs
}

/** 一個版本的模型索引：建一次，勾選變動時只重算 analyze()。 */
export class ModelIndex {
  readonly tableNames: Set<string>
  readonly measures = new Map<string, MeasureInfo>()
  /** 量值名稱 → 量值 key（DAX 量值名稱整個模型唯一） */
  readonly measureByName = new Map<string, string>()
  /** 量值 key → 直接引用它的量值 key */
  readonly dependents = new Map<string, Set<string>>()

  constructor(readonly tables: ModelTable[]) {
    this.tableNames = new Set(tables.map((t) => lower(t.table)))
    for (const t of tables) {
      for (const m of t.measures) {
        const key = pairKey(t.table, m.measure)
        this.measureByName.set(lower(m.measure), key)
        this.measures.set(key, {
          key,
          table: t.table,
          measure: m.measure,
          expression: m.expression ?? '',
          refs: daxReferences(m.expression, this.tableNames),
        })
      }
    }
    for (const info of this.measures.values()) {
      for (const target of this.referencedMeasures(info)) {
        if (!this.dependents.has(target)) this.dependents.set(target, new Set())
        this.dependents.get(target)!.add(info.key)
      }
    }
  }

  private referencedMeasures(info: MeasureInfo): string[] {
    const names = [...info.refs.unqualified, ...[...info.refs.qualified].map((k) => splitKey(k)[1])]
    return names.map((n) => this.measureByName.get(n)).filter((k): k is string => !!k && k !== info.key)
  }
}

export interface Removal {
  tables: Set<string> // 小寫表名
  columns: Set<string> // pairKey
  measures: Set<string> // pairKey
}

/** 欄位和量值全被刪光的表視同整張刪除（跟後端 apply_removal 一致）。 */
export function effectiveRemovedTables(index: ModelIndex, removal: Removal): Set<string> {
  const out = new Set(removal.tables)
  for (const t of index.tables) {
    const keepCols = t.columns.some((c) => !removal.columns.has(pairKey(t.table, c.column)))
    const keepMeasures = t.measures.some((m) => !removal.measures.has(pairKey(t.table, m.measure)))
    if (!keepCols && !keepMeasures) out.add(lower(t.table))
  }
  return out
}

export function removedRelationships(
  relationships: ModelRelationship[],
  goneTables: Set<string>,
  goneColumns: Set<string>,
): ModelRelationship[] {
  return relationships.filter(
    (r) =>
      goneTables.has(lower(r.fromTable)) ||
      goneTables.has(lower(r.toTable)) ||
      goneColumns.has(pairKey(r.fromTable, r.fromColumn)) ||
      goneColumns.has(pairKey(r.toTable, r.toColumn)),
  )
}

/**
 * 每個量值（不在被刪除的表裡）引用到哪些被刪除的項目。被勾選刪除的量值也照算，
 * 這樣勾選後它不會從「受影響的量值」清單消失。被刪除的表裡的量值視同刪除。
 */
export function measureReasons(index: ModelIndex, removal: Removal, goneTables: Set<string>): Map<string, string[]> {
  const goneMeasureNames = new Set<string>()
  for (const info of index.measures.values()) {
    if (goneTables.has(lower(info.table)) || removal.measures.has(info.key)) goneMeasureNames.add(lower(info.measure))
  }

  const result = new Map<string, string[]>()
  for (const info of index.measures.values()) {
    const home = lower(info.table)
    if (goneTables.has(home)) continue
    const { refs } = info
    const reasons: string[] = []
    for (const t of [...refs.tables].filter((t) => goneTables.has(t)).sort()) {
      reasons.push(`引用了被刪除的表 ${displayTable(index, t)}`)
    }
    for (const k of [...refs.qualified].sort()) {
      const [t, name] = splitKey(k)
      if (goneTables.has(t)) continue
      if (removal.columns.has(k)) reasons.push(`引用了被刪除的欄位 ${displayTable(index, t)}[${name}]`)
      else if (goneMeasureNames.has(name) && name !== lower(info.measure)) reasons.push(`引用了被刪除的量值 [${name}]`)
    }
    // 沒加表名的 [X]：量值優先；不是量值時，看它是不是自己這張表、或運算式裡引用到的表的
    // 被刪除欄位（迭代函式的 row context，例如 SUMX(Sales, [qty])）
    const contextTables = new Set([...refs.tables, home])
    for (const name of [...refs.unqualified].sort()) {
      if (goneMeasureNames.has(name) && name !== lower(info.measure)) reasons.push(`引用了被刪除的量值 [${name}]`)
      else if (!index.measureByName.has(name) && [...contextTables].some((t) => removal.columns.has(pairKey(t, name)))) {
        reasons.push(`引用了被刪除的欄位 [${name}]`)
      }
    }
    if (reasons.length) result.set(info.key, reasons)
  }
  return result
}

function displayTable(index: ModelIndex, lowerName: string) {
  return index.tables.find((t) => lower(t.table) === lowerName)?.table ?? lowerName
}

/**
 * 連帶勾選：從管理員手動勾選的量值出發，沿著「誰引用了我」往下展開，直接或間接
 * 依賴它的量值都一起刪，除非管理員明確取消過（excluded）。回傳 量值 key → 是因為
 * 引用了哪個量值才被連帶勾選。走過的節點不重走，循環引用不會卡住。
 */
export function cascadeMeasures(index: ModelIndex, manual: Set<string>, excluded: Set<string>): Map<string, string> {
  const autoBy = new Map<string, string>()
  const queue = [...manual]
  const seen = new Set(manual)
  while (queue.length) {
    const key = queue.shift()!
    for (const dep of index.dependents.get(key) ?? []) {
      if (seen.has(dep) || excluded.has(dep)) continue
      seen.add(dep)
      autoBy.set(dep, key)
      queue.push(dep)
    }
  }
  return autoBy
}

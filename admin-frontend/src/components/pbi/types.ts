// 這些型別的欄位名稱就是存進 DB、透過 get_model_detail 交給 skill 的 JSON key，
// 屬於對外契約，畫面上的中文名稱可以隨便改，key 本身不能動（見 docs/skill-integration.md）。

export interface FilterRule {
  description: string
  expression: string
  requiredTable?: string | null
}

export interface FilterProfile {
  filterId: string
  name: string
  description?: string | null
  alwaysApply: boolean
  overrideDefaults: boolean
  contextKeywords: string[]
  filters: FilterRule[]
}

export interface QueryMode {
  mode_id: string
  name: string
  description?: string | null
  tables: string[]
  filters: FilterRule[]
}

export interface ColumnValueAlias {
  value: string
  aliases: string[]
}

export interface ColumnAliasGroup {
  table: string
  column: string
  values: ColumnValueAlias[]
}

export interface SchemaTable {
  table: string
  columns: string[]
}

// 折疊面板要一個穩定的 key 記住哪張卡片展開：不能用陣列索引（刪掉中間一筆後面全部位移），
// 也不能用 filterId 這類使用者可改的欄位，所以替每個物件另外配一個只存在前端記憶體的 id。
const itemKeys = new WeakMap<object, string>()
let keySeq = 0
export function itemKey(item: object) {
  let key = itemKeys.get(item)
  if (!key) itemKeys.set(item, (key = `item-${++keySeq}`))
  return key
}

export function newId(prefix: string) {
  return `${prefix}-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`
}

// 後端存的資料可能是手寫 JSON 進去的，欄位不一定齊，進表單前補上預設值，
// 避免 v-model 綁到 undefined 的陣列。
export function normalizeRule(r: Partial<FilterRule>): FilterRule {
  return { description: r.description ?? '', expression: r.expression ?? '', requiredTable: r.requiredTable ?? null }
}

export function normalizeProfile(p: Partial<FilterProfile>): FilterProfile {
  return {
    filterId: p.filterId || newId('filter'),
    name: p.name ?? '',
    description: p.description ?? '',
    alwaysApply: p.alwaysApply ?? false,
    overrideDefaults: p.overrideDefaults ?? false,
    contextKeywords: p.contextKeywords ?? [],
    filters: (p.filters ?? []).map(normalizeRule),
  }
}

export function normalizeMode(m: Partial<QueryMode>): QueryMode {
  return {
    mode_id: m.mode_id || newId('mode'),
    name: m.name ?? '',
    description: m.description ?? '',
    tables: m.tables ?? [],
    filters: (m.filters ?? []).map(normalizeRule),
  }
}

export function normalizeAliasGroup(g: Partial<ColumnAliasGroup>): ColumnAliasGroup {
  return {
    table: g.table ?? '',
    column: g.column ?? '',
    values: (g.values ?? []).map((v) => ({ value: v.value ?? '', aliases: v.aliases ?? [] })),
  }
}

// 存檔前清掉空字串的選填欄位，讓存進去的 JSON 跟以前手寫的長得一樣乾淨。
export function cleanRule(r: FilterRule): FilterRule {
  const out: FilterRule = { description: r.description.trim(), expression: r.expression.trim() }
  if (r.requiredTable) out.requiredTable = r.requiredTable
  return out
}

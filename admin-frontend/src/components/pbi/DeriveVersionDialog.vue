<template>
  <el-dialog
    v-model="visible"
    :title="`從版本 ${sourceVersion} 刪除資料表／欄位／量值`"
    width="min(1200px, 96vw)"
    top="4vh"
    destroy-on-close
    @open="load"
  >
    <div v-loading="loading" class="derive">
      <el-alert type="info" :closable="false" show-icon style="margin-bottom: 12px">
        <template #title>
          勾選要讓 AI 看不到的項目，儲存後會<b>另存成新版本</b>，版本 {{ sourceVersion }} 本身不會被修改。
          這裡只影響 AI 拿到的模型說明，Power BI 上的資料集不會有任何變動。
        </template>
      </el-alert>

      <el-row v-if="index" :gutter="16">
        <!-- 左：選擇項目 -->
        <el-col :md="11" :span="24">
          <div class="pane-title">選擇要刪除的項目</div>
          <el-input v-model="keyword" placeholder="搜尋資料表、欄位或量值" clearable prefix-icon="Search" />
          <div class="tree">
            <div v-for="t in visibleTables" :key="t.table" class="table-block">
              <div class="table-row" :class="{ removed: tableRemoved(t) }">
                <el-icon class="caret" :class="{ open: isOpen(t) }" @click="toggleOpen(t)"><ArrowRight /></el-icon>
                <el-checkbox
                  :model-value="tableRemoved(t)"
                  :indeterminate="!tableRemoved(t) && tablePartial(t)"
                  @change="(v: string | number | boolean) => setTable(t, Boolean(v))"
                />
                <span class="table-name" @click="toggleOpen(t)">{{ t.table }}</span>
                <span class="meta">{{ t.columns.length }} 欄位・{{ t.measures.length }} 量值</span>
              </div>
              <div v-if="isOpen(t)" class="children">
                <template v-if="shownColumns(t).length">
                  <div class="group-label">欄位</div>
                  <div v-for="c in shownColumns(t)" :key="c.column" class="child-row">
                    <el-checkbox
                      :model-value="tableRemoved(t) || removedColumns.has(pairKey(t.table, c.column))"
                      :disabled="tableRemoved(t)"
                      @change="(v: string | number | boolean) => setColumn(t, c.column, Boolean(v))"
                    >
                      {{ c.column }}
                    </el-checkbox>
                    <span class="meta">{{ c.dataType }}</span>
                  </div>
                </template>
                <template v-if="shownMeasures(t).length">
                  <div class="group-label">量值</div>
                  <div v-for="m in shownMeasures(t)" :key="m.measure" class="child-row">
                    <el-checkbox
                      :model-value="tableRemoved(t) || removedMeasures.has(pairKey(t.table, m.measure))"
                      :disabled="tableRemoved(t)"
                      @change="(v: string | number | boolean) => setMeasure(pairKey(t.table, m.measure), Boolean(v))"
                    >
                      {{ m.measure }}
                    </el-checkbox>
                    <el-tag v-if="!tableRemoved(t) && autoBy.has(pairKey(t.table, m.measure))" size="small" type="warning">
                      連帶
                    </el-tag>
                  </div>
                </template>
              </div>
            </div>
            <el-empty v-if="!visibleTables.length" :image-size="60" description="沒有符合的項目" />
          </div>
        </el-col>

        <!-- 右：影響 -->
        <el-col :md="13" :span="24">
          <div class="pane-title">刪除後的影響</div>
          <el-empty v-if="nothingSelected" :image-size="60" description="從左邊勾選要刪除的項目" />
          <template v-else>
            <div class="summary">
              將刪除
              <b>{{ summary.tables }}</b> 張表、<b>{{ summary.columns }}</b> 個欄位、<b>{{ summary.measures }}</b> 個量值
            </div>

            <el-collapse v-if="goneRelationships.length" class="rels">
              <el-collapse-item :title="`連帶刪除的關聯：${goneRelationships.length} 筆（自動，不用選）`">
                <div v-for="(r, i) in goneRelationships" :key="i" class="rel">
                  {{ r.fromTable }}[{{ r.fromColumn }}] → {{ r.toTable }}[{{ r.toColumn }}]
                </div>
              </el-collapse-item>
            </el-collapse>

            <div v-if="affected.length" class="section">
              <div class="section-head">
                <span class="sub-label">引用到被刪除項目的量值（{{ affected.length }}）</span>
                <span>
                  <el-button size="small" link type="danger" @click="setAllAffected(true)">全部一併刪除</el-button>
                  <el-button size="small" link @click="setAllAffected(false)">全部保留</el-button>
                </span>
              </div>
              <div class="hint" style="margin: 0 0 8px">
                勾選 = 一併刪除。保留也可以：Power BI 上量值照樣算得出來，只是 AI 會看到它引用了不存在的項目。
                勾選某個量值時，直接或間接引用它的量值會<b>連帶勾選</b>。
              </div>
              <div v-for="row in affected" :key="row.key" class="affected-row" :class="{ keep: !row.checked }">
                <el-checkbox :model-value="row.checked" @change="(v: string | number | boolean) => setMeasure(row.key, Boolean(v))" />
                <div class="affected-body">
                  <div>
                    <span class="measure-name">{{ row.table }}[{{ row.measure }}]</span>
                    <el-tag v-if="row.autoFrom" size="small" type="warning" style="margin-left: 6px">
                      連帶：因為引用 [{{ row.autoFrom }}]
                    </el-tag>
                    <el-tag v-else-if="!row.checked" size="small" type="danger" effect="plain" style="margin-left: 6px">
                      保留後會有懸空引用
                    </el-tag>
                  </div>
                  <div class="reasons">{{ row.reasons.join('；') }}</div>
                </div>
              </div>
            </div>

            <el-alert v-if="configRefs.length" type="warning" :closable="false" show-icon class="section">
              <template #title>PBI 設定中引用到這些項目的地方（這裡不會修改，儲存後請到對應分頁調整）</template>
              <div v-for="(r, i) in configRefs" :key="i">・{{ r.where }}「{{ r.name }}」：{{ r.detail }}</div>
            </el-alert>
          </template>
        </el-col>
      </el-row>
    </div>

    <template #footer>
      <div class="footer">
        <el-input v-model="name" :placeholder="`新版本名稱（預設：由版本 ${sourceVersion} 刪除部分項目）`" clearable class="name-input" />
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" :disabled="nothingSelected" :loading="saving" @click="save(false)">另存為新版本</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, h, reactive, ref, shallowRef } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api/http'
import {
  ModelIndex,
  cascadeMeasures,
  daxReferences,
  effectiveRemovedTables,
  measureReasons,
  pairKey,
  removedRelationships,
  splitKey,
  type ModelRelationship,
  type ModelTable,
} from './modelDeps'

interface ConfigLike {
  filters: any[]
  query_modes: any[]
  column_aliases: any[]
}

const props = defineProps<{ chunkId: string; sourceVersion: number; config: ConfigLike | null }>()
const emit = defineEmits<{ saved: [result: { model_version: number; serving_model_version: number | null }] }>()
const visible = defineModel<boolean>({ required: true })

const loading = ref(false)
const saving = ref(false)
const index = shallowRef<ModelIndex | null>(null)
const relationships = shallowRef<ModelRelationship[]>([])
const keyword = ref('')
const name = ref('')
const openTables = reactive(new Set<string>())

// 勾選狀態：表與欄位就是勾什麼刪什麼；量值分「手動勾的」與「被取消的連帶項目」，
// 實際要刪的量值 = 手動 ∪ 連帶（cascadeMeasures 算），所以取消某個手動項目時，
// 只因為它才被連帶的量值會自動消失，其他手動勾的不受影響。
const removedTables = reactive(new Set<string>()) // 小寫表名
const removedColumns = reactive(new Set<string>()) // pairKey
const manualMeasures = reactive(new Set<string>())
const excludedMeasures = reactive(new Set<string>())

const lower = (s: string) => s.toLowerCase()

async function load() {
  loading.value = true
  index.value = null
  keyword.value = ''
  name.value = ''
  for (const s of [openTables, removedTables, removedColumns, manualMeasures, excludedMeasures]) s.clear()
  try {
    const { data } = await http.get(`/model/versions/${props.chunkId}/content`)
    index.value = new ModelIndex(
      (data.tables as ModelTable[]).map((t) => ({ ...t, columns: t.columns ?? [], measures: t.measures ?? [] })),
    )
    relationships.value = data.relationships
  } catch {
    ElMessage.error('載入版本內容失敗')
    visible.value = false
  } finally {
    loading.value = false
  }
}

// ── 左側清單 ───────────────────────────────────────────────────────

const kw = computed(() => lower(keyword.value.trim()))
const hit = (s: string) => lower(s).includes(kw.value)

const visibleTables = computed(() => {
  const tables = index.value?.tables ?? []
  if (!kw.value) return tables
  return tables.filter((t) => hit(t.table) || t.columns.some((c) => hit(c.column)) || t.measures.some((m) => hit(m.measure)))
})

function shownColumns(t: ModelTable) {
  return !kw.value || hit(t.table) ? t.columns : t.columns.filter((c) => hit(c.column))
}
function shownMeasures(t: ModelTable) {
  return !kw.value || hit(t.table) ? t.measures : t.measures.filter((m) => hit(m.measure))
}

// 搜尋到的是欄位或量值時自動展開那張表，不然使用者看不到符合的項目在哪
function isOpen(t: ModelTable) {
  return openTables.has(t.table) || (!!kw.value && !hit(t.table))
}
function toggleOpen(t: ModelTable) {
  if (openTables.has(t.table)) openTables.delete(t.table)
  else openTables.add(t.table)
}

function tableRemoved(t: ModelTable) {
  return removedTables.has(lower(t.table))
}
function tablePartial(t: ModelTable) {
  return (
    t.columns.some((c) => removedColumns.has(pairKey(t.table, c.column))) ||
    t.measures.some((m) => removedMeasures.value.has(pairKey(t.table, m.measure)))
  )
}

function setTable(t: ModelTable, on: boolean) {
  if (on) {
    removedTables.add(lower(t.table))
    // 整張表刪掉就涵蓋了裡面的欄位與量值，清掉個別勾選，取消整表時才不會殘留
    for (const c of t.columns) removedColumns.delete(pairKey(t.table, c.column))
    for (const m of t.measures) manualMeasures.delete(pairKey(t.table, m.measure))
  } else {
    removedTables.delete(lower(t.table))
  }
}

function setColumn(t: ModelTable, column: string, on: boolean) {
  const key = pairKey(t.table, column)
  if (on) removedColumns.add(key)
  else removedColumns.delete(key)
}

function setMeasure(key: string, on: boolean) {
  if (on) {
    const before = autoBy.value.size
    excludedMeasures.delete(key)
    manualMeasures.add(key)
    const added = autoBy.value.size - before
    if (added > 0) ElMessage.info(`連帶勾選了 ${added} 個依賴它的量值`)
  } else if (manualMeasures.has(key)) {
    manualMeasures.delete(key)
  } else {
    // 取消的是連帶勾選的項目：記下來，之後重算時不再把它連帶進來
    excludedMeasures.add(key)
  }
}

// ── 影響分析 ───────────────────────────────────────────────────────

const autoBy = computed(() =>
  index.value ? cascadeMeasures(index.value, manualMeasures, excludedMeasures) : new Map<string, string>(),
)
const removedMeasures = computed(() => new Set([...manualMeasures, ...autoBy.value.keys()]))
const removal = computed(() => ({ tables: removedTables, columns: removedColumns, measures: removedMeasures.value }))
const goneTables = computed(() => (index.value ? effectiveRemovedTables(index.value, removal.value) : new Set<string>()))

const nothingSelected = computed(() => !removedTables.size && !removedColumns.size && !removedMeasures.value.size)

const summary = computed(() => {
  const gone = goneTables.value
  const tableOf = (key: string) => splitKey(key)[0]
  return {
    tables: gone.size,
    columns: [...removedColumns].filter((k) => !gone.has(tableOf(k))).length,
    measures: [...removedMeasures.value].filter((k) => !gone.has(tableOf(k))).length,
  }
})

const goneRelationships = computed(() => removedRelationships(relationships.value, goneTables.value, removedColumns))

const affected = computed(() => {
  if (!index.value) return []
  const reasons = measureReasons(index.value, removal.value, goneTables.value)
  return [...reasons.entries()].map(([key, rs]) => {
    const info = index.value!.measures.get(key)!
    const from = autoBy.value.get(key)
    return {
      key,
      table: info.table,
      measure: info.measure,
      reasons: rs,
      checked: removedMeasures.value.has(key),
      autoFrom: from ? index.value!.measures.get(from)?.measure : undefined,
    }
  })
})

function setAllAffected(on: boolean) {
  for (const row of affected.value) {
    if (on) {
      excludedMeasures.delete(row.key)
      manualMeasures.add(row.key)
    } else {
      manualMeasures.delete(row.key)
      excludedMeasures.add(row.key)
    }
  }
}

// PBI 設定屬於設定本身、不屬於某個版本，這裡只提醒不修改（理由：指定了提供版本時，
// 改設定會立刻影響線上那一版）
const configRefs = computed(() => {
  const cfg = props.config
  if (!cfg || !index.value) return []
  const gone = goneTables.value
  const cols = removedColumns
  const tableNames = index.value.tableNames
  const out: { where: string; name: string; detail: string }[] = []

  const ruleHits = (rules: any[]) => {
    const hits = new Set<string>()
    for (const r of rules ?? []) {
      if (r.requiredTable && gone.has(lower(r.requiredTable))) hits.add(`需要的資料表 ${r.requiredTable}`)
      const refs = daxReferences(r.expression, tableNames)
      for (const t of refs.tables) if (gone.has(t)) hits.add(`運算式引用 ${t}`)
      for (const k of refs.qualified) if (cols.has(k)) hits.add(`運算式引用 ${k.replace('\u0000', '[')}]`)
    }
    return [...hits]
  }

  for (const p of cfg.filters ?? []) {
    const hits = ruleHits(p.filters)
    if (hits.length) out.push({ where: '篩選規則', name: p.name, detail: hits.join('、') })
  }
  for (const m of cfg.query_modes ?? []) {
    const hits = [
      ...(m.tables ?? []).filter((t: string) => gone.has(lower(t))).map((t: string) => `可查詢的表包含 ${t}`),
      ...ruleHits(m.filters),
    ]
    if (hits.length) out.push({ where: '查詢模式', name: m.name, detail: hits.join('、') })
  }
  for (const g of cfg.column_aliases ?? []) {
    if (gone.has(lower(g.table ?? '')) || cols.has(pairKey(g.table ?? '', g.column ?? ''))) {
      out.push({ where: '篩選欄位別名', name: `${g.table}[${g.column}]`, detail: '這個欄位將被刪除' })
    }
  }
  return out
})

// ── 儲存 ───────────────────────────────────────────────────────────

function payload(allowDangling: boolean) {
  const idx = index.value!
  const gone = removedTables
  const original = (lowerName: string) => idx.tables.find((t) => lower(t.table) === lowerName)!.table
  const split = splitKey
  const findCol = (t: string, c: string) => {
    const table = idx.tables.find((x) => lower(x.table) === t)!
    return { table: table.table, column: table.columns.find((x) => lower(x.column) === c)!.column }
  }
  return {
    remove_tables: [...gone].map(original),
    remove_columns: [...removedColumns].map(split).filter(([t]) => !gone.has(t)).map(([t, c]) => findCol(t, c)),
    remove_measures: [...removedMeasures.value]
      .filter((k) => !gone.has(split(k)[0]))
      .map((k) => {
        const info = idx.measures.get(k)!
        return { table: info.table, measure: info.measure }
      }),
    name: name.value.trim() || null,
    allow_dangling: allowDangling,
  }
}

async function confirmDangling(rows: { table: string; measure: string; reasons: string[] }[]) {
  await ElMessageBox.confirm(
    h('div', [
      h('p', { style: 'margin: 0 0 8px' }, `有 ${rows.length} 個保留的量值仍引用被刪除的項目：`),
      ...rows.map((r) => h('div', { style: 'font-size: 13px' }, `・${r.table}[${r.measure}]：${r.reasons.join('；')}`)),
      h('p', { style: 'margin: 8px 0 0; font-size: 12px; color: var(--el-text-color-secondary)' },
        'Power BI 上這些量值照樣算得出來，只是 AI 會看到它們引用了不存在的項目。'),
    ]),
    '確認保留這些量值？',
    { confirmButtonText: '仍要儲存', cancelButtonText: '返回修改', type: 'warning' },
  )
}

async function save(allowDangling: boolean) {
  if (!allowDangling) {
    const dangling = affected.value.filter((r) => !r.checked)
    if (dangling.length) {
      try {
        await confirmDangling(dangling)
      } catch {
        return
      }
      allowDangling = true
    }
  }
  saving.value = true
  try {
    const { data } = await http.post(`/model/versions/${props.chunkId}/derive`, payload(allowDangling))
    if (data.serving_model_version === data.model_version) {
      ElMessage.success(`已另存為版本 ${data.model_version}，MCP 已改提供這一版（設定為跟隨最新版）`)
    } else {
      ElMessage({
        type: 'success',
        duration: 6000,
        message: `已另存為版本 ${data.model_version}。MCP 目前仍提供版本 ${data.serving_model_version}，確認無誤後可在版本列表切換。`,
      })
    }
    visible.value = false
    emit('saved', data)
  } catch (e: any) {
    const detail = e.response?.data?.detail
    // 前端的分析漏掉、後端多抓到懸空引用時，讓管理員看過再決定
    if (e.response?.status === 409 && detail?.dangling) {
      saving.value = false
      try {
        await confirmDangling(detail.dangling)
      } catch {
        return
      }
      return save(true)
    }
    ElMessage.error(typeof detail === 'string' ? detail : '儲存失敗')
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
@import './editor.css';

.pane-title {
  font-weight: 600;
  margin-bottom: 8px;
}
.tree {
  margin-top: 8px;
  max-height: 60vh;
  overflow-y: auto;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 4px;
  padding: 4px 0;
}
.table-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 2px 8px;
}
.table-row:hover {
  background: var(--el-fill-color-light);
}
.table-row.removed .table-name {
  text-decoration: line-through;
  color: var(--el-text-color-secondary);
}
.caret {
  cursor: pointer;
  transition: transform 0.15s;
  color: var(--el-text-color-secondary);
}
.caret.open {
  transform: rotate(90deg);
}
.table-name {
  cursor: pointer;
  font-weight: 500;
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.meta {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  white-space: nowrap;
}
.children {
  padding: 0 8px 6px 48px;
}
.group-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-top: 4px;
}
.child-row {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 28px;
}
.child-row :deep(.el-checkbox) {
  height: 28px;
}
.summary {
  margin-bottom: 8px;
}
.rels {
  margin-bottom: 12px;
}
.rel {
  font-size: 13px;
  font-family: monospace;
}
.section {
  margin-top: 12px;
}
.section-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.affected-row {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  padding: 6px 8px;
  border-radius: 4px;
}
.affected-row.keep {
  background: var(--el-color-danger-light-9);
}
.affected-row :deep(.el-checkbox) {
  height: 22px;
}
.affected-body {
  min-width: 0;
}
.measure-name {
  font-weight: 500;
}
.reasons {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.footer {
  display: flex;
  align-items: center;
  gap: 8px;
}
.name-input {
  flex: 1;
  max-width: 420px;
  margin-right: auto;
}
</style>

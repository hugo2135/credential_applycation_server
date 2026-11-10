<template>
  <el-page-header :content="config?.name ?? '載入中…'" @back="router.push('/admin/pbi-configs')" style="margin-bottom: 20px" />

  <el-tabs v-model="activeTab" v-loading="loading">
    <!-- 基本設定 -->
    <el-tab-pane label="基本設定" name="basic">
      <el-form label-width="120px" style="max-width: 480px">
        <el-form-item label="名稱">
          <el-input :model-value="config?.name" disabled />
        </el-form-item>
        <el-form-item label="Workspace ID">
          <el-input v-model="basicForm.workspace_id" placeholder="Power BI Workspace UUID" />
        </el-form-item>
        <el-form-item label="Dataset ID">
          <el-input v-model="basicForm.dataset_id" placeholder="Power BI Dataset UUID" />
        </el-form-item>
      </el-form>
      <el-button type="primary" :loading="basicSaving" @click="saveBasic">儲存</el-button>
    </el-tab-pane>

    <!-- 語意模型版本 -->
    <el-tab-pane label="語意模型版本" name="model">
      <el-row :gutter="16">
        <el-col :span="11">
          <el-card>
            <template #header>上傳新版語意模型</template>
            <el-form label-position="top">
              <el-form-item label="版本名稱（選填）">
                <el-input v-model="uploadName" placeholder="例：2025 Q3 財務模型" clearable />
              </el-form-item>
              <el-form-item label="模型說明（選填）">
                <el-input
                  v-model="uploadDescription"
                  type="textarea"
                  :rows="5"
                  placeholder="以 Markdown 撰寫可查詢資料範圍、資料表用途、重要量值說明等，供 Skill 直接使用"
                />
              </el-form-item>
            </el-form>

            <el-tabs v-model="inputMode" style="margin-top: 4px">
              <el-tab-pane label="上傳檔案" name="file">
                <el-upload
                  drag
                  accept=".json"
                  :auto-upload="false"
                  :limit="1"
                  :on-change="handleFileChange"
                  :on-remove="() => { fileContent = ''; fileName = '' }"
                  :file-list="fileList"
                >
                  <el-icon style="font-size: 48px; color: #c0c4cc"><Upload /></el-icon>
                  <div style="margin-top: 8px; font-size: 14px; color: #606266">
                    拖曳 <b>.json</b> 至此，或<em>點擊選擇</em>
                  </div>
                  <template #tip>
                    <div style="font-size: 12px; color: #909399; margin-top: 4px">
                      支援原始 Power BI 格式（clientDataModel）或簡化語意格式
                    </div>
                  </template>
                </el-upload>
                <div v-if="fileName" style="margin-top: 8px; font-size: 13px; color: #67c23a">
                  ✓ 已選擇：{{ fileName }}
                </div>
              </el-tab-pane>

              <el-tab-pane label="貼上 JSON" name="text">
                <el-input
                  v-model="rawJson"
                  type="textarea"
                  :rows="14"
                  placeholder="貼上原始 PBI JSON（clientDataModel 或簡化語意格式）"
                  style="font-family: monospace; font-size: 12px"
                />
              </el-tab-pane>
            </el-tabs>

            <el-alert v-if="parseError" :title="parseError" type="error" show-icon :closable="false" style="margin-top: 12px" />

            <el-button type="primary" :loading="uploading" style="margin-top: 16px" @click="handleUpload">
              上傳
            </el-button>
          </el-card>
        </el-col>

        <el-col :span="13">
          <el-card>
            <template #header>
              <div class="card-head">
                <span>版本歷史</span>
                <span class="serving">
                  AI 目前拿到：<b>{{ servingVersion ? `版本 ${servingVersion}` : '—' }}</b>
                  <el-switch
                    :model-value="followLatest"
                    active-text="跟隨最新版"
                    :disabled="!versions.length"
                    @change="(on: string | number | boolean) => setServing(on ? null : servingVersion)"
                  />
                </span>
              </div>
              <div class="hint">
                {{ followLatest
                  ? '新上傳或另存的版本會立刻提供給 AI。想先檢查新版本再上線，請關掉「跟隨最新版」。'
                  : '已固定提供上面這一版，新版本不會自動上線；要切換請在該版本的「更多」選「固定提供這一版」。' }}
              </div>
            </template>
            <el-table :data="versions" v-loading="loadingVersions" border row-key="id" @expand-change="handleExpand">
              <el-table-column type="expand">
                <template #default="{ row }">
                  <div style="padding: 8px 16px">
                    <div v-if="!versionDetails[row.id]" style="color: #909399; font-size: 13px">載入中…</div>
                    <template v-else>
                      <div style="font-size: 13px; color: #606266; margin-bottom: 6px">
                        {{ versionDetails[row.id]?.table_count }} 張表・
                        {{ versionDetails[row.id]?.relationship_count }} 個關聯
                      </div>
                      <el-tag v-for="t in versionDetails[row.id]?.tables" :key="t" size="small" style="margin: 2px">
                        {{ t }}
                      </el-tag>
                    </template>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="版本" width="80" align="center">
                <template #default="{ row }">
                  <div>{{ row.model_version }}</div>
                  <el-tag v-if="row.is_serving" size="small" type="success">提供中</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="名稱" min-width="110">
                <template #default="{ row }">
                  <template v-if="editingId === row.id">
                    <el-input
                      v-model="editingName"
                      size="small"
                      autofocus
                      @blur="saveRename(row)"
                      @keyup.enter="saveRename(row)"
                      @keyup.esc="editingId = null"
                    />
                  </template>
                  <span v-else style="cursor: pointer; color: #303133" title="雙擊改名" @dblclick="startRename(row)">
                    {{ row.name || '—' }}
                  </span>
                  <div v-if="row.derived_from_version" class="hint" style="margin: 0">
                    由版本 {{ row.derived_from_version }} 刪減而來
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="上傳時間" min-width="120">
                <template #default="{ row }">{{ formatDate(row.uploaded_at) }}</template>
              </el-table-column>
              <el-table-column label="" width="180" align="center">
                <template #default="{ row }">
                  <el-button size="small" @click="openDerive(row)">刪減項目</el-button>
                  <el-dropdown trigger="click" style="margin-left: 8px" @command="(cmd: string) => onVersionCommand(cmd, row)">
                    <el-button size="small">更多<el-icon class="el-icon--right"><ArrowDown /></el-icon></el-button>
                    <template #dropdown>
                      <el-dropdown-menu>
                        <el-dropdown-item command="serve" :disabled="config?.active_model_version === row.model_version">
                          固定提供這一版
                        </el-dropdown-item>
                        <el-dropdown-item command="desc">{{ row.model_description ? '編輯說明' : '新增說明' }}</el-dropdown-item>
                        <el-dropdown-item command="export">匯出</el-dropdown-item>
                        <el-dropdown-item command="delete" divided :disabled="config?.active_model_version === row.model_version">
                          刪除
                        </el-dropdown-item>
                      </el-dropdown-menu>
                    </template>
                  </el-dropdown>
                </template>
              </el-table-column>
            </el-table>
          </el-card>
        </el-col>
      </el-row>
    </el-tab-pane>

    <!-- 篩選規則 -->
    <el-tab-pane :label="tabLabel('篩選規則', filtersSection)" name="filters">
      <el-alert type="info" :closable="false" style="margin-bottom: 12px">
        <template #title>
          AI 產生查詢時自動加上的條件。分兩種：<b>預設篩選</b>每次查詢都會加（例如一律排除退貨單、測試資料）；
          <b>情境篩選</b>只在使用者的問題提到特定關鍵字時才加（例如提到「退貨」時改成只看退貨單）。
        </template>
      </el-alert>
      <SectionShell :section="filtersSection">
        <template #hint>
          <SchemaSource v-model="schemaVersion" :versions="versionNumbers" :serving-version="servingVersion" />
        </template>
        <FilterProfilesEditor v-model="filtersSection.state.items" :tables="tableNames" />
      </SectionShell>
    </el-tab-pane>

    <!-- 查詢模式 -->
    <el-tab-pane :label="tabLabel('查詢模式', queryModesSection)" name="query-modes">
      <el-alert type="info" :closable="false" style="margin-bottom: 12px">
        <template #title>
          限制這份設定能查的資料範圍。設了多個模式時，AI 會在查詢前請使用者選一個；沒設定就是整個模型都能查。
          要讓不同部門看不同範圍，請建立多份 PBI 設定分別指派，而不是在同一份設定裡用模式區隔。
        </template>
      </el-alert>
      <SectionShell :section="queryModesSection">
        <template #hint>
          <SchemaSource v-model="schemaVersion" :versions="versionNumbers" :serving-version="servingVersion" />
        </template>
        <QueryModesEditor v-model="queryModesSection.state.items" :tables="tableNames" />
      </SectionShell>
    </el-tab-pane>

    <!-- 篩選欄位別名 -->
    <el-tab-pane :label="tabLabel('篩選欄位別名', columnAliasesSection)" name="column-aliases">
      <el-alert type="info" :closable="false" style="margin-bottom: 12px">
        <template #title>
          把使用者的日常說法對應到模型裡實際的名稱，可以設兩種：<b>欄位的其他說法</b>（使用者說「地區」，指的是
          <code>region</code> 欄位），以及<b>欄位值的對照</b>（使用者說「北部」，資料裡存的是 <code>North</code>）。
          設定後 AI 會換成正確的名稱去查，避免找錯欄位或因為值對不上而查不到資料。
        </template>
      </el-alert>
      <SectionShell :section="columnAliasesSection">
        <template #hint>
          <SchemaSource v-model="schemaVersion" :versions="versionNumbers" :serving-version="servingVersion" />
        </template>
        <ColumnAliasesEditor v-model="columnAliasesSection.state.items" :tables="schemaTables" />
      </SectionShell>
    </el-tab-pane>
  </el-tabs>

  <DeriveVersionDialog
    v-model="deriveDialog.visible"
    :chunk-id="deriveDialog.chunkId"
    :source-version="deriveDialog.version"
    :config="config"
    @saved="onDerived"
  />

  <!-- 編輯模型說明 dialog -->
  <el-dialog v-model="descDialog.visible" title="模型說明" width="600px">
    <el-alert type="info" :closable="false" style="margin-bottom: 12px">
      <template #title>以 Markdown 撰寫，Skill 會直接輸出給使用者，留空則由 Claude 自動推論</template>
    </el-alert>
    <el-input
      v-model="descDialog.text"
      type="textarea"
      :rows="14"
      placeholder="## 可查詢的資料主題&#10;&#10;### 訂單與銷售&#10;| 資料表 | 說明 |&#10;..."
    />
    <template #footer>
      <el-button @click="descDialog.visible = false">取消</el-button>
      <el-button type="primary" :loading="descDialog.loading" @click="saveDescription">儲存</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { UploadFile } from 'element-plus'
import http from '@/api/http'
import { formatDate } from '@/utils/date'
import SectionShell from '@/components/pbi/SectionShell.vue'
import FilterProfilesEditor from '@/components/pbi/FilterProfilesEditor.vue'
import QueryModesEditor from '@/components/pbi/QueryModesEditor.vue'
import ColumnAliasesEditor from '@/components/pbi/ColumnAliasesEditor.vue'
import DeriveVersionDialog from '@/components/pbi/DeriveVersionDialog.vue'
import SchemaSource from '@/components/pbi/SchemaSource.vue'
import { duplicates, useConfigSection } from '@/components/pbi/useConfigSection'
import {
  cleanRule,
  normalizeAliasGroup,
  normalizeMode,
  normalizeProfile,
  type ColumnAliasGroup,
  type FilterProfile,
  type FilterRule,
  type QueryMode,
  type SchemaTable,
} from '@/components/pbi/types'

interface PbiConfig {
  id: string
  name: string
  workspace_id: string | null
  dataset_id: string | null
  filters: any[]
  query_modes: any[]
  column_aliases: any[]
  /** null = 跟隨最新版 */
  active_model_version: number | null
  /** MCP 實際提供的版本（後端算好，考慮了跟隨最新版） */
  serving_model_version: number | null
}
interface Version {
  id: string
  model_version: number
  name: string | null
  model_description: string | null
  pbi_config_id: string | null
  derived_from_version: number | null
  is_serving: boolean
  table_count: number
  relationship_count: number
  uploaded_at: string
}
interface VersionDetail {
  tables: string[]
  table_count: number
  relationship_count: number
}

const route = useRoute()
const router = useRouter()
const configId = route.params.id as string

const activeTab = ref('basic')
const loading = ref(false)
const config = ref<PbiConfig | null>(null)

const basicForm = ref({ workspace_id: '', dataset_id: '' })
const basicSaving = ref(false)

// 表名／欄位名下拉選單的來源，預設是 MCP 提供中的版本；還沒上傳模型時退回手動輸入。
// schemaVersion 為 null 代表跟著提供中的版本，管理員也可以先切到還沒上線的版本調設定。
const schemaTables = ref<SchemaTable[]>([])
const schemaVersion = ref<number | null>(null)
const tableNames = computed(() => schemaTables.value.map((t) => t.table))

async function loadSchema() {
  try {
    const params = schemaVersion.value === null ? {} : { version: schemaVersion.value }
    const { data } = await http.get(`/pbi-configs/${configId}/schema`, { params })
    schemaTables.value = data.tables
  } catch {
    // 下拉選單只是輔助，抓不到就讓管理員手動輸入
  }
}
watch(schemaVersion, loadSchema)

const servingVersion = computed(() => config.value?.serving_model_version ?? null)
const followLatest = computed(() => config.value?.active_model_version == null)
const versionNumbers = computed(() => versions.value.map((v) => v.model_version))

// 只更新版本相關欄位，不重跑 load()：load() 會把篩選規則等分頁還沒存的修改洗掉
async function refreshServing() {
  try {
    const { data } = await http.get(`/pbi-configs/${configId}`)
    if (config.value) {
      config.value.active_model_version = data.active_model_version
      config.value.serving_model_version = data.serving_model_version
    }
  } catch {
    // 顯示用，失敗不影響操作
  }
}

async function setServing(version: number | null) {
  try {
    const { data } = await http.put(`/pbi-configs/${configId}/active-version`, { model_version: version })
    if (config.value) {
      config.value.active_model_version = data.active_model_version
      config.value.serving_model_version = data.serving_model_version
    }
    ElMessage.success(data.message)
    await Promise.all([loadVersions(), loadSchema()])
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail ?? '切換失敗')
  }
}

function ruleErrors(prefix: string, rules: FilterRule[]) {
  return rules.flatMap((r, j) =>
    r.expression.trim() ? [] : [`${prefix}第 ${j + 1} 條篩選條件沒有填 DAX 運算式`],
  )
}

const filtersSection = useConfigSection<FilterProfile>({
  configId,
  field: 'filters',
  label: '篩選規則',
  normalize: normalizeProfile,
  clean: (p) => ({
    filterId: p.filterId.trim(),
    name: p.name.trim(),
    ...(p.description?.trim() ? { description: p.description.trim() } : {}),
    alwaysApply: p.alwaysApply,
    // 「每次都套用」的規則用不到這兩個欄位，存成預設值，免得留下切換前的殘值造成誤會
    overrideDefaults: p.alwaysApply ? false : p.overrideDefaults,
    contextKeywords: p.alwaysApply ? [] : p.contextKeywords,
    filters: p.filters.map(cleanRule),
  }),
  validate: (items) => {
    const errors: string[] = []
    items.forEach((p, i) => {
      const label = `「${p.name || `第 ${i + 1} 組`}」`
      if (!p.name.trim()) errors.push(`第 ${i + 1} 組規則沒有填名稱`)
      if (!p.filterId.trim()) errors.push(`${label}的 filterId 是空的，請切到 JSON 模式修改`)
      if (!p.alwaysApply && !p.contextKeywords.length) {
        errors.push(`${label}設定成「提到關鍵字才套用」，但沒有填任何觸發關鍵字，永遠不會生效`)
      }
      if (!p.filters.length) errors.push(`${label}沒有任何篩選條件`)
      errors.push(...ruleErrors(label, p.filters))
    })
    for (const d of duplicates(items.map((p) => p.filterId.trim()))) {
      errors.push(`filterId「${d}」重複了，請切到 JSON 模式修改`)
    }
    return errors
  },
  onSaved: () => load(),
})

const queryModesSection = useConfigSection<QueryMode>({
  configId,
  field: 'query_modes',
  label: '查詢模式',
  normalize: normalizeMode,
  clean: (m) => ({
    mode_id: m.mode_id.trim(),
    name: m.name.trim(),
    ...(m.description?.trim() ? { description: m.description.trim() } : {}),
    tables: m.tables,
    filters: m.filters.map(cleanRule),
  }),
  validate: (items) => {
    const errors: string[] = []
    items.forEach((m, i) => {
      const label = `「${m.name || `第 ${i + 1} 個模式`}」`
      if (!m.name.trim()) errors.push(`第 ${i + 1} 個模式沒有填名稱`)
      if (!m.mode_id.trim()) errors.push(`${label}的 mode_id 是空的，請切到 JSON 模式修改`)
      errors.push(...ruleErrors(label, m.filters))
    })
    for (const d of duplicates(items.map((m) => m.mode_id.trim()))) {
      errors.push(`mode_id「${d}」重複了，請切到 JSON 模式修改`)
    }
    return errors
  },
  onSaved: () => load(),
})

const columnAliasesSection = useConfigSection<ColumnAliasGroup>({
  configId,
  field: 'column_aliases',
  label: '篩選欄位別名',
  normalize: normalizeAliasGroup,
  clean: (g) => ({
    table: g.table.trim(),
    column: g.column.trim(),
    aliases: g.aliases,
    values: g.values.map((v) => ({ value: v.value.trim(), aliases: v.aliases })),
  }),
  validate: (items) => {
    const errors: string[] = []
    items.forEach((g, i) => {
      const label = g.table && g.column ? `${g.table}[${g.column}]` : `第 ${i + 1} 個欄位`
      if (!g.table.trim() || !g.column.trim()) errors.push(`${label}沒有選擇資料表或欄位`)
      if (!g.aliases.length && !g.values.length) errors.push(`${label}沒有填欄位的其他說法，也沒有任何值的對照`)
      g.values.forEach((v, j) => {
        if (!v.value.trim()) errors.push(`${label}第 ${j + 1} 個值沒有填「資料裡實際存的值」`)
      })
    })
    return errors
  },
  onSaved: () => load(),
})

const sections = [filtersSection, queryModesSection, columnAliasesSection]

function tabLabel(label: string, section: { dirty: { value: boolean } }) {
  return section.dirty.value ? `${label} ●` : label
}

function hasUnsaved() {
  return sections.some((s) => s.dirty.value)
}

onBeforeRouteLeave(async () => {
  if (!hasUnsaved()) return true
  try {
    await ElMessageBox.confirm('篩選規則／查詢模式／欄位別名有修改還沒儲存，離開後這些修改會遺失。', '尚未儲存', {
      confirmButtonText: '放棄修改並離開',
      cancelButtonText: '留在這頁',
      type: 'warning',
    })
    return true
  } catch {
    return false
  }
})

// 關分頁、重新整理這種不經過 Vue Router 的離開，只能用瀏覽器內建的確認框
function onBeforeUnload(e: BeforeUnloadEvent) {
  if (hasUnsaved()) e.preventDefault()
}
onMounted(() => window.addEventListener('beforeunload', onBeforeUnload))
onBeforeUnmount(() => window.removeEventListener('beforeunload', onBeforeUnload))

async function load() {
  loading.value = true
  try {
    const { data } = await http.get(`/pbi-configs/${configId}`)
    config.value = data
    basicForm.value = { workspace_id: data.workspace_id ?? '', dataset_id: data.dataset_id ?? '' }
    filtersSection.load(data.filters)
    queryModesSection.load(data.query_modes)
    columnAliasesSection.load(data.column_aliases)
  } catch {
    ElMessage.error('無法載入 PBI 設定')
  } finally {
    loading.value = false
  }
}

async function saveBasic() {
  basicSaving.value = true
  try {
    await http.patch(`/pbi-configs/${configId}`, basicForm.value)
    ElMessage.success('已儲存')
    await load()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail ?? '儲存失敗')
  } finally {
    basicSaving.value = false
  }
}

// ── 語意模型版本 ────────────────────────────────────────────────────

const inputMode = ref<'file' | 'text'>('file')
const uploadName = ref('')
const uploadDescription = ref('')
const fileContent = ref('')
const fileName = ref('')
const fileList = ref<UploadFile[]>([])
const rawJson = ref('')
const parseError = ref('')
const uploading = ref(false)
const versions = ref<Version[]>([])
const loadingVersions = ref(false)
const versionDetails = ref<Record<string, VersionDetail>>({})
const editingId = ref<string | null>(null)
const editingName = ref('')
const descDialog = ref({ visible: false, loading: false, id: '', text: '' })

function handleFileChange(file: UploadFile) {
  if (!file.raw) return
  fileName.value = file.raw.name
  const reader = new FileReader()
  reader.onload = (e) => { fileContent.value = (e.target?.result as string) ?? '' }
  reader.readAsText(file.raw, 'utf-8')
}

async function handleUpload() {
  parseError.value = ''
  const source = inputMode.value === 'file' ? fileContent.value : rawJson.value
  if (!source.trim()) {
    parseError.value = inputMode.value === 'file' ? '請先選擇 .json 檔案' : '請貼上 JSON 內容'
    return
  }
  let parsed: unknown
  try { parsed = JSON.parse(source) } catch {
    parseError.value = 'JSON 格式錯誤，請確認內容'
    return
  }
  uploading.value = true
  try {
    const res = await http.post('/model/upload', {
      pbi_config_id: configId,
      name: uploadName.value || null,
      model_description: uploadDescription.value || null,
      data: parsed,
    })
    ElMessage.success(
      `上傳成功 — 版本 ${res.data.model_version}（${res.data.table_count} 張表，${res.data.relationship_count} 個關聯）`,
    )
    uploadName.value = ''
    uploadDescription.value = ''
    fileContent.value = ''
    fileName.value = ''
    fileList.value = []
    rawJson.value = ''
    await refreshServing()
    await Promise.all([loadVersions(), loadSchema()])
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail ?? '上傳失敗')
  } finally {
    uploading.value = false
  }
}

async function loadVersions() {
  loadingVersions.value = true
  try {
    const res = await http.get('/model/versions', { params: { pbi_config_id: configId } })
    versions.value = res.data
    // 下拉選單正在看的版本被刪掉了，退回提供中的版本
    if (schemaVersion.value !== null && !versionNumbers.value.includes(schemaVersion.value)) {
      schemaVersion.value = null
    }
  } finally {
    loadingVersions.value = false
  }
}

async function handleExpand(row: Version, expandedRows: Version[]) {
  if (!expandedRows.find((r) => r.id === row.id)) return
  if (versionDetails.value[row.id]) return
  try {
    const res = await http.get(`/model/versions/${row.id}`)
    versionDetails.value[row.id] = res.data
  } catch {
    ElMessage.error('載入版本詳情失敗')
  }
}

function startRename(row: Version) {
  editingId.value = row.id
  editingName.value = row.name ?? ''
}

async function saveRename(row: Version) {
  if (editingId.value !== row.id) return
  editingId.value = null
  try {
    await http.patch(`/model/versions/${row.id}`, { name: editingName.value || null })
    row.name = editingName.value || null
  } catch {
    ElMessage.error('改名失敗')
  }
}

async function exportVersion(row: Version) {
  try {
    const res = await http.get(`/model/versions/${row.id}/export`, { responseType: 'blob' })
    const url = URL.createObjectURL(new Blob([res.data], { type: 'application/json' }))
    const a = document.createElement('a')
    a.href = url
    const safeName = (config.value?.name ?? 'model').replace(/[/\\:*?"<>|]/g, '_')
    a.download = `${safeName}_v${row.model_version}.json`
    a.click()
    URL.revokeObjectURL(url)
  } catch {
    ElMessage.error('匯出失敗')
  }
}

function openDescDialog(row: Version) {
  descDialog.value = { visible: true, loading: false, id: row.id, text: row.model_description ?? '' }
}

async function saveDescription() {
  descDialog.value.loading = true
  try {
    await http.patch(`/model/versions/${descDialog.value.id}`, { model_description: descDialog.value.text || null })
    const row = versions.value.find((v) => v.id === descDialog.value.id)
    if (row) row.model_description = descDialog.value.text || null
    ElMessage.success('模型說明已儲存')
    descDialog.value.visible = false
  } catch {
    ElMessage.error('儲存失敗')
  } finally {
    descDialog.value.loading = false
  }
}

async function deleteVersion(row: Version) {
  const warning = row.is_serving
    ? `版本 ${row.model_version} 是 AI 目前拿到的版本，刪除後會改提供剩下的最新版。確定刪除？`
    : `確定刪除版本 ${row.model_version}？刪除後無法復原。`
  try {
    await ElMessageBox.confirm(warning, '刪除版本', {
      confirmButtonText: '刪除',
      cancelButtonText: '取消',
      confirmButtonClass: 'el-button--danger',
      type: 'warning',
    })
  } catch {
    return
  }
  try {
    await http.delete(`/model/versions/${row.id}`)
    ElMessage.success(`版本 ${row.model_version} 已刪除`)
    delete versionDetails.value[row.id]
    await refreshServing()
    await Promise.all([loadVersions(), loadSchema()])
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail ?? '刪除失敗')
  }
}

function onVersionCommand(cmd: string, row: Version) {
  if (cmd === 'serve') setServing(row.model_version)
  else if (cmd === 'desc') openDescDialog(row)
  else if (cmd === 'export') exportVersion(row)
  else if (cmd === 'delete') deleteVersion(row)
}

const deriveDialog = ref({ visible: false, chunkId: '', version: 0 })

function openDerive(row: Version) {
  deriveDialog.value = { visible: true, chunkId: row.id, version: row.model_version }
}

async function onDerived() {
  await refreshServing()
  await Promise.all([loadVersions(), loadSchema()])
}

onMounted(async () => {
  await Promise.all([load(), loadVersions(), loadSchema()])
})
</script>

<style scoped>
.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}
.serving {
  display: inline-flex;
  align-items: center;
  gap: 12px;
  font-size: 13px;
}
.hint {
  font-size: 12px;
  line-height: 1.6;
  color: var(--el-text-color-secondary);
  margin-top: 4px;
}
</style>

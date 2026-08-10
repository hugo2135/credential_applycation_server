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
            <template #header>版本歷史</template>
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
              <el-table-column prop="model_version" label="版本" width="60" align="center" />
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
                </template>
              </el-table-column>
              <el-table-column label="上傳時間" min-width="120">
                <template #default="{ row }">{{ formatDate(row.uploaded_at) }}</template>
              </el-table-column>
              <el-table-column label="" width="190" align="center">
                <template #default="{ row }">
                  <el-button size="small" @click="openDescDialog(row)">
                    {{ row.model_description ? '編輯說明' : '新增說明' }}
                  </el-button>
                  <el-button size="small" type="success" plain @click="exportVersion(row)">匯出</el-button>
                  <el-popconfirm title="確定刪除此版本？" confirm-button-type="danger" @confirm="deleteVersion(row)">
                    <template #reference>
                      <el-button size="small" type="danger" plain>刪除</el-button>
                    </template>
                  </el-popconfirm>
                </template>
              </el-table-column>
            </el-table>
          </el-card>
        </el-col>
      </el-row>
    </el-tab-pane>

    <!-- 篩選規則 -->
    <el-tab-pane label="篩選規則" name="filters">
      <el-alert type="info" :closable="false" style="margin-bottom: 12px">
        <template #title>
          JSON 陣列，每筆一個篩選設定檔（filterId/name/alwaysApply/overrideDefaults/contextKeywords/filters）。
          Skill 透過 get_model_detail 取得，格式說明見 docs/skill-integration.md。
        </template>
      </el-alert>
      <el-input
        v-model="filtersText"
        type="textarea"
        :rows="16"
        style="font-family: monospace; font-size: 12px"
        placeholder='[
  {
    "filterId": "exclude-return-orders",
    "name": "排除退貨單",
    "description": "預設查詢排除退貨訂單",
    "alwaysApply": true,
    "overrideDefaults": false,
    "contextKeywords": [],
    "filters": [
      { "description": "排除退貨單", "expression": "Orders[order_type] <> \"return_order\"" }
    ]
  }
]'
      />
      <div v-if="filtersError" style="color: #f56c6c; font-size: 13px; margin-top: 8px">{{ filtersError }}</div>
      <el-button type="primary" :loading="filtersSaving" style="margin-top: 12px" @click="saveFilters">儲存</el-button>
    </el-tab-pane>

    <!-- 查詢模式 -->
    <el-tab-pane label="查詢模式" name="query-modes">
      <el-alert type="info" :closable="false" style="margin-bottom: 12px">
        <template #title>
          JSON 陣列，每筆一個資料曝光範圍模式（mode_id/name/description/tables/filters）。tables 是語意模型裡的表名子集，
          留空代表不限制；filters 會疊加在「篩選規則」比對出來的結果之上。存取限制沿用既有的 PBI 設定指派機制。
        </template>
      </el-alert>
      <el-input
        v-model="queryModesText"
        type="textarea"
        :rows="16"
        style="font-family: monospace; font-size: 12px"
        placeholder='[
  {
    "mode_id": "summary",
    "name": "摘要模式",
    "description": "只看高階彙總表",
    "tables": ["Sales", "Product"],
    "filters": []
  }
]'
      />
      <div v-if="queryModesError" style="color: #f56c6c; font-size: 13px; margin-top: 8px">{{ queryModesError }}</div>
      <el-button type="primary" :loading="queryModesSaving" style="margin-top: 12px" @click="saveQueryModes">儲存</el-button>
    </el-tab-pane>

    <!-- 篩選欄位別名 -->
    <el-tab-pane label="篩選欄位別名" name="column-aliases">
      <el-alert type="info" :closable="false" style="margin-bottom: 12px">
        <template #title>
          JSON 陣列，每筆對應一個重點欄位（table/column/values），values 是該欄位可能的值跟使用者可能會用的別名，
          讓 Skill 把自然語言用詞轉換成實際存在 Power BI 裡的欄位值。
        </template>
      </el-alert>
      <el-input
        v-model="columnAliasesText"
        type="textarea"
        :rows="16"
        style="font-family: monospace; font-size: 12px"
        placeholder='[
  {
    "table": "Orders",
    "column": "region",
    "values": [
      { "value": "North", "aliases": ["北區", "北部"] },
      { "value": "South", "aliases": ["南區", "南部"] }
    ]
  }
]'
      />
      <div v-if="columnAliasesError" style="color: #f56c6c; font-size: 13px; margin-top: 8px">{{ columnAliasesError }}</div>
      <el-button type="primary" :loading="columnAliasesSaving" style="margin-top: 12px" @click="saveColumnAliases">儲存</el-button>
    </el-tab-pane>
  </el-tabs>

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
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { UploadFile } from 'element-plus'
import http from '@/api/http'
import { formatDate } from '@/utils/date'

interface PbiConfig {
  id: string
  name: string
  workspace_id: string | null
  dataset_id: string | null
  filters: unknown[]
  query_modes: unknown[]
  column_aliases: unknown[]
}
interface Version {
  id: string
  model_version: number
  name: string | null
  model_description: string | null
  pbi_config_id: string | null
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

const filtersText = ref('')
const filtersError = ref('')
const filtersSaving = ref(false)

const queryModesText = ref('')
const queryModesError = ref('')
const queryModesSaving = ref(false)

const columnAliasesText = ref('')
const columnAliasesError = ref('')
const columnAliasesSaving = ref(false)

async function load() {
  loading.value = true
  try {
    const { data } = await http.get(`/pbi-configs/${configId}`)
    config.value = data
    basicForm.value = { workspace_id: data.workspace_id ?? '', dataset_id: data.dataset_id ?? '' }
    filtersText.value = data.filters?.length ? JSON.stringify(data.filters, null, 2) : ''
    queryModesText.value = data.query_modes?.length ? JSON.stringify(data.query_modes, null, 2) : ''
    columnAliasesText.value = data.column_aliases?.length ? JSON.stringify(data.column_aliases, null, 2) : ''
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

function parseJsonArray(text: string, label: string): unknown[] | null {
  if (!text.trim()) return []
  try {
    const parsed = JSON.parse(text)
    if (!Array.isArray(parsed)) throw new Error()
    return parsed
  } catch {
    throw new Error(`${label}格式錯誤，最外層必須是 JSON 陣列`)
  }
}

async function saveFilters() {
  filtersError.value = ''
  let filters: unknown[]
  try {
    filters = parseJsonArray(filtersText.value, '篩選規則') ?? []
  } catch (e: any) {
    filtersError.value = e.message
    return
  }
  filtersSaving.value = true
  try {
    await http.patch(`/pbi-configs/${configId}`, { filters })
    ElMessage.success('篩選規則已儲存')
    await load()
  } catch (e: any) {
    filtersError.value = e.response?.data?.detail
      ? (typeof e.response.data.detail === 'string' ? e.response.data.detail : JSON.stringify(e.response.data.detail))
      : '儲存失敗'
  } finally {
    filtersSaving.value = false
  }
}

async function saveQueryModes() {
  queryModesError.value = ''
  let queryModes: unknown[]
  try {
    queryModes = parseJsonArray(queryModesText.value, '查詢模式') ?? []
  } catch (e: any) {
    queryModesError.value = e.message
    return
  }
  queryModesSaving.value = true
  try {
    await http.patch(`/pbi-configs/${configId}`, { query_modes: queryModes })
    ElMessage.success('查詢模式已儲存')
    await load()
  } catch (e: any) {
    queryModesError.value = e.response?.data?.detail
      ? (typeof e.response.data.detail === 'string' ? e.response.data.detail : JSON.stringify(e.response.data.detail))
      : '儲存失敗'
  } finally {
    queryModesSaving.value = false
  }
}

async function saveColumnAliases() {
  columnAliasesError.value = ''
  let columnAliases: unknown[]
  try {
    columnAliases = parseJsonArray(columnAliasesText.value, '篩選欄位別名') ?? []
  } catch (e: any) {
    columnAliasesError.value = e.message
    return
  }
  columnAliasesSaving.value = true
  try {
    await http.patch(`/pbi-configs/${configId}`, { column_aliases: columnAliases })
    ElMessage.success('篩選欄位別名已儲存')
    await load()
  } catch (e: any) {
    columnAliasesError.value = e.response?.data?.detail
      ? (typeof e.response.data.detail === 'string' ? e.response.data.detail : JSON.stringify(e.response.data.detail))
      : '儲存失敗'
  } finally {
    columnAliasesSaving.value = false
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
    await loadVersions()
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
  try {
    await http.delete(`/model/versions/${row.id}`)
    ElMessage.success(`版本 ${row.model_version} 已刪除`)
    delete versionDetails.value[row.id]
    await loadVersions()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail ?? '刪除失敗')
  }
}

onMounted(async () => {
  await load()
  await loadVersions()
})
</script>

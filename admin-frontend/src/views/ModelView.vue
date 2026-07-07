<template>
  <el-row :gutter="16">
    <!-- 上傳區 -->
    <el-col :span="13">
      <el-card>
        <template #header>上傳新版語意模型</template>

        <el-form label-position="top">
          <el-form-item label="PBI 設定（必填）" required>
            <el-select
              v-model="uploadConfigId"
              placeholder="選擇 PBI 設定"
              style="width: 100%"
              :loading="loadingConfigs"
            >
              <el-option
                v-for="c in configs"
                :key="c.id"
                :label="c.name"
                :value="c.id"
              />
            </el-select>
          </el-form-item>

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

    <!-- 版本歷史 -->
    <el-col :span="11">
      <el-card>
        <template #header>
          <div style="display: flex; align-items: center; gap: 12px">
            <span>版本歷史</span>
            <el-select
              v-model="filterConfigId"
              placeholder="全部 PBI 設定"
              clearable
              size="small"
              style="width: 160px"
              @change="loadVersions"
            >
              <el-option
                v-for="c in configs"
                :key="c.id"
                :label="c.name"
                :value="c.id"
              />
            </el-select>
          </div>
        </template>

        <el-table
          :data="versions"
          v-loading="loadingVersions"
          border
          row-key="model_version"
          @expand-change="handleExpand"
        >
          <el-table-column type="expand">
            <template #default="{ row }">
              <div style="padding: 8px 16px">
                <div v-if="!details[row.model_version]" style="color: #909399; font-size: 13px">載入中…</div>
                <template v-else>
                  <div style="font-size: 13px; color: #606266; margin-bottom: 6px">
                    {{ details[row.model_version]?.table_count }} 張表・
                    {{ details[row.model_version]?.relationship_count }} 個關聯
                  </div>
                  <el-tag
                    v-for="t in details[row.model_version]?.tables"
                    :key="t"
                    size="small"
                    style="margin: 2px"
                  >
                    {{ t }}
                  </el-tag>
                </template>
              </div>
            </template>
          </el-table-column>

          <el-table-column prop="model_version" label="版本" width="60" align="center" />

          <el-table-column label="名稱" min-width="110">
            <template #default="{ row }">
              <template v-if="editingVersion === row.model_version">
                <el-input
                  v-model="editingName"
                  size="small"
                  autofocus
                  @blur="saveRename(row)"
                  @keyup.enter="saveRename(row)"
                  @keyup.esc="editingVersion = null"
                />
              </template>
              <span
                v-else
                style="cursor: pointer; color: #303133"
                title="雙擊改名"
                @dblclick="startRename(row)"
              >
                {{ row.name || '—' }}
              </span>
            </template>
          </el-table-column>

          <el-table-column label="PBI 設定" min-width="90">
            <template #default="{ row }">
              <span style="font-size: 12px; color: #606266">{{ configName(row.pbi_config_id) }}</span>
            </template>
          </el-table-column>

          <el-table-column label="上傳時間" min-width="120">
            <template #default="{ row }">{{ fmtDate(row.uploaded_at) }}</template>
          </el-table-column>

          <el-table-column label="" width="190" align="center">
            <template #default="{ row }">
              <el-button size="small" @click="openDescDialog(row)">
                {{ row.model_description ? '編輯說明' : '新增說明' }}
              </el-button>
              <el-button size="small" type="success" plain @click="exportVersion(row)">匯出</el-button>
              <el-popconfirm
                title="確定刪除此版本？"
                confirm-button-type="danger"
                @confirm="deleteVersion(row)"
              >
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
import { ElMessage } from 'element-plus'
import type { UploadFile } from 'element-plus'
import http from '@/api/http'

interface PbiConfig {
  id: string
  name: string
}
interface Version {
  model_version: number
  name: string | null
  model_description: string | null
  pbi_config_id: string | null
  table_count: number
  relationship_count: number
  uploaded_at: string
}
interface Detail {
  tables: string[]
  table_count: number
  relationship_count: number
}

const configs        = ref<PbiConfig[]>([])
const loadingConfigs = ref(false)
const uploadConfigId = ref('')
const filterConfigId = ref('')

const inputMode         = ref<'file' | 'text'>('file')
const uploadName        = ref('')
const uploadDescription = ref('')
const fileContent  = ref('')
const fileName     = ref('')
const fileList     = ref<UploadFile[]>([])
const rawJson      = ref('')
const parseError   = ref('')
const uploading    = ref(false)
const versions     = ref<Version[]>([])
const loadingVersions = ref(false)
const details      = ref<Record<number, Detail>>({})
const editingVersion = ref<number | null>(null)
const editingName    = ref('')
const descDialog     = ref({ visible: false, loading: false, version: 0, text: '' })

function fmtDate(d: string) {
  return new Date(d).toLocaleString()
}

function configName(id: string | null) {
  if (!id) return '—'
  return configs.value.find(c => c.id === id)?.name ?? '—'
}

async function loadConfigs() {
  loadingConfigs.value = true
  try {
    const res = await http.get('/pbi-configs')
    configs.value = res.data
  } finally {
    loadingConfigs.value = false
  }
}

function handleFileChange(file: UploadFile) {
  if (!file.raw) return
  fileName.value = file.raw.name
  const reader = new FileReader()
  reader.onload = (e) => { fileContent.value = e.target?.result as string ?? '' }
  reader.readAsText(file.raw, 'utf-8')
}

async function handleUpload() {
  parseError.value = ''
  if (!uploadConfigId.value) {
    parseError.value = '請選擇 PBI 設定'
    return
  }
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
      pbi_config_id: uploadConfigId.value,
      name: uploadName.value || null,
      model_description: uploadDescription.value || null,
      data: parsed,
    })
    ElMessage.success(
      `上傳成功 — 版本 ${res.data.model_version}（${res.data.table_count} 張表，${res.data.relationship_count} 個關聯）`
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
    const params = filterConfigId.value ? { pbi_config_id: filterConfigId.value } : {}
    const res = await http.get('/model/versions', { params })
    versions.value = res.data
  } finally {
    loadingVersions.value = false
  }
}

async function handleExpand(row: Version, expandedRows: Version[]) {
  if (!expandedRows.find(r => r.model_version === row.model_version)) return
  if (details.value[row.model_version]) return
  try {
    const res = await http.get(`/model/versions/${row.model_version}`)
    details.value[row.model_version] = res.data
  } catch {
    ElMessage.error('載入版本詳情失敗')
  }
}

function startRename(row: Version) {
  editingVersion.value = row.model_version
  editingName.value = row.name ?? ''
}

async function saveRename(row: Version) {
  if (editingVersion.value !== row.model_version) return
  editingVersion.value = null
  try {
    await http.patch(`/model/versions/${row.model_version}`, { name: editingName.value || null })
    row.name = editingName.value || null
  } catch {
    ElMessage.error('改名失敗')
  }
}

async function exportVersion(row: Version) {
  try {
    const res = await http.get(`/model/versions/${row.model_version}/export`, { responseType: 'blob' })
    const url = URL.createObjectURL(new Blob([res.data], { type: 'application/json' }))
    const a = document.createElement('a')
    a.href = url
    a.download = `model_v${row.model_version}.json`
    a.click()
    URL.revokeObjectURL(url)
  } catch {
    ElMessage.error('匯出失敗')
  }
}

function openDescDialog(row: Version) {
  descDialog.value = { visible: true, loading: false, version: row.model_version, text: row.model_description ?? '' }
}

async function saveDescription() {
  descDialog.value.loading = true
  try {
    await http.patch(`/model/versions/${descDialog.value.version}`, { model_description: descDialog.value.text || null })
    const row = versions.value.find(v => v.model_version === descDialog.value.version)
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
    await http.delete(`/model/versions/${row.model_version}`)
    ElMessage.success(`版本 ${row.model_version} 已刪除`)
    delete details.value[row.model_version]
    await loadVersions()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail ?? '刪除失敗')
  }
}

onMounted(async () => {
  await loadConfigs()
  await loadVersions()
})
</script>

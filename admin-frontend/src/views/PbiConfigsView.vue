<template>
  <el-card>
    <template #header>
      <div style="display: flex; justify-content: space-between; align-items: center">
        <span>PBI 設定列表</span>
        <el-button type="primary" @click="openCreate">新增設定</el-button>
      </div>
    </template>
    <el-table :data="configs" v-loading="loading" border>
      <el-table-column prop="name" label="名稱" width="160" />
      <el-table-column label="Workspace ID" min-width="200">
        <template #default="{ row }">{{ row.workspace_id || '—' }}</template>
      </el-table-column>
      <el-table-column label="Dataset ID" min-width="200">
        <template #default="{ row }">{{ row.dataset_id || '—' }}</template>
      </el-table-column>
      <el-table-column label="篩選規則" width="100" align="center">
        <template #default="{ row }">
          <el-tag v-if="row.filters?.length" size="small">{{ row.filters.length }} 筆</el-tag>
          <span v-else style="color: #c0c4cc; font-size: 13px">未設定</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="240" align="center">
        <template #default="{ row }">
          <el-button size="small" @click="openEdit(row)">編輯</el-button>
          <el-button size="small" @click="openFilters(row)">篩選規則</el-button>
          <el-popconfirm
            title="刪除後相關語意模型也會一併刪除，確定？"
            confirm-button-type="danger"
            @confirm="deleteConfig(row)"
          >
            <template #reference>
              <el-button size="small" type="danger" plain>刪除</el-button>
            </template>
          </el-popconfirm>
        </template>
      </el-table-column>
    </el-table>
  </el-card>

  <!-- 新增 Dialog -->
  <el-dialog v-model="createDialog.visible" title="新增 PBI 設定" width="440px">
    <el-form :model="createDialog.form" label-width="120px">
      <el-form-item label="名稱" required>
        <el-input v-model="createDialog.form.name" placeholder="例：財務模型 A" />
      </el-form-item>
      <el-form-item label="Workspace ID">
        <el-input v-model="createDialog.form.workspace_id" placeholder="Power BI Workspace UUID" />
      </el-form-item>
      <el-form-item label="Dataset ID">
        <el-input v-model="createDialog.form.dataset_id" placeholder="Power BI Dataset UUID" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="createDialog.visible = false">取消</el-button>
      <el-button type="primary" :loading="createDialog.loading" @click="submitCreate">建立</el-button>
    </template>
  </el-dialog>

  <!-- 編輯 Dialog -->
  <el-dialog v-model="editDialog.visible" title="編輯 PBI 設定" width="440px">
    <el-form :model="editDialog.form" label-width="120px">
      <el-form-item label="名稱">
        <el-input :value="editDialog.name" disabled />
      </el-form-item>
      <el-form-item label="Workspace ID">
        <el-input v-model="editDialog.form.workspace_id" />
      </el-form-item>
      <el-form-item label="Dataset ID">
        <el-input v-model="editDialog.form.dataset_id" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="editDialog.visible = false">取消</el-button>
      <el-button type="primary" :loading="editDialog.loading" @click="submitEdit">儲存</el-button>
    </template>
  </el-dialog>

  <!-- 篩選規則 Dialog -->
  <el-dialog v-model="filterDialog.visible" title="篩選規則" width="640px">
    <el-alert type="info" :closable="false" style="margin-bottom: 12px">
      <template #title>
        JSON 陣列，每筆一個篩選設定檔（filterId/name/alwaysApply/overrideDefaults/contextKeywords/filters）。
        Skill 透過 get_model_detail 取得，格式說明見 docs/skill-integration.md。
      </template>
    </el-alert>
    <el-input
      v-model="filterDialog.text"
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
    <div v-if="filterDialog.error" style="color: #f56c6c; font-size: 13px; margin-top: 8px">
      {{ filterDialog.error }}
    </div>
    <template #footer>
      <el-button @click="filterDialog.visible = false">取消</el-button>
      <el-button type="primary" :loading="filterDialog.loading" @click="submitFilters">儲存</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import http from '@/api/http'

interface FilterProfile {
  filterId: string
  name: string
  description?: string | null
  alwaysApply: boolean
  overrideDefaults: boolean
  contextKeywords: string[]
  filters: { description: string; expression: string; requiredTable?: string | null }[]
}
interface Config {
  id: string
  name: string
  workspace_id: string | null
  dataset_id: string | null
  filters: FilterProfile[]
}

const configs = ref<Config[]>([])
const loading = ref(false)

const createDialog = ref({
  visible: false,
  loading: false,
  form: { name: '', workspace_id: '', dataset_id: '' },
})

const editDialog = ref({
  visible: false,
  loading: false,
  configId: '',
  name: '',
  form: { workspace_id: '', dataset_id: '' },
})

const filterDialog = ref({
  visible: false,
  loading: false,
  configId: '',
  text: '',
  error: '',
})

async function load() {
  loading.value = true
  try {
    const res = await http.get('/pbi-configs')
    configs.value = res.data
  } finally {
    loading.value = false
  }
}

function openCreate() {
  createDialog.value = {
    visible: true,
    loading: false,
    form: { name: '', workspace_id: '', dataset_id: '' },
  }
}

function openEdit(row: Config) {
  editDialog.value = {
    visible: true,
    loading: false,
    configId: row.id,
    name: row.name,
    form: {
      workspace_id: row.workspace_id ?? '',
      dataset_id: row.dataset_id ?? '',
    },
  }
}

function openFilters(row: Config) {
  filterDialog.value = {
    visible: true,
    loading: false,
    configId: row.id,
    text: row.filters?.length ? JSON.stringify(row.filters, null, 2) : '',
    error: '',
  }
}

async function submitFilters() {
  const d = filterDialog.value
  d.error = ''
  let filters: unknown = []
  if (d.text.trim()) {
    try {
      filters = JSON.parse(d.text)
    } catch {
      d.error = 'JSON 格式錯誤，請確認內容'
      return
    }
    if (!Array.isArray(filters)) {
      d.error = '最外層必須是陣列（每筆一個篩選設定檔）'
      return
    }
  }
  d.loading = true
  try {
    await http.patch(`/pbi-configs/${d.configId}`, { filters })
    ElMessage.success('篩選規則已儲存')
    d.visible = false
    await load()
  } catch (e: any) {
    d.error = e.response?.data?.detail
      ? typeof e.response.data.detail === 'string'
        ? e.response.data.detail
        : JSON.stringify(e.response.data.detail)
      : '儲存失敗'
  } finally {
    d.loading = false
  }
}

async function submitCreate() {
  const d = createDialog.value
  d.loading = true
  try {
    await http.post('/pbi-configs', d.form)
    ElMessage.success('PBI 設定建立成功')
    d.visible = false
    await load()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail ?? '建立失敗')
  } finally {
    d.loading = false
  }
}

async function submitEdit() {
  const d = editDialog.value
  d.loading = true
  const body: Record<string, string> = {}
  for (const [k, v] of Object.entries(d.form)) {
    if (v) body[k] = v
  }
  try {
    await http.patch(`/pbi-configs/${d.configId}`, body)
    ElMessage.success('PBI 設定更新成功')
    d.visible = false
    await load()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail ?? '更新失敗')
  } finally {
    d.loading = false
  }
}

async function deleteConfig(row: Config) {
  try {
    await http.delete(`/pbi-configs/${row.id}`)
    ElMessage.success(`${row.name} 已刪除`)
    await load()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail ?? '刪除失敗')
  }
}

onMounted(load)
</script>

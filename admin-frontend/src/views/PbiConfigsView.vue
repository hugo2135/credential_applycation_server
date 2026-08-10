<template>
  <el-card>
    <template #header>
      <div style="display: flex; justify-content: space-between; align-items: center">
        <span>PBI 設定列表</span>
        <el-button type="primary" @click="openCreate">新增設定</el-button>
      </div>
    </template>

    <!-- 批次操作工具列，選取後才出現 -->
    <div v-if="selected.length" style="margin-bottom: 12px; display: flex; align-items: center; gap: 8px">
      <span style="font-size: 13px; color: #666">已選擇 {{ selected.length }} 筆</span>
      <el-button size="small" @click="openBatchUpdate">批次修改</el-button>
    </div>

    <el-table :data="configs" v-loading="loading" border @selection-change="selected = $event">
      <el-table-column type="selection" width="42" />
      <el-table-column prop="name" label="名稱" width="160" />
      <el-table-column label="Workspace ID" min-width="200">
        <template #default="{ row }">{{ row.workspace_id || '—' }}</template>
      </el-table-column>
      <el-table-column label="Dataset ID" min-width="200">
        <template #default="{ row }">{{ row.dataset_id || '—' }}</template>
      </el-table-column>
      <el-table-column label="篩選規則" width="90" align="center">
        <template #default="{ row }">
          <el-tag v-if="row.filters?.length" size="small">{{ row.filters.length }}</el-tag>
          <span v-else style="color: #c0c4cc; font-size: 13px">—</span>
        </template>
      </el-table-column>
      <el-table-column label="查詢模式" width="90" align="center">
        <template #default="{ row }">
          <el-tag v-if="row.query_modes?.length" size="small" type="success">{{ row.query_modes.length }}</el-tag>
          <span v-else style="color: #c0c4cc; font-size: 13px">—</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="240" align="center">
        <template #default="{ row }">
          <el-button size="small" @click="router.push(`/admin/pbi-configs/${row.id}`)">詳情</el-button>
          <el-button size="small" @click="openDuplicate(row)">複製</el-button>
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
    <el-form :model="createDialog.form" label-width="80px">
      <el-form-item label="名稱" required>
        <el-input v-model="createDialog.form.name" placeholder="例：財務模型 A" />
      </el-form-item>
    </el-form>
    <el-alert type="info" :closable="false" style="margin-bottom: 4px">
      <template #title>Workspace ID、Dataset ID、篩選規則、查詢模式等其他設定，建立後在詳情頁繼續設定</template>
    </el-alert>
    <template #footer>
      <el-button @click="createDialog.visible = false">取消</el-button>
      <el-button type="primary" :loading="createDialog.loading" @click="submitCreate">建立</el-button>
    </template>
  </el-dialog>

  <!-- 複製 Dialog -->
  <el-dialog v-model="duplicateDialog.visible" title="複製 PBI 設定" width="440px">
    <el-alert type="info" :closable="false" style="margin-bottom: 12px">
      <template #title>會連同 Workspace/Dataset ID、篩選規則、查詢模式、篩選欄位別名、最新一版語意模型一起複製，複製後兩份設定各自獨立</template>
    </el-alert>
    <el-form label-width="80px">
      <el-form-item label="新名稱" required>
        <el-input v-model="duplicateDialog.name" placeholder="例：財務模型 A（物流部）" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="duplicateDialog.visible = false">取消</el-button>
      <el-button type="primary" :loading="duplicateDialog.loading" @click="submitDuplicate">複製</el-button>
    </template>
  </el-dialog>

  <!-- 批次修改 Dialog -->
  <el-dialog v-model="batchDialog.visible" title="批次修改" width="520px">
    <el-alert type="warning" :closable="false" style="margin-bottom: 12px">
      <template #title>
        只能批次修改 Workspace ID、Dataset ID、篩選欄位別名——這三個是底層 Power BI 資料集本身的屬性，適合共用。
        篩選規則跟查詢模式刻意不開放批次修改，因為它們就是要讓不同設定之間有差異，批次覆蓋容易誤刪已調好的設定。
      </template>
    </el-alert>
    <el-form label-width="120px">
      <el-form-item>
        <el-checkbox v-model="batchDialog.applyWorkspace">套用 Workspace ID</el-checkbox>
      </el-form-item>
      <el-form-item label="Workspace ID" v-if="batchDialog.applyWorkspace">
        <el-input v-model="batchDialog.workspace_id" />
      </el-form-item>
      <el-form-item>
        <el-checkbox v-model="batchDialog.applyDataset">套用 Dataset ID</el-checkbox>
      </el-form-item>
      <el-form-item label="Dataset ID" v-if="batchDialog.applyDataset">
        <el-input v-model="batchDialog.dataset_id" />
      </el-form-item>
      <el-form-item>
        <el-checkbox v-model="batchDialog.applyColumnAliases">套用篩選欄位別名</el-checkbox>
      </el-form-item>
      <template v-if="batchDialog.applyColumnAliases">
        <el-input
          v-model="batchDialog.columnAliasesText"
          type="textarea"
          :rows="10"
          style="font-family: monospace; font-size: 12px"
          placeholder='[{ "table": "Orders", "column": "region", "values": [{ "value": "North", "aliases": ["北區"] }] }]'
        />
      </template>
    </el-form>
    <div v-if="batchDialog.error" style="color: #f56c6c; font-size: 13px; margin-top: 8px">{{ batchDialog.error }}</div>
    <template #footer>
      <el-button @click="batchDialog.visible = false">取消</el-button>
      <el-button type="primary" :loading="batchDialog.loading" @click="submitBatchUpdate">套用</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import http from '@/api/http'

interface Config {
  id: string
  name: string
  workspace_id: string | null
  dataset_id: string | null
  filters: unknown[]
  query_modes: unknown[]
}

const router = useRouter()
const configs = ref<Config[]>([])
const loading = ref(false)
const selected = ref<Config[]>([])

const createDialog = ref({
  visible: false,
  loading: false,
  form: { name: '' },
})

const duplicateDialog = ref({
  visible: false,
  loading: false,
  sourceId: '',
  name: '',
})

const batchDialog = ref({
  visible: false,
  loading: false,
  error: '',
  applyWorkspace: false,
  workspace_id: '',
  applyDataset: false,
  dataset_id: '',
  applyColumnAliases: false,
  columnAliasesText: '',
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
  createDialog.value = { visible: true, loading: false, form: { name: '' } }
}

async function submitCreate() {
  const d = createDialog.value
  d.loading = true
  try {
    const res = await http.post('/pbi-configs', d.form)
    ElMessage.success('PBI 設定建立成功')
    d.visible = false
    router.push(`/admin/pbi-configs/${res.data.id}`)
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail ?? '建立失敗')
  } finally {
    d.loading = false
  }
}

function openDuplicate(row: Config) {
  duplicateDialog.value = {
    visible: true,
    loading: false,
    sourceId: row.id,
    name: `${row.name}（複製）`,
  }
}

async function submitDuplicate() {
  const d = duplicateDialog.value
  if (!d.name.trim()) {
    ElMessage.warning('請輸入新名稱')
    return
  }
  d.loading = true
  try {
    const res = await http.post(`/pbi-configs/${d.sourceId}/duplicate`, { name: d.name })
    ElMessage.success('複製成功')
    d.visible = false
    router.push(`/admin/pbi-configs/${res.data.id}`)
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail ?? '複製失敗')
  } finally {
    d.loading = false
  }
}

function openBatchUpdate() {
  batchDialog.value = {
    visible: true,
    loading: false,
    error: '',
    applyWorkspace: false,
    workspace_id: '',
    applyDataset: false,
    dataset_id: '',
    applyColumnAliases: false,
    columnAliasesText: '',
  }
}

async function submitBatchUpdate() {
  const d = batchDialog.value
  d.error = ''
  if (!d.applyWorkspace && !d.applyDataset && !d.applyColumnAliases) {
    d.error = '請至少勾選一個要套用的欄位'
    return
  }
  const body: Record<string, unknown> = { config_ids: selected.value.map((c) => c.id) }
  if (d.applyWorkspace) body.workspace_id = d.workspace_id
  if (d.applyDataset) body.dataset_id = d.dataset_id
  if (d.applyColumnAliases) {
    try {
      const parsed = d.columnAliasesText.trim() ? JSON.parse(d.columnAliasesText) : []
      if (!Array.isArray(parsed)) throw new Error()
      body.column_aliases = parsed
    } catch {
      d.error = '篩選欄位別名格式錯誤，最外層必須是 JSON 陣列'
      return
    }
  }
  d.loading = true
  try {
    await http.patch('/pbi-configs/batch-update', body)
    ElMessage.success('批次修改成功')
    d.visible = false
    selected.value = []
    await load()
  } catch (e: any) {
    d.error = e.response?.data?.detail
      ? (typeof e.response.data.detail === 'string' ? e.response.data.detail : JSON.stringify(e.response.data.detail))
      : '套用失敗'
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

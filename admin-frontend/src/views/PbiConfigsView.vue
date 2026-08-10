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
      <el-table-column label="操作" width="180" align="center">
        <template #default="{ row }">
          <el-button size="small" @click="router.push(`/admin/pbi-configs/${row.id}`)">詳情</el-button>
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

const createDialog = ref({
  visible: false,
  loading: false,
  form: { name: '' },
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

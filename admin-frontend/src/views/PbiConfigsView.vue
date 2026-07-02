<template>
  <el-card>
    <template #header>
      <div style="display: flex; justify-content: space-between; align-items: center">
        <span>PBI 設定列表</span>
        <el-button type="primary" @click="openCreate">新增設定</el-button>
      </div>
    </template>
    <el-table :data="configs" v-loading="loading" border>
      <el-table-column prop="name" label="名稱" width="140" />
      <el-table-column prop="tenant_id" label="Tenant ID" min-width="160" />
      <el-table-column prop="client_id" label="Client ID" min-width="160" />
      <el-table-column prop="workspace_id" label="Workspace ID" min-width="160">
        <template #default="{ row }">{{ row.workspace_id || '—' }}</template>
      </el-table-column>
      <el-table-column prop="dataset_id" label="Dataset ID" min-width="160">
        <template #default="{ row }">{{ row.dataset_id || '—' }}</template>
      </el-table-column>
      <el-table-column label="操作" width="100" align="center">
        <template #default="{ row }">
          <el-button size="small" @click="openEdit(row)">編輯</el-button>
        </template>
      </el-table-column>
    </el-table>
  </el-card>

  <!-- 新增 Dialog -->
  <el-dialog v-model="createDialog.visible" title="新增 PBI 設定" width="480px">
    <el-form :model="createDialog.form" label-width="120px">
      <el-form-item label="名稱" required>
        <el-input v-model="createDialog.form.name" />
      </el-form-item>
      <el-form-item label="Tenant ID" required>
        <el-input v-model="createDialog.form.tenant_id" />
      </el-form-item>
      <el-form-item label="Client ID" required>
        <el-input v-model="createDialog.form.client_id" />
      </el-form-item>
      <el-form-item label="Client Secret" required>
        <el-input v-model="createDialog.form.client_secret" type="password" show-password />
      </el-form-item>
      <el-form-item label="Workspace ID">
        <el-input v-model="createDialog.form.workspace_id" />
      </el-form-item>
      <el-form-item label="Dataset ID">
        <el-input v-model="createDialog.form.dataset_id" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="createDialog.visible = false">取消</el-button>
      <el-button type="primary" :loading="createDialog.loading" @click="submitCreate">建立</el-button>
    </template>
  </el-dialog>

  <!-- 編輯 Dialog -->
  <el-dialog v-model="editDialog.visible" title="編輯 PBI 設定" width="480px">
    <el-form :model="editDialog.form" label-width="120px">
      <el-form-item label="名稱">
        <el-input :value="editDialog.name" disabled />
      </el-form-item>
      <el-form-item label="Tenant ID">
        <el-input v-model="editDialog.form.tenant_id" />
      </el-form-item>
      <el-form-item label="Client ID">
        <el-input v-model="editDialog.form.client_id" />
      </el-form-item>
      <el-form-item label="Client Secret">
        <el-input v-model="editDialog.form.client_secret" type="password" show-password placeholder="留空表示不修改" />
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
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import http from '@/api/http'

interface Config {
  id: string
  name: string
  tenant_id: string
  client_id: string
  workspace_id: string | null
  dataset_id: string | null
}

const configs = ref<Config[]>([])
const loading = ref(false)

const createDialog = ref({
  visible: false,
  loading: false,
  form: { name: '', tenant_id: '', client_id: '', client_secret: '', workspace_id: '', dataset_id: '' },
})

const editDialog = ref({
  visible: false,
  loading: false,
  configId: '',
  name: '',
  form: { tenant_id: '', client_id: '', client_secret: '', workspace_id: '', dataset_id: '' },
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
    form: { name: '', tenant_id: '', client_id: '', client_secret: '', workspace_id: '', dataset_id: '' },
  }
}

function openEdit(row: Config) {
  editDialog.value = {
    visible: true,
    loading: false,
    configId: row.id,
    name: row.name,
    form: {
      tenant_id: row.tenant_id,
      client_id: row.client_id,
      client_secret: '',
      workspace_id: row.workspace_id ?? '',
      dataset_id: row.dataset_id ?? '',
    },
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

onMounted(load)
</script>

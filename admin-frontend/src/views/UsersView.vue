<template>
  <el-card>
    <el-table :data="users" v-loading="loading" border>
      <el-table-column prop="email" label="Email" min-width="200" />
      <el-table-column label="狀態" width="90" align="center">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'danger'">
            {{ row.is_active ? '已開通' : '未開通' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="PBI 設定" min-width="140">
        <template #default="{ row }">
          {{ configName(row.pbi_config_id) || '—' }}
        </template>
      </el-table-column>
      <el-table-column label="到期時間" min-width="160">
        <template #default="{ row }">{{ fmtDate(row.expires_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="200" align="center">
        <template #default="{ row }">
          <el-button
            size="small"
            :type="row.is_active ? 'warning' : 'success'"
            @click="toggleActive(row)"
          >
            {{ row.is_active ? '停用' : '開通' }}
          </el-button>
          <el-button size="small" @click="openAssign(row)">指派設定</el-button>
        </template>
      </el-table-column>
    </el-table>
  </el-card>

  <el-dialog v-model="assignDialog.visible" title="指派 PBI 設定" width="400px">
    <el-form label-width="90px">
      <el-form-item label="PBI 設定">
        <el-select v-model="assignDialog.configId" placeholder="選擇設定" clearable style="width: 100%">
          <el-option
            v-for="c in configs"
            :key="c.id"
            :label="c.name"
            :value="c.id"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="到期時間">
        <el-date-picker
          v-model="assignDialog.expiresAt"
          type="datetime"
          placeholder="選填"
          style="width: 100%"
        />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="assignDialog.visible = false">取消</el-button>
      <el-button type="primary" :loading="assignDialog.loading" @click="submitAssign">確認</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import http from '@/api/http'

interface User {
  id: string
  email: string
  is_active: boolean
  pbi_config_id: string | null
  expires_at: string | null
}
interface Config { id: string; name: string }

const users = ref<User[]>([])
const configs = ref<Config[]>([])
const loading = ref(false)

const assignDialog = ref({
  visible: false,
  loading: false,
  user: null as User | null,
  configId: '',
  expiresAt: null as Date | null,
})

async function load() {
  loading.value = true
  try {
    const [u, c] = await Promise.all([http.get('/users'), http.get('/pbi-configs')])
    users.value = u.data
    configs.value = c.data
  } finally {
    loading.value = false
  }
}

function configName(id: string | null) {
  return configs.value.find((c) => c.id === id)?.name ?? ''
}

function fmtDate(d: string | null) {
  return d ? new Date(d).toLocaleString() : '—'
}

async function toggleActive(row: User) {
  try {
    await http.patch('/users/activate', { email: row.email, is_active: !row.is_active })
    ElMessage.success(`${!row.is_active ? '開通' : '停用'} ${row.email} 成功`)
    await load()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail ?? '操作失敗')
  }
}

function openAssign(row: User) {
  assignDialog.value = {
    visible: true,
    loading: false,
    user: row,
    configId: row.pbi_config_id ?? '',
    expiresAt: row.expires_at ? new Date(row.expires_at) : null,
  }
}

async function submitAssign() {
  const d = assignDialog.value
  if (!d.user) return
  d.loading = true
  try {
    await http.patch('/users/activate', {
      email: d.user.email,
      is_active: d.user.is_active,
      pbi_config_id: d.configId || null,
      expires_at: d.expiresAt?.toISOString() ?? null,
    })
    ElMessage.success('指派成功')
    d.visible = false
    await load()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail ?? '操作失敗')
  } finally {
    d.loading = false
  }
}

onMounted(load)
</script>

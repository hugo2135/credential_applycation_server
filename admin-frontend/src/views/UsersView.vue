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
      <el-table-column label="Azure AD 憑證" width="110" align="center">
        <template #default="{ row }">
          <el-tag :type="row.has_credentials ? 'success' : 'info'" size="small">
            {{ row.has_credentials ? '已設定' : '未設定' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="已分配語意模型" min-width="180">
        <template #default="{ row }">
          <template v-if="row.pbi_config_ids?.length">
            <el-tag
              v-for="id in row.pbi_config_ids"
              :key="id"
              size="small"
              style="margin: 2px"
            >
              {{ configName(id) }}
            </el-tag>
          </template>
          <span v-else style="color: #c0c4cc; font-size: 13px">尚未分配</span>
        </template>
      </el-table-column>
      <el-table-column label="到期時間" min-width="150">
        <template #default="{ row }">{{ fmtDate(row.expires_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="360" align="center">
        <template #default="{ row }">
          <el-button
            size="small"
            :type="row.is_active ? 'warning' : 'success'"
            @click="toggleActive(row)"
          >
            {{ row.is_active ? '停用' : '開通' }}
          </el-button>
          <el-button size="small" @click="openCredentials(row)">設定憑證</el-button>
          <el-button size="small" @click="openAssign(row)">指派模型</el-button>
          <el-popconfirm
            title="重設後使用者需重新至 Dashboard 領取新的 Key，確定？"
            @confirm="resetMaskKey(row)"
          >
            <template #reference>
              <el-button size="small" type="info" plain>重設 Key</el-button>
            </template>
          </el-popconfirm>
          <el-popconfirm
            title="確定刪除此使用者？此操作無法復原。"
            confirm-button-type="danger"
            @confirm="deleteUser(row)"
          >
            <template #reference>
              <el-button size="small" type="danger" plain>刪除</el-button>
            </template>
          </el-popconfirm>
        </template>
      </el-table-column>
    </el-table>
  </el-card>

  <!-- 設定 Azure AD 憑證 dialog -->
  <el-dialog v-model="credDialog.visible" title="設定 Azure AD 憑證" width="440px">
    <el-alert type="info" :closable="false" style="margin-bottom: 16px">
      <template #title>每位使用者各自的 Azure AD Service Principal 憑證</template>
    </el-alert>
    <el-form :model="credDialog.form" label-width="120px">
      <el-form-item label="Tenant ID" required>
        <el-input v-model="credDialog.form.tenant_id" />
      </el-form-item>
      <el-form-item label="Client ID" required>
        <el-input v-model="credDialog.form.client_id" />
      </el-form-item>
      <el-form-item label="Client Secret" required>
        <el-input
          v-model="credDialog.form.client_secret"
          type="password"
          show-password
          placeholder="填入即更新，留空則取消"
        />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="credDialog.visible = false">取消</el-button>
      <el-button type="primary" :loading="credDialog.loading" @click="submitCredentials">儲存</el-button>
    </template>
  </el-dialog>

  <!-- 指派語意模型 dialog -->
  <el-dialog v-model="assignDialog.visible" title="指派語意模型" width="440px">
    <el-form label-width="90px">
      <el-form-item label="PBI 設定">
        <el-select
          v-model="assignDialog.configIds"
          multiple
          collapse-tags
          collapse-tags-tooltip
          placeholder="選擇一或多個設定"
          style="width: 100%"
        >
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
  has_credentials: boolean
  pbi_config_ids: string[]
  expires_at: string | null
}
interface Config { id: string; name: string }

const users = ref<User[]>([])
const configs = ref<Config[]>([])
const loading = ref(false)

const credDialog = ref({
  visible: false,
  loading: false,
  userId: '',
  form: { tenant_id: '', client_id: '', client_secret: '' },
})

const assignDialog = ref({
  visible: false,
  loading: false,
  user: null as User | null,
  configIds: [] as string[],
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

function configName(id: string) {
  return configs.value.find((c) => c.id === id)?.name ?? id
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

function openCredentials(row: User) {
  credDialog.value = {
    visible: true,
    loading: false,
    userId: row.id,
    form: { tenant_id: '', client_id: '', client_secret: '' },
  }
}

async function submitCredentials() {
  const d = credDialog.value
  if (!d.form.tenant_id || !d.form.client_id || !d.form.client_secret) {
    ElMessage.warning('三個欄位皆為必填')
    return
  }
  d.loading = true
  try {
    await http.patch(`/users/${d.userId}/credentials`, d.form)
    ElMessage.success('Azure AD 憑證設定成功')
    d.visible = false
    await load()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail ?? '設定失敗')
  } finally {
    d.loading = false
  }
}

function openAssign(row: User) {
  assignDialog.value = {
    visible: true,
    loading: false,
    user: row,
    configIds: [...(row.pbi_config_ids ?? [])],
    expiresAt: row.expires_at ? new Date(row.expires_at) : null,
  }
}

async function submitAssign() {
  const d = assignDialog.value
  if (!d.user) return
  d.loading = true
  try {
    await Promise.all([
      http.put(`/users/${d.user.id}/pbi-configs`, { pbi_config_ids: d.configIds }),
      http.patch('/users/activate', {
        email: d.user.email,
        is_active: d.user.is_active,
        expires_at: d.expiresAt?.toISOString() ?? null,
      }),
    ])
    ElMessage.success('指派成功')
    d.visible = false
    await load()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail ?? '操作失敗')
  } finally {
    d.loading = false
  }
}

async function resetMaskKey(row: User) {
  try {
    await http.post(`/users/${row.id}/reset-mask-key`, {})
    ElMessage.success(`${row.email} 的 PBI_MASK_KEY 已重設`)
    await load()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail ?? '重設失敗')
  }
}

async function deleteUser(row: User) {
  try {
    await http.delete(`/users/${row.id}`)
    ElMessage.success(`已刪除使用者 ${row.email}`)
    await load()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail ?? '刪除失敗')
  }
}

onMounted(load)
</script>

<template>
  <el-card>
    <el-alert type="info" :closable="false" style="margin-bottom: 16px">
      <template #title>只保留最近 90 天的紀錄，涵蓋 /dashboard、/mcp、/mcp-tokens、/api 等有身份驗證的存取。</template>
    </el-alert>

    <div style="display: flex; gap: 12px; margin-bottom: 16px; flex-wrap: wrap">
      <el-input v-model="filters.email" placeholder="依 Email 搜尋" clearable style="width: 220px" @keyup.enter="load" />
      <el-select v-model="filters.authMethod" placeholder="存取方式" clearable style="width: 160px">
        <el-option label="使用者登入 (SPA)" value="user_session" />
        <el-option label="OAuth (MCP)" value="oauth" />
        <el-option label="Personal Access Token" value="pat" />
        <el-option label="PBI_MASK_KEY (legacy)" value="mask_key" />
      </el-select>
      <el-date-picker
        v-model="filters.range"
        type="datetimerange"
        start-placeholder="起"
        end-placeholder="迄"
        style="width: 340px"
      />
      <el-button type="primary" :loading="loading" @click="load">查詢</el-button>
      <el-button @click="exportCsv">匯出 CSV</el-button>
    </div>

    <el-table :data="logs" v-loading="loading" border>
      <el-table-column label="時間" width="180">
        <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
      </el-table-column>
      <el-table-column prop="email" label="Email" min-width="200">
        <template #default="{ row }">{{ row.email || '—' }}</template>
      </el-table-column>
      <el-table-column label="方式" width="150">
        <template #default="{ row }">
          <el-tag size="small" :type="authMethodTag(row.auth_method)">{{ authMethodLabel(row.auth_method) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="path" label="路徑" min-width="160" />
      <el-table-column label="Method" width="90">
        <template #default="{ row }">{{ row.method || '—' }}</template>
      </el-table-column>
      <el-table-column label="IP" width="140">
        <template #default="{ row }">{{ row.ip_address || '—' }}</template>
      </el-table-column>
      <template #empty>
        <el-empty description="沒有符合條件的紀錄" :image-size="80" />
      </template>
    </el-table>
  </el-card>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import http from '@/api/http'
import { formatDate } from '@/utils/date'

interface AccessLog {
  id: string
  user_id: string | null
  email: string | null
  path: string
  method: string | null
  auth_method: string
  ip_address: string | null
  created_at: string
}

const logs = ref<AccessLog[]>([])
const loading = ref(false)
const filters = ref({
  email: '',
  authMethod: '',
  range: null as [Date, Date] | null,
})

const authMethodLabels: Record<string, string> = {
  user_session: '使用者登入',
  oauth: 'OAuth (MCP)',
  pat: 'PAT',
  mask_key: 'PBI_MASK_KEY',
}
const authMethodTags: Record<string, string> = {
  user_session: 'success',
  oauth: 'primary',
  pat: 'warning',
  mask_key: 'info',
}

function authMethodLabel(m: string) {
  return authMethodLabels[m] ?? m
}
function authMethodTag(m: string) {
  return authMethodTags[m] ?? 'info'
}

function buildParams() {
  const params: Record<string, string> = {}
  if (filters.value.email) params.email = filters.value.email
  if (filters.value.authMethod) params.auth_method = filters.value.authMethod
  if (filters.value.range?.[0]) params.start = filters.value.range[0].toISOString()
  if (filters.value.range?.[1]) params.end = filters.value.range[1].toISOString()
  return params
}

async function load() {
  loading.value = true
  try {
    const { data } = await http.get('/access-logs', { params: buildParams() })
    logs.value = data
  } catch {
    ElMessage.error('無法載入存取歷史')
  } finally {
    loading.value = false
  }
}

async function exportCsv() {
  try {
    const res = await http.get('/access-logs/export', { params: buildParams(), responseType: 'blob' })
    const url = URL.createObjectURL(new Blob([res.data]))
    const a = document.createElement('a')
    a.href = url
    a.download = `access-logs-${new Date().toISOString().slice(0, 10)}.csv`
    a.click()
    URL.revokeObjectURL(url)
  } catch {
    ElMessage.error('匯出失敗')
  }
}

onMounted(load)
</script>

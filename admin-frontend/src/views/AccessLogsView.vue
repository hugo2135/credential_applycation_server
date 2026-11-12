<template>
  <el-card>
    <el-alert type="info" :closable="false" style="margin-bottom: 16px">
      <template #title>只保留最近 90 天的紀錄，涵蓋 /dashboard、/mcp、/mcp-tokens、/api 等有身份驗證的存取。Ticket 兌換失敗也會記錄（查無此 ticket 除外）；有 get_query_ticket 卻完全沒有對應的兌換紀錄，代表請求根本沒送到 server（通常是使用者端的權限或網路限制）。伺服器查詢（/mcp/run_query）會記下實際執行的 DAX；腳本查詢的 DAX 是 skill 領 ticket 時自行申報的（記在領取與兌換兩筆），無法保證與實際查詢一致。點「DAX」查看。</template>
    </el-alert>

    <div style="display: flex; gap: 12px; margin-bottom: 16px; flex-wrap: wrap">
      <el-input v-model="filters.email" placeholder="依 Email 搜尋" clearable style="width: 220px" @keyup.enter="load" />
      <el-select v-model="filters.authMethod" placeholder="存取方式" clearable style="width: 160px">
        <el-option label="使用者登入 (SPA)" value="user_session" />
        <el-option label="OAuth (MCP)" value="oauth" />
        <el-option label="Personal Access Token" value="pat" />
        <el-option label="PBI_MASK_KEY (legacy)" value="mask_key" />
        <el-option label="Ticket 兌換" value="ticket" />
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
      <el-table-column label="路徑" min-width="160">
        <template #default="{ row }">
          {{ row.path }}
          <!-- run_query 是實際執行的 DAX；get_query_ticket／ticket 兌換是 skill 自行申報的 -->
          <el-popover v-if="row.query_text" placement="left" :width="520" trigger="click">
            <template #reference>
              <el-button size="small" link type="primary" style="margin-left: 6px">DAX</el-button>
            </template>
            <pre class="dax-text">{{ row.query_text }}</pre>
          </el-popover>
        </template>
      </el-table-column>
      <el-table-column label="結果" min-width="160">
        <template #default="{ row }">
          <el-tag v-if="row.error" size="small" type="danger">失敗</el-tag>
          <span v-if="row.error" style="margin-left: 6px; font-size: 12px; color: #c45656">{{ row.error }}</span>
          <el-tag v-else size="small" type="success">成功</el-tag>
        </template>
      </el-table-column>
      <!-- 只有 MCP tool 與 ticket 兌換量得到耗時，其他紀錄寫在身份驗證當下 -->
      <el-table-column label="耗時" width="90" align="right">
        <template #default="{ row }">{{ formatDuration(row.duration_ms) }}</template>
      </el-table-column>
      <el-table-column label="對象 PBI 設定" min-width="140">
        <template #default="{ row }">{{ row.detail ? configName(row.detail) : '—' }}</template>
      </el-table-column>
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
  detail: string | null
  error: string | null
  query_text: string | null
  duration_ms: number | null
  created_at: string
}

function formatDuration(ms: number | null) {
  if (ms == null) return '—'
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} 秒`
}

const logs = ref<AccessLog[]>([])
const loading = ref(false)
// detail 存的是 pbi_config_id，這裡另外抓一份設定清單把它顯示成看得懂的名稱。
// 後端刻意只存 id：名稱之後改了，歷史紀錄仍然指向同一個設定。
const configNames = ref<Record<string, string>>({})

function configName(id: string) {
  return configNames.value[id] ?? id
}
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
  ticket: 'Ticket 兌換',
}
const authMethodTags: Record<string, string> = {
  user_session: 'success',
  oauth: 'primary',
  pat: 'warning',
  mask_key: 'info',
  ticket: 'primary',
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

async function loadConfigNames() {
  try {
    const { data } = await http.get('/pbi-configs')
    configNames.value = Object.fromEntries(data.map((c: { id: string; name: string }) => [c.id, c.name]))
  } catch {
    // 名稱只是顯示用，抓不到就退回顯示原始 id，不影響主要功能
  }
}

onMounted(async () => {
  await Promise.all([load(), loadConfigNames()])
})
</script>

<style scoped>
.dax-text {
  margin: 0;
  max-height: 360px;
  overflow: auto;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>

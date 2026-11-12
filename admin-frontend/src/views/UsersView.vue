<template>
  <el-card>
    <!-- 批次操作工具列，選取後才出現 -->
    <div v-if="selected.length" style="margin-bottom: 12px; display: flex; align-items: center; gap: 8px">
      <span style="font-size: 13px; color: #666">已選擇 {{ selected.length }} 位使用者</span>
      <el-button size="small" type="success" @click="batchActivate(true)">批次開通</el-button>
      <el-button size="small" type="warning" @click="batchActivate(false)">批次停用</el-button>
      <el-button size="small" @click="openBatchAssign">批次指派 PBI 設定</el-button>
      <el-dropdown trigger="click" @command="batchSetQueryExecution">
        <el-button size="small">
          切換查詢方式<el-icon class="el-icon--right"><ArrowDown /></el-icon>
        </el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="server">改為伺服器查詢</el-dropdown-item>
            <el-dropdown-item command="edge">改為腳本查詢</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
      <el-popconfirm
        title="確定刪除這些使用者？此操作無法復原。"
        confirm-button-type="danger"
        @confirm="batchDelete"
      >
        <template #reference>
          <el-button size="small" type="danger" plain>批次刪除</el-button>
        </template>
      </el-popconfirm>
    </div>

    <el-table :data="users" v-loading="loading" border @selection-change="selected = $event">
      <el-table-column type="selection" width="42" />
      <el-table-column prop="email" label="Email" min-width="200" />
      <el-table-column label="狀態" width="100" align="center">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'danger'">
            {{ row.is_active ? '已開通' : '未開通' }}
          </el-tag>
          <div v-if="row.is_locked" style="margin-top: 4px">
            <el-tag type="warning" size="small">🔒 已鎖定</el-tag>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="Azure AD 憑證" width="150" align="center">
        <template #default="{ row }">
          <el-tag :type="row.has_credentials ? 'success' : 'info'" size="small">
            {{ row.has_credentials ? '已設定' : '未設定' }}
          </el-tag>
          <div v-if="row.has_credentials && secretExpiry(row)" style="margin-top: 4px">
            <el-tag :type="secretExpiry(row)!.type" size="small">{{ secretExpiry(row)!.label }}</el-tag>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="查詢方式" width="110" align="center">
        <template #default="{ row }">
          <el-tag :type="row.query_execution === 'server' ? 'primary' : 'info'" size="small" effect="plain">
            {{ queryExecutionLabel(row.query_execution) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="已分配語意模型" min-width="180">
        <template #default="{ row }">
          <template v-if="row.pbi_config_checks?.length">
            <!-- 燈號：綠＝可查詢、紅＝無法查詢、灰＝未檢測；完整錯誤在「設定 → 指派模型」 -->
            <el-tooltip v-for="c in row.pbi_config_checks" :key="c.pbi_config_id" placement="top">
              <template #content>
                <div style="max-width: 320px; white-space: pre-wrap">{{ checkTooltip(c) }}</div>
              </template>
              <el-tag size="small" style="margin: 2px">
                <span :style="dotStyle(c.check_status)" />{{ configName(c.pbi_config_id) }}
              </el-tag>
            </el-tooltip>
          </template>
          <span v-else style="color: #c0c4cc; font-size: 13px">尚未分配</span>
        </template>
      </el-table-column>
      <el-table-column label="到期時間" min-width="150">
        <template #default="{ row }">{{ fmtDate(row.expires_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="160" align="center">
        <template #default="{ row }">
          <el-button size="small" @click="openSettings(row)">設定</el-button>
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

  <!-- 單一使用者設定：整合開通/停用、Azure AD 憑證、指派模型、重設 Key、解鎖、PAT 管理 -->
  <el-dialog v-model="settingsDialog.visible" :title="`設定 - ${settingsDialog.user?.email ?? ''}`" width="560px">
    <el-tabs v-model="settingsDialog.activeTab">
      <el-tab-pane label="開通/停用" name="activate">
        <el-form label-width="100px">
          <el-form-item label="帳號狀態">
            <el-switch
              v-model="settingsDialog.activateForm.isActive"
              active-text="開通"
              inactive-text="停用"
            />
          </el-form-item>
          <el-form-item label="到期時間">
            <el-date-picker
              v-model="settingsDialog.activateForm.expiresAt"
              type="datetime"
              placeholder="選填"
              style="width: 100%"
            />
          </el-form-item>
        </el-form>
        <el-button type="primary" :loading="settingsDialog.saving" @click="saveActivate">儲存</el-button>
      </el-tab-pane>

      <el-tab-pane label="Azure AD 憑證" name="credentials">
        <el-alert type="info" :closable="false" style="margin-bottom: 16px">
          <template #title>每位使用者各自的 Azure AD Service Principal 憑證</template>
        </el-alert>
        <el-form label-width="120px">
          <el-form-item label="Tenant ID" required>
            <el-input v-model="settingsDialog.credForm.tenant_id" />
          </el-form-item>
          <el-form-item label="Client ID" required>
            <el-input v-model="settingsDialog.credForm.client_id" />
          </el-form-item>
          <el-form-item label="Client Secret" required>
            <el-input
              v-model="settingsDialog.credForm.client_secret"
              type="password"
              show-password
              placeholder="填入即更新，留空則取消"
            />
          </el-form-item>
          <el-form-item label="Secret 到期日">
            <el-date-picker
              v-model="settingsDialog.credForm.client_secret_expires_at"
              type="date"
              placeholder="選填，建議照 Azure 上的到期日填"
              style="width: 100%"
            />
          </el-form-item>
        </el-form>
        <el-alert type="info" :closable="false" style="margin-bottom: 12px">
          <template #title>
            Azure AD 的 client secret 最長 24 個月。到期時使用者只會突然查不了、
            錯誤訊息看不出原因，填了到期日列表才能提前警示。
          </template>
        </el-alert>
        <el-button type="primary" :loading="settingsDialog.saving" @click="saveCredentials">儲存</el-button>
      </el-tab-pane>

      <el-tab-pane label="指派模型" name="assign">
        <el-form label-width="90px">
          <el-form-item label="PBI 設定">
            <el-select
              v-model="settingsDialog.assignConfigIds"
              multiple
              collapse-tags
              collapse-tags-tooltip
              placeholder="選擇一或多個設定"
              style="width: 100%"
            >
              <el-option v-for="c in configs" :key="c.id" :label="c.name" :value="c.id" />
            </el-select>
          </el-form-item>
        </el-form>
        <el-button type="primary" :loading="settingsDialog.saving" @click="saveAssign">儲存</el-button>

        <el-divider content-position="left">查詢權限檢測</el-divider>
        <p style="color: #666; margin-bottom: 12px; font-size: 13px">
          用這位使用者的服務主體，對已儲存的每個模型跑一個最小查詢（不讀取實際資料），確認能不能真的查詢。
          儲存 Azure AD 憑證或指派模型後會自動檢測。
        </p>
        <div v-if="!settingsDialog.checks.length" style="color: #c0c4cc; font-size: 13px">尚未指派任何模型</div>
        <div
          v-for="c in settingsDialog.checks"
          :key="c.pbi_config_id"
          style="border: 1px solid #ebeef5; border-radius: 4px; padding: 10px 12px; margin-bottom: 8px"
        >
          <div style="display: flex; align-items: center; justify-content: space-between; gap: 8px">
            <span>
              <span :style="dotStyle(c.check_status)" /><b>{{ configName(c.pbi_config_id) }}</b>
              <span style="color: #909399; font-size: 12px; margin-left: 8px">
                {{ statusLabel(c.check_status) }}<template v-if="c.checked_at"> · {{ fmtDate(c.checked_at) }}</template>
              </span>
            </span>
            <el-button
              size="small"
              link
              type="primary"
              :loading="settingsDialog.checkingId === c.pbi_config_id"
              :disabled="!!settingsDialog.checkingId"
              @click="runChecks([c.pbi_config_id])"
            >
              重新檢測
            </el-button>
          </div>
          <!-- 完整訊息（白話原因＋原始錯誤），可以選取複製給管理 Azure／Power BI 的人 -->
          <div
            v-if="c.check_status === 'failed' && c.check_message"
            style="margin-top: 6px; font-size: 12px; color: #f56c6c; white-space: pre-wrap; word-break: break-all"
          >{{ c.check_message }}</div>
        </div>
        <el-button
          v-if="settingsDialog.checks.length > 1"
          size="small"
          :loading="settingsDialog.checkingId === 'all'"
          :disabled="!!settingsDialog.checkingId"
          @click="runChecks(null)"
        >
          全部重新檢測
        </el-button>
      </el-tab-pane>

      <el-tab-pane label="查詢方式" name="queryExecution">
        <el-radio-group v-model="settingsDialog.queryExecution" class="mode-options">
          <el-radio value="edge" border>
            <b>腳本查詢</b>
            <span class="mode-desc">AI 端的查詢腳本拿一次性 ticket 自己連 Power BI，沙盒要放行網路</span>
          </el-radio>
          <el-radio value="server" border>
            <b>伺服器查詢</b>
            <span class="mode-desc">由伺服器代查並把結果交給 AI，不需要網路設定；DAX 會記進存取歷史</span>
          </el-radio>
        </el-radio-group>
        <el-alert
          v-if="settingsDialog.queryExecution === 'server'"
          type="warning"
          :closable="false"
          style="margin: 12px 0"
        >
          <template #title>
            這位使用者的 skill 需要已更新到支援伺服器查詢（v2.0 起的 run_query）；舊版 skill 切過去會拿不到查詢授權。
          </template>
        </el-alert>
        <div style="margin-top: 12px">
          <el-button
            type="primary"
            :loading="settingsDialog.saving"
            :disabled="settingsDialog.queryExecution === settingsDialog.user?.query_execution"
            @click="saveQueryExecution"
          >
            儲存
          </el-button>
        </div>
      </el-tab-pane>

      <el-tab-pane label="重設 Key" name="resetKey">
        <p style="color: #666; margin-bottom: 16px; font-size: 14px">
          重設後使用者需重新至 Dashboard 領取新的 PBI_MASK_KEY。
        </p>
        <el-popconfirm title="確定重設此使用者的 PBI_MASK_KEY？" @confirm="resetMaskKey">
          <template #reference>
            <el-button type="warning" plain>重設 Key</el-button>
          </template>
        </el-popconfirm>
      </el-tab-pane>

      <el-tab-pane v-if="settingsDialog.user?.is_locked" label="解鎖" name="unlock">
        <p style="color: #666; margin-bottom: 16px; font-size: 14px">
          帳號因密碼連續錯誤已被鎖定，解鎖後可重新登入。
        </p>
        <el-button type="warning" @click="unlockUser">🔒 解鎖</el-button>
      </el-tab-pane>

      <el-tab-pane label="PAT 管理" name="pat">
        <p style="color: #666; margin-bottom: 16px; font-size: 14px">
          使用者自助產生、給不支援 OAuth 的 MCP client 用的 token。管理員只能查看與撤銷，看不到明文。
        </p>
        <el-table :data="settingsDialog.patTokens" v-loading="settingsDialog.patLoading" size="small">
          <el-table-column prop="name" label="名稱">
            <template #default="{ row }">{{ row.name || '—' }}</template>
          </el-table-column>
          <el-table-column label="建立時間">
            <template #default="{ row }">{{ fmtDate(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="最後使用">
            <template #default="{ row }">{{ row.last_used_at ? fmtDate(row.last_used_at) : '尚未使用' }}</template>
          </el-table-column>
          <el-table-column label="操作" width="80">
            <template #default="{ row }">
              <el-popconfirm title="確定撤銷此 token？" @confirm="revokePat(row.id)">
                <template #reference>
                  <el-button type="danger" size="small" link>撤銷</el-button>
                </template>
              </el-popconfirm>
            </template>
          </el-table-column>
          <template #empty>
            <el-empty description="尚未建立任何 token" :image-size="60" />
          </template>
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <template #footer>
      <el-button @click="settingsDialog.visible = false">關閉</el-button>
    </template>
  </el-dialog>

  <!-- 批次指派 PBI 設定：只會新增，不會動到既有指派 -->
  <el-dialog v-model="batchAssignDialog.visible" title="批次指派 PBI 設定" width="440px">
    <el-alert type="info" :closable="false" style="margin-bottom: 16px">
      <template #title>會新增指派給已選擇的 {{ selected.length }} 位使用者，不會移除他們既有的設定</template>
    </el-alert>
    <el-form label-width="90px">
      <el-form-item label="PBI 設定">
        <el-select
          v-model="batchAssignDialog.configIds"
          multiple
          collapse-tags
          collapse-tags-tooltip
          placeholder="選擇一或多個設定"
          style="width: 100%"
        >
          <el-option v-for="c in configs" :key="c.id" :label="c.name" :value="c.id" />
        </el-select>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="batchAssignDialog.visible = false">取消</el-button>
      <el-button type="primary" :loading="batchAssignDialog.loading" @click="submitBatchAssign">確認</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api/http'
import { formatDate, parseUtcDate } from '@/utils/date'

type CheckStatus = 'ok' | 'failed' | null
interface ConfigCheck {
  pbi_config_id: string
  check_status: CheckStatus
  check_message: string | null
  checked_at: string | null
}
interface User {
  id: string
  email: string
  is_active: boolean
  has_credentials: boolean
  client_secret_expires_at: string | null
  pbi_config_ids: string[]
  pbi_config_checks: ConfigCheck[]
  expires_at: string | null
  is_locked: boolean
  query_execution: QueryExecution
}
type QueryExecution = 'edge' | 'server'
interface Config { id: string; name: string }
interface McpToken {
  id: string
  name: string | null
  created_at: string
  last_used_at: string | null
}

const users = ref<User[]>([])
const configs = ref<Config[]>([])
const loading = ref(false)
const selected = ref<User[]>([])

const settingsDialog = ref({
  visible: false,
  saving: false,
  user: null as User | null,
  activeTab: 'activate',
  activateForm: { isActive: false, expiresAt: null as Date | null },
  credForm: { tenant_id: '', client_id: '', client_secret: '', client_secret_expires_at: null as Date | null },
  assignConfigIds: [] as string[],
  queryExecution: 'edge' as QueryExecution,
  checks: [] as ConfigCheck[],
  checkingId: null as string | null, // 正在檢測的 pbi_config_id，全部檢測時為 'all'
  patTokens: [] as McpToken[],
  patLoading: false,
})

const batchAssignDialog = ref({
  visible: false,
  loading: false,
  configIds: [] as string[],
})

async function load() {
  loading.value = true
  try {
    const [u, c] = await Promise.all([http.get('/users'), http.get('/pbi-configs')])
    users.value = u.data
    configs.value = c.data
    // 設定彈窗開著時，同步最新的使用者資料與檢測結果（不動使用者正在編輯的表單）
    const d = settingsDialog.value
    if (d.visible && d.user) {
      const fresh = users.value.find((x) => x.id === d.user!.id)
      if (fresh) {
        d.user = fresh
        d.checks = fresh.pbi_config_checks ?? []
      }
    }
  } finally {
    loading.value = false
  }
}

// ── 查詢權限檢測 ────────────────────────────────────────────────────

const STATUS_COLORS = { ok: '#67c23a', failed: '#f56c6c', none: '#c0c4cc' }

function dotStyle(status: CheckStatus) {
  return {
    display: 'inline-block',
    width: '8px',
    height: '8px',
    borderRadius: '50%',
    marginRight: '6px',
    verticalAlign: 'middle',
    background: STATUS_COLORS[status ?? 'none'],
  }
}

function statusLabel(status: CheckStatus) {
  return status === 'ok' ? '可查詢' : status === 'failed' ? '無法查詢' : '未檢測'
}

/** 列表 tooltip 只放一句白話原因（訊息第一行）和檢測時間，完整內容在設定彈窗 */
function checkTooltip(c: ConfigCheck) {
  if (!c.check_status) return '未檢測：到「設定 → 指派模型」執行檢測'
  const reason = c.check_status === 'failed' ? `：${(c.check_message ?? '').split('\n')[0]}` : ''
  return `${statusLabel(c.check_status)}${reason}\n檢測時間：${fmtDate(c.checked_at)}`
}

async function runChecks(pbiConfigIds: string[] | null, opts: { auto?: boolean } = {}) {
  const d = settingsDialog.value
  if (!d.user) return
  d.checkingId = pbiConfigIds?.length === 1 ? pbiConfigIds[0]! : 'all'
  try {
    const { data } = await http.post<ConfigCheck[]>(`/users/${d.user.id}/query-check`, {
      pbi_config_ids: pbiConfigIds,
    })
    const failed = data.filter((r) => r.check_status === 'failed').length
    if (!data.length) {
      if (!opts.auto) ElMessage.info('尚未指派任何模型')
    } else if (failed) {
      ElMessage.warning(`${failed} 個模型無法查詢，原因見「指派模型」分頁`)
      d.activeTab = 'assign'
    } else {
      ElMessage.success(`檢測完成：${data.length} 個模型都可以查詢`)
    }
    await load()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail ?? '檢測失敗')
  } finally {
    d.checkingId = null
  }
}

function configName(id: string) {
  return configs.value.find((c) => c.id === id)?.name ?? id
}

function fmtDate(d: string | null) {
  return formatDate(d)
}

const SECRET_EXPIRY_WARNING_DAYS = 30

/** Azure AD client secret 的到期狀態。沒填到期日就不顯示（不是所有人都會維護這欄）。 */
function secretExpiry(row: User): { type: 'danger' | 'warning'; label: string } | null {
  const expiry = parseUtcDate(row.client_secret_expires_at)
  if (!expiry) return null
  const days = Math.ceil((expiry.getTime() - Date.now()) / 86400000)
  if (days < 0) return { type: 'danger', label: 'Secret 已過期' }
  if (days <= SECRET_EXPIRY_WARNING_DAYS) return { type: 'warning', label: `Secret ${days} 天後到期` }
  return null
}

// ── 單一使用者設定彈窗 ──────────────────────────────────────────────

function openSettings(row: User) {
  settingsDialog.value = {
    visible: true,
    saving: false,
    user: row,
    activeTab: 'activate',
    activateForm: { isActive: row.is_active, expiresAt: parseUtcDate(row.expires_at) },
    credForm: {
      tenant_id: '', client_id: '', client_secret: '',
      client_secret_expires_at: parseUtcDate(row.client_secret_expires_at),
    },
    assignConfigIds: [...(row.pbi_config_ids ?? [])],
    queryExecution: row.query_execution,
    checks: row.pbi_config_checks ?? [],
    checkingId: null,
    patTokens: [],
    patLoading: false,
  }
  loadPatTokens(row.id)
}

async function loadPatTokens(userId: string) {
  settingsDialog.value.patLoading = true
  try {
    const { data } = await http.get(`/users/${userId}/mcp-tokens`)
    settingsDialog.value.patTokens = data
  } catch {
    ElMessage.error('無法載入 token 清單')
  } finally {
    settingsDialog.value.patLoading = false
  }
}

async function revokePat(tokenId: string) {
  const userId = settingsDialog.value.user?.id
  if (!userId) return
  try {
    await http.delete(`/users/${userId}/mcp-tokens/${tokenId}`)
    ElMessage.success('已撤銷')
    await loadPatTokens(userId)
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail ?? '撤銷失敗')
  }
}

async function saveActivate() {
  const d = settingsDialog.value
  if (!d.user) return
  d.saving = true
  try {
    await http.patch('/users/activate', {
      email: d.user.email,
      is_active: d.activateForm.isActive,
      expires_at: d.activateForm.expiresAt?.toISOString() ?? null,
    })
    ElMessage.success('已儲存')
    await load()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail ?? '操作失敗')
  } finally {
    d.saving = false
  }
}

async function saveCredentials() {
  const d = settingsDialog.value
  if (!d.user) return
  if (!d.credForm.tenant_id || !d.credForm.client_id || !d.credForm.client_secret) {
    ElMessage.warning('三個欄位皆為必填')
    return
  }
  d.saving = true
  try {
    await http.patch(`/users/${d.user.id}/credentials`, {
      ...d.credForm,
      client_secret_expires_at: d.credForm.client_secret_expires_at?.toISOString() ?? null,
    })
    ElMessage.success('Azure AD 憑證設定成功')
    await load()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail ?? '設定失敗')
    return
  } finally {
    d.saving = false
  }
  // 憑證換了，所有模型的舊結果都已被後端重置，全部重新檢測
  await runChecks(null, { auto: true })
}

async function saveAssign() {
  const d = settingsDialog.value
  if (!d.user) return
  d.saving = true
  try {
    await http.put(`/users/${d.user.id}/pbi-configs`, { pbi_config_ids: d.assignConfigIds })
    ElMessage.success('指派成功')
    await load()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail ?? '操作失敗')
    return
  } finally {
    d.saving = false
  }
  // 只檢測還沒有結果的（新指派的），原本就檢測過的模型保留結果
  const pending = d.checks.filter((c) => !c.check_status).map((c) => c.pbi_config_id)
  if (pending.length) await runChecks(pending, { auto: true })
}

// ── 查詢方式（腳本查詢 edge／伺服器查詢 server） ─────────────────────

function queryExecutionLabel(mode: QueryExecution) {
  return mode === 'server' ? '伺服器查詢' : '腳本查詢'
}

async function setQueryExecution(userIds: string[], mode: QueryExecution) {
  const { data } = await http.post('/users/batch-query-execution', { user_ids: userIds, query_execution: mode })
  ElMessage.success(data.message)
  await load()
}

async function saveQueryExecution() {
  const d = settingsDialog.value
  if (!d.user) return
  d.saving = true
  try {
    await setQueryExecution([d.user.id], d.queryExecution)
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail ?? '切換失敗')
  } finally {
    d.saving = false
  }
}

async function batchSetQueryExecution(mode: QueryExecution) {
  if (!selected.value.length) return
  const warning = mode === 'server'
    ? '這些使用者的 skill 需要已更新到支援伺服器查詢（v2.0 起的 run_query），舊版 skill 切過去會拿不到查詢授權。'
    : '切換後這些使用者的 AI 會改用查詢腳本自行連 Power BI，沙盒需要放行網路。'
  try {
    await ElMessageBox.confirm(
      `將 ${selected.value.length} 位使用者改為「${queryExecutionLabel(mode)}」？\n${warning}`,
      '切換查詢方式',
      { type: 'warning', confirmButtonText: '切換', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await setQueryExecution(selected.value.map((u) => u.id), mode)
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail ?? '批次切換失敗')
  }
}

async function resetMaskKey() {
  const user = settingsDialog.value.user
  if (!user) return
  try {
    await http.post(`/users/${user.id}/reset-mask-key`, {})
    ElMessage.success(`${user.email} 的 PBI_MASK_KEY 已重設`)
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail ?? '重設失敗')
  }
}

async function unlockUser() {
  const user = settingsDialog.value.user
  if (!user) return
  try {
    await http.post(`/users/${user.id}/unlock`, {})
    ElMessage.success(`${user.email} 已解鎖`)
    settingsDialog.value.visible = false
    await load()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail ?? '解鎖失敗')
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

// ── 批次操作 ────────────────────────────────────────────────────────

async function batchActivate(isActive: boolean) {
  if (!selected.value.length) return
  try {
    await http.post('/users/batch-activate', {
      user_ids: selected.value.map((u) => u.id),
      is_active: isActive,
    })
    ElMessage.success(`已${isActive ? '開通' : '停用'} ${selected.value.length} 位使用者`)
    await load()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail ?? '批次操作失敗')
  }
}

function openBatchAssign() {
  batchAssignDialog.value = { visible: true, loading: false, configIds: [] }
}

async function submitBatchAssign() {
  if (!batchAssignDialog.value.configIds.length) {
    ElMessage.warning('請至少選擇一個 PBI 設定')
    return
  }
  batchAssignDialog.value.loading = true
  try {
    await http.put('/users/batch-pbi-configs', {
      user_ids: selected.value.map((u) => u.id),
      pbi_config_ids: batchAssignDialog.value.configIds,
    })
    ElMessage.success('批次指派成功')
    batchAssignDialog.value.visible = false
    await load()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail ?? '批次指派失敗')
  } finally {
    batchAssignDialog.value.loading = false
  }
}

async function batchDelete() {
  if (!selected.value.length) return
  try {
    await http.post('/users/batch-delete', { user_ids: selected.value.map((u) => u.id) })
    ElMessage.success(`已刪除 ${selected.value.length} 位使用者`)
    selected.value = []
    await load()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail ?? '批次刪除失敗')
  }
}

onMounted(load)
</script>

<style scoped>
.mode-options {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 8px;
}
.mode-options :deep(.el-radio) {
  height: auto;
  margin-right: 0;
  padding: 10px 12px;
  white-space: normal;
}
.mode-desc {
  display: block;
  margin-top: 2px;
  font-size: 12px;
  color: #909399;
}
</style>

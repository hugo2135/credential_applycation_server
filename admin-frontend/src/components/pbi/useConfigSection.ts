import { reactive } from 'vue'
import { ElMessage } from 'element-plus'
import http from '@/api/http'

interface SectionOptions<T> {
  configId: string
  /** PATCH /pbi-configs/{id} body 裡的欄位名稱，例如 filters */
  field: string
  label: string
  normalize: (raw: any) => T
  clean: (item: T) => unknown
  /** 回傳錯誤訊息清單，空陣列代表通過 */
  validate: (items: T[]) => string[]
  onSaved?: () => Promise<void> | void
}

/**
 * 詳情頁三個 JSON 欄位（篩選規則／查詢模式／欄位別名）共用的編輯邏輯：
 * 預設用表單編輯，可切換成原始 JSON（進階），兩邊來回切換時互相同步。
 */
export function useConfigSection<T>(opts: SectionOptions<T>) {
  const state = reactive({
    items: [] as T[],
    text: '',
    jsonMode: false,
    errors: [] as string[],
    saving: false,
  })

  function load(raw: unknown[] | null | undefined) {
    state.items = (raw ?? []).map(opts.normalize) as any
    state.text = toText()
    state.errors = []
  }

  function toText() {
    const cleaned = (state.items as T[]).map(opts.clean)
    return cleaned.length ? JSON.stringify(cleaned, null, 2) : ''
  }

  function parseText(): T[] | null {
    if (!state.text.trim()) return []
    try {
      const parsed = JSON.parse(state.text)
      if (!Array.isArray(parsed)) throw new Error()
      return parsed.map(opts.normalize)
    } catch {
      state.errors = [`${opts.label}格式錯誤，最外層必須是 JSON 陣列`]
      return null
    }
  }

  function setJsonMode(on: boolean) {
    state.errors = []
    if (on) {
      state.text = toText()
      state.jsonMode = true
      return
    }
    const parsed = parseText()
    if (parsed === null) return // JSON 有錯就留在 JSON 模式，不要把內容洗掉
    state.items = parsed as any
    state.jsonMode = false
  }

  async function save() {
    state.errors = []
    if (state.jsonMode) {
      const parsed = parseText()
      if (parsed === null) return
      state.items = parsed as any
    }
    const errors = opts.validate(state.items as T[])
    if (errors.length) {
      state.errors = errors
      return
    }
    state.saving = true
    try {
      await http.patch(`/pbi-configs/${opts.configId}`, { [opts.field]: (state.items as T[]).map(opts.clean) })
      ElMessage.success(`${opts.label}已儲存`)
      await opts.onSaved?.()
    } catch (e: any) {
      const detail = e.response?.data?.detail
      state.errors = [detail ? (typeof detail === 'string' ? detail : JSON.stringify(detail)) : '儲存失敗']
    } finally {
      state.saving = false
    }
  }

  return { state, load, setJsonMode, save }
}

export function duplicates(values: string[]) {
  const seen = new Set<string>()
  const dup = new Set<string>()
  for (const v of values) (seen.has(v) ? dup : seen).add(v)
  return [...dup]
}

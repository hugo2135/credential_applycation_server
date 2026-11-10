import { ref, type Ref } from 'vue'
import { itemKey } from './types'

/** 三個編輯器共用的折疊狀態：既有項目預設收合，新增的項目自動展開。 */
export function useCollapse<T extends object>(items: Ref<T[]>) {
  const open = ref<string[]>([])

  function add(item: T) {
    items.value.push(item)
    // push 進 reactive 陣列後要用陣列裡的 proxy 取 key，跟 template 裡拿到的才會是同一個物件
    open.value.push(itemKey(items.value[items.value.length - 1]!))
  }

  function expandAll() {
    open.value = items.value.map(itemKey)
  }

  function collapseAll() {
    open.value = []
  }

  return { open, add, expandAll, collapseAll, itemKey }
}

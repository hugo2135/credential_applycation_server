<template>
  <div>
    <el-empty v-if="!model.length" description="還沒有設定欄位別名" :image-size="60" />

    <template v-else>
      <div class="toolbar">
        <el-button text size="small" @click="expandAll">全部展開</el-button>
        <el-button text size="small" @click="collapseAll">全部收合</el-button>
      </div>
      <el-collapse v-model="open" class="items">
        <el-collapse-item v-for="(g, i) in model" :key="itemKey(g)" :name="itemKey(g)">
          <template #title>
            <div class="item-title">
              <span>
                <b>{{ g.table && g.column ? `${g.table}[${g.column}]` : '（尚未選擇欄位）' }}</b>
                <span class="summary">{{ g.values.length }} 個值</span>
              </span>
              <span @click.stop>
                <el-popconfirm title="確定刪除這個欄位的別名？" confirm-button-type="danger" @confirm="model.splice(i, 1)">
                  <template #reference><el-button text type="danger" size="small">刪除</el-button></template>
                </el-popconfirm>
              </span>
            </div>
          </template>

          <div class="item-body">
            <div style="display: flex; gap: 8px; margin-bottom: 12px">
              <el-select
                v-model="g.table"
                filterable
                allow-create
                default-first-option
                placeholder="資料表"
                style="flex: 1"
                @change="g.column = ''"
              >
                <el-option v-for="t in tables" :key="t.table" :label="t.table" :value="t.table" />
              </el-select>
              <el-select
                v-model="g.column"
                filterable
                allow-create
                default-first-option
                placeholder="欄位"
                style="flex: 1"
              >
                <el-option v-for="c in columnsOf(g.table)" :key="c" :label="c" :value="c" />
              </el-select>
            </div>

            <el-table :data="g.values" border size="small">
              <el-table-column label="資料裡實際存的值" width="240">
                <template #default="{ row }">
                  <el-input v-model="row.value" placeholder="例：North" size="small" />
                </template>
              </el-table-column>
              <el-table-column label="使用者可能的說法">
                <template #default="{ row }">
                  <TagInput v-model="row.aliases" placeholder="例：北區、北部，輸入後按 Enter" />
                </template>
              </el-table-column>
              <el-table-column width="70" align="center">
                <template #default="{ $index }">
                  <el-button text type="danger" size="small" @click="g.values.splice($index, 1)">刪除</el-button>
                </template>
              </el-table-column>
              <template #empty>還沒有值</template>
            </el-table>
            <el-button size="small" style="margin-top: 8px" @click="g.values.push({ value: '', aliases: [] })">
              ＋ 新增一個值
            </el-button>
          </div>
        </el-collapse-item>
      </el-collapse>
    </template>

    <el-button type="primary" plain @click="add({ table: '', column: '', values: [{ value: '', aliases: [] }] })">
      ＋ 新增欄位
    </el-button>
  </div>
</template>

<script setup lang="ts">
import TagInput from './TagInput.vue'
import type { ColumnAliasGroup, SchemaTable } from './types'
import { useCollapse } from './useCollapse'

const model = defineModel<ColumnAliasGroup[]>({ required: true })
const props = defineProps<{ tables: SchemaTable[] }>()
const { open, add, expandAll, collapseAll, itemKey } = useCollapse(model)

function columnsOf(table: string) {
  return props.tables.find((t) => t.table === table)?.columns ?? []
}
</script>

<style scoped>
@import './editor.css';
</style>

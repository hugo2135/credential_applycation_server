<template>
  <div>
    <div v-for="(rule, i) in model" :key="i" class="rule-row">
      <div class="rule-fields">
        <el-input v-model="rule.description" placeholder="這條條件在做什麼，例：排除退貨單" />
        <el-input
          v-model="rule.expression"
          type="textarea"
          :autosize="{ minRows: 1, maxRows: 4 }"
          placeholder='DAX 布林運算式，例：Orders[order_type] <> "return_order"'
          class="mono"
        />
        <el-select
          v-model="rule.requiredTable"
          clearable
          filterable
          allow-create
          default-first-option
          placeholder="（選填）只有查詢用到這張表時才套用"
          style="width: 100%"
        >
          <el-option v-for="t in tables" :key="t" :label="t" :value="t" />
        </el-select>
      </div>
      <el-button text type="danger" @click="model.splice(i, 1)">刪除</el-button>
    </div>
    <el-button size="small" @click="model.push({ description: '', expression: '', requiredTable: null })">
      ＋ 新增一條篩選條件
    </el-button>
  </div>
</template>

<script setup lang="ts">
import type { FilterRule } from './types'

const model = defineModel<FilterRule[]>({ required: true })
defineProps<{ tables: string[] }>()
</script>

<style scoped>
.rule-row {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  padding: 10px;
  margin-bottom: 8px;
  border: 1px dashed var(--el-border-color);
  border-radius: 4px;
}
.rule-fields {
  flex: 1;
  display: grid;
  gap: 6px;
}
.mono :deep(textarea) {
  font-family: monospace;
  font-size: 12px;
}
</style>

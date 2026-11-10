<template>
  <!-- 沒有選項的 multiple + allow-create select，當成「打字按 Enter 變一個標籤」的輸入框用 -->
  <el-select
    v-model="model"
    multiple
    filterable
    allow-create
    default-first-option
    :reserve-keyword="false"
    :placeholder="placeholder ?? '輸入後按 Enter 新增'"
    style="width: 100%"
  >
    <el-option v-for="opt in options ?? []" :key="opt" :label="opt" :value="opt" />
  </el-select>
</template>

<script setup lang="ts">
const model = defineModel<string[]>({ required: true })
defineProps<{ placeholder?: string; options?: string[] }>()
</script>

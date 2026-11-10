<template>
  <span v-if="!versions.length" class="warn">尚未上傳語意模型，資料表與欄位需要手動輸入名稱。</span>
  <span v-else class="source">
    下拉選單的資料表來自
    <el-select v-model="selected" size="small" style="width: 210px">
      <el-option
        v-for="v in versions"
        :key="v"
        :value="v"
        :label="v === servingVersion ? `版本 ${v}（MCP 提供中）` : `版本 ${v}`"
      />
    </el-select>
    <span v-if="selected !== servingVersion" class="warn">AI 目前拿到的不是這一版，選到的表要切換版本後才會生效</span>
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ versions: number[]; servingVersion: number | null }>()
// null = 跟著 MCP 提供的版本
const model = defineModel<number | null>({ required: true })

const selected = computed({
  get: () => model.value ?? props.servingVersion,
  set: (v) => (model.value = v === props.servingVersion ? null : v),
})
</script>

<style scoped>
.source {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.warn {
  font-size: 12px;
  color: var(--el-color-warning);
}
</style>

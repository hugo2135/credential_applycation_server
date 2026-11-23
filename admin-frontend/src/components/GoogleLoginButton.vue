<template>
  <template v-if="visible">
    <!-- 整頁導向（不是 fetch）：要讓瀏覽器帶著 state cookie 跳去 Google 再回來 -->
    <a class="google-btn" :href="`/oauth/google/start?flow=${flow}`">{{ label }}</a>
    <div class="divider">或使用{{ flow === 'admin' ? ' Admin Secret' : '帳號密碼' }}</div>
  </template>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import axios from 'axios'

const props = defineProps<{ flow: 'user' | 'admin'; label?: string }>()

const status = ref({ enabled: false, admin_enabled: false })
const visible = computed(() => (props.flow === 'admin' ? status.value.admin_enabled : status.value.enabled))
const label = computed(() => props.label ?? '用 Google 登入')

onMounted(async () => {
  try {
    const { data } = await axios.get('/oauth/google/status')
    status.value = data
  } catch {
    // 拿不到就不顯示按鈕，帳密登入照常
  }
})
</script>

<style scoped>
.google-btn {
  display: block;
  padding: 9px;
  text-align: center;
  border: 1px solid #dadce0;
  border-radius: 4px;
  color: #3c4043;
  text-decoration: none;
  font-weight: 500;
  font-size: 14px;
}
.google-btn:hover {
  background: #f8f9fa;
}
.divider {
  margin: 18px 0 14px;
  font-size: 12px;
  color: #909399;
  text-align: center;
}
</style>

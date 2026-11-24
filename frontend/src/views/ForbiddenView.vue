<template>
  <el-result icon="warning" title="无访问权限" sub-title="当前角色不具备访问该页面的能力，如需访问请联系项目管理员。">
    <template #extra>
      <el-button type="primary" @click="router.replace('/overview')">返回总览</el-button>
    </template>
  </el-result>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'
const router = useRouter()
</script>

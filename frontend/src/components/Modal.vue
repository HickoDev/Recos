<template>
  <div v-if="open" class="backdrop" @click.self="emit('close')">
    <div class="panel" role="dialog" aria-modal="true">
      <header class="head">
        <h3>{{ title }}</h3>
        <button class="x" @click="emit('close')" aria-label="Close">✕</button>
      </header>
      <section class="body">
        <slot />
      </section>
    </div>
  </div>
  
</template>
<script setup lang="ts">
const props = defineProps<{ open: boolean; title: string }>();
const emit = defineEmits<{ (e:'close'): void }>();
</script>
<style scoped>
.backdrop{ position:fixed; inset:0; background:rgba(0,0,0,.55); display:flex; align-items:center; justify-content:center; padding:32px; z-index:1000; }
.panel{ width:min(920px, 96vw); max-height:85vh; background:#1b2029; border:1px solid #2a313d; border-radius:12px; box-shadow:0 10px 40px rgba(0,0,0,.6); display:grid; grid-template-rows:auto 1fr; overflow:hidden; }
.head{ display:flex; align-items:center; justify-content:space-between; padding:12px 14px; border-bottom:1px solid #2a313d; }
.head h3{ margin:0; font-size:16px; }
.x{ background:transparent; border:none; color:#8892a0; cursor:pointer; font-size:16px; }
.body{ padding:12px 14px; overflow:auto; }
pre{ background:#11161d; padding:12px; border-radius:8px; max-height:70vh; overflow:auto; }
a{ color:#3d82f7; }
table{ width:100%; border-collapse: collapse; font-size:13px; }
th,td{ padding:6px 8px; text-align:left; }
thead th{ position:sticky; top:0; background:#222834; }
tr:nth-child(even){ background:#20262f; }
</style>

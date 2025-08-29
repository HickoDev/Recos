<template>
  <section class="card">
    <div class="row">
      <label>Batch</label>
      <select v-model="selected" @change="$emit('changeBatch', selected)">
        <option v-for="b in batches" :key="b" :value="b">{{ b }}</option>
      </select>
      <button class="btn" @click="refresh">Refresh</button>
      <span style="flex:1"></span>
      <button class="btn" :disabled="!selected" @click="openLog">View log</button>
      <button class="btn" :disabled="!selected" @click="openMail">View mail</button>
    </div>
    <div class="stats">
      <div class="stat"><strong>{{ stats.devices }}</strong><small>devices</small></div>
      <div class="stat"><strong>{{ stats.upgrades }}</strong><small>need action</small></div>
      <div class="stat"><strong>{{ stats.critical }}</strong><small>with Critical CVEs</small></div>
    </div>
  </section>
  <Modal :open="modals.log" title="Pipeline log" @close="modals.log=false">
    <div style="margin-bottom:8px; display:flex; gap:8px; align-items:center;">
      <a class="btn btn-xs" :href="selected ? `/api/batch/${selected}/log` : '#'" target="_blank" rel="noopener" :aria-disabled="!selected">Open raw</a>
    </div>
    <pre style="white-space: pre-wrap;">{{ logText || 'No log available' }}</pre>
  </Modal>
  <Modal :open="modals.mail" title="Notification mail" @close="modals.mail=false">
    <div style="margin-bottom:8px; display:flex; gap:8px; align-items:center;">
      <a class="btn btn-xs" :href="selected ? `/api/batch/${selected}/mail` : '#'" target="_blank" rel="noopener" :aria-disabled="!selected">Open raw</a>
    </div>
    <pre style="white-space: pre-wrap;">{{ mailText || 'No mail available' }}</pre>
  </Modal>
</template>
<script setup lang="ts">
import { onMounted, ref, watch } from 'vue';
import Modal from './Modal.vue';

const props = defineProps<{ batch: string }>();
const emit = defineEmits<{ (e:'changeBatch', v: string): void }>();

const batches = ref<string[]>([]);
const selected = ref('');
const stats = ref({ devices: 0, upgrades: 0, critical: 0 });
const modals = ref({ log: false, mail: false });
const logText = ref('');
const mailText = ref('');

async function fetchJSON<T>(url: string): Promise<T>{ const r = await fetch(url); if(!r.ok) throw new Error(await r.text()); return r.json(); }

async function loadBatches(){ const data = await fetchJSON<{batches:string[]}>('/api/batches'); batches.value = data.batches||[]; if(!selected.value && batches.value.length){ selected.value = batches.value[0]; emit('changeBatch', selected.value); } }
async function loadStats(){ if(!selected.value) { stats.value = {devices:0,upgrades:0,critical:0}; return; } const data = await fetchJSON<{devices:any[], batch_ts:string}>(`/api/batch/${selected.value}/devices`); const devs = data.devices||[]; const upgrades = devs.filter((d:any)=> d.upgrade_recommended).length; const critical = devs.filter((d:any)=> ((d.cve_counts||{}).Critical||0) > 0).length; stats.value = { devices: devs.length, upgrades, critical }; }

async function refresh(){ await loadBatches(); await loadStats(); }

async function openLog(){
  if(!selected.value) { modals.value.log = true; logText.value = ''; return; }
  try{
    const r = await fetch(`/api/batch/${encodeURIComponent(selected.value)}/log`);
    logText.value = r.ok ? await r.text() : `Error: ${r.status} ${r.statusText}`;
  }catch(err:any){
    logText.value = String(err?.message||err);
  }finally{
    modals.value.log = true;
  }
}

async function openMail(){
  if(!selected.value) { modals.value.mail = true; mailText.value = ''; return; }
  try{
    const r = await fetch(`/api/batch/${encodeURIComponent(selected.value)}/mail?decoded=true`);
    mailText.value = r.ok ? await r.text() : `Error: ${r.status} ${r.statusText}`;
  }catch(err:any){
    mailText.value = String(err?.message||err);
  }finally{
    modals.value.mail = true;
  }
}

watch(()=>props.batch, (b)=>{ if(b && b!==selected.value){ selected.value=b; loadStats(); } });
watch(selected, ()=>{ emit('changeBatch', selected.value); loadStats(); });

onMounted(()=>{ refresh(); });
</script>
<style scoped>
.card { background:#1c212b; border:1px solid #262d38; border-radius:10px; padding:12px; }
.row { display:flex; align-items:center; gap:8px; }
.stats { display:flex; gap:16px; margin-top:12px; }
.stat { background:#20262f; border:1px solid #2b3441; border-radius:8px; padding:8px 10px; min-width:120px; text-align:center; }
small { display:block; color:#8892a0; }
label { color:#8892a0; }
select, button, .btn { background:#222834; color:#e6e9ef; border:1px solid #2f3743; padding:6px 10px; border-radius:6px; font-size:13px; }
button, .btn { cursor:pointer; }
button:hover, .btn:hover { background:#2a3340; }
</style>

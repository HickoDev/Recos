<template>
  <section class="card">
    <h3 style="margin:0 0 8px;">Control panel</h3>
    <div class="toolbar">
      <input class="input" v-model.trim="aliasForm.pid" placeholder="PID (e.g., WS-C2960-48TT-L)" />
      <input class="input" v-model.trim="aliasForm.alias" placeholder="Model alias (e.g., Catalyst 2960-48TC-L Switch)" />
      <button class="btn" @click="addAlias" :disabled="!aliasForm.pid || !aliasForm.alias">Add/Update alias</button>
  <button class="btn" @click="checkAlias" :disabled="!aliasForm.pid">Check PID</button>
  <button class="btn" @click="openAliasList">Check PIDs</button>
    </div>
    <div v-if="aliasMsg" style="margin-top:6px;">
      <span class="chip" :style="{borderColor: aliasErr? '#fbb0aa':'#86d792', background: aliasErr? 'linear-gradient(180deg,#ffcfcc,#fd9b94)':'linear-gradient(180deg,#d7f5c5,#b9ed95)', color: aliasErr? '#2a0a0a':'#0c1a0a'}">{{ aliasMsg }}</span>
    </div>
    <div class="toolbar" style="margin-top:8px;">
      <label>Run mode</label>
      <select v-model="runMode" class="input">
        <option value="full">full (with Ansible)</option>
        <option value="no-ansible">no-ansible</option>
      </select>
      <button class="btn btn-primary" @click="startRun" :disabled="status.running">Start pipeline</button>
      <span v-if="status.running && !isComplete" class="chip" style="display:inline-flex; align-items:center; gap:8px;">
        <span class="spinner" aria-hidden="true"></span>
        Running: {{ status.mode }} — {{ status.progress_current }}/{{ status.progress_total }} ({{ status.progress_label }})
      </span>
      <span v-else-if="isComplete" class="chip" style="display:inline-flex; align-items:center; gap:8px; border-color:#86d792; background:linear-gradient(180deg,#d7f5c5,#b9ed95); color:#0c1a0a;">
        ✅ Completed — {{ status.progress_current }}/{{ status.progress_total }} ({{ status.progress_label }})
      </span>
  <button class="btn" @click="onRefreshClick">Refresh status</button>
      <span v-if="status.last_run_ts" class="chip">Last run: {{ status.last_run_ts }}</span>
    </div>
    <div v-if="status.orch_tail" style="margin-top:8px;">
      <pre style="max-height:160px; overflow:auto; background:#11161d; border:1px solid var(--border); border-radius: var(--radius-sm); padding:8px;">{{ status.orch_tail }}</pre>
    </div>
  </section>
  <Modal :open="modals.aliasList" title="PID aliases" @close="modals.aliasList=false">
    <div class="toolbar" style="margin-bottom:8px;">
      <input class="input" v-model.trim="aliasFilter" placeholder="Filter by PID or alias" />
    </div>
    <div style="max-height:60vh; overflow:auto; border:1px solid var(--border); border-radius: var(--radius);">
      <table>
        <thead>
          <tr><th style="width:36%">PID</th><th>Alias</th></tr>
        </thead>
        <tbody>
          <tr v-for="row in aliasListFiltered" :key="row.pid">
            <td class="mono">{{ row.pid }}</td>
            <td>{{ row.alias }}</td>
          </tr>
          <tr v-if="aliasListFiltered.length===0"><td colspan="2">No matches</td></tr>
        </tbody>
      </table>
    </div>
  </Modal>
</template>
<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';
import Modal from './Modal.vue';

const aliasForm = reactive({ pid:'', alias:'' });
const aliasMsg = ref('');
const aliasErr = ref(false);
const modals = reactive({ aliasList: false });
const aliasList = ref<Array<{pid:string, alias:string}>>([]);
const aliasFilter = ref('');

const runMode = ref<'full'|'no-ansible'>('full');
const status = reactive<{running:boolean; mode:string|null; started_at:number|null; last_run_ts:string|null; orch_tail:string; progress_current:number; progress_total:number; progress_label:string}>({ running:false, mode:null, started_at:null, last_run_ts:null, orch_tail:'', progress_current:0, progress_total:0, progress_label:'' });
const isComplete = computed(()=> status.progress_total > 0 && status.progress_current >= status.progress_total);
let pollTimer: number|undefined;

async function addAlias(){
  aliasMsg.value = '';
  aliasErr.value = false;
  try{
    const r = await fetch('/api/pid_alias', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ pid: aliasForm.pid, alias: aliasForm.alias }) });
    const j = await r.json();
    if(!r.ok){ throw new Error(j?.detail || r.statusText); }
    aliasMsg.value = `Saved: ${j.pid} → ${j.alias}`;
    aliasForm.pid = '';
    aliasForm.alias = '';
  }catch(err:any){
    aliasErr.value = true;
    aliasMsg.value = String(err?.message || err);
  }
}

async function checkAlias(){
  aliasMsg.value = '';
  aliasErr.value = false;
  try{
    const r = await fetch(`/api/pid_alias/${encodeURIComponent(aliasForm.pid)}`);
    let j: any = undefined;
    try { j = await r.json(); } catch { /* ignore parse errors */ }
    if(!r.ok){
      aliasErr.value = true;
      aliasMsg.value = (j && (j.detail || j.message)) ? j.detail || j.message : 'PID not found';
      return;
    }
    aliasForm.alias = (j && j.alias) ? j.alias : '';
    aliasMsg.value = `Found: ${j?.pid || aliasForm.pid} → ${aliasForm.alias || j?.alias || ''}`;
  }catch(err:any){
    aliasErr.value = true;
    aliasMsg.value = String(err?.message || 'PID not found');
  }
}

async function startRun(){
  try{
    const r = await fetch('/api/run', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ mode: runMode.value }) });
    const j = await r.json();
    if(!r.ok){ throw new Error(j?.detail || r.statusText); }
  await refreshStatus();
  // poll a few times for feedback after starting
  if(pollTimer){ clearInterval(pollTimer as any); }
  pollTimer = setInterval(refreshStatus, 2000) as unknown as number;
  }catch(err){ /* surface in status on refresh */ }
}

async function refreshStatus(){
  try{
    const r = await fetch('/api/run/status');
    const j = await r.json();
    status.running = !!j.running;
    status.mode = j.mode || null;
    status.started_at = j.started_at || null;
  status.last_run_ts = j.last_run_ts || null;
  status.orch_tail = j.orch_tail || '';
  status.progress_current = j.progress_current || 0;
  status.progress_total = j.progress_total || 0;
  status.progress_label = j.progress_label || '';
  const complete = status.progress_total > 0 && status.progress_current >= status.progress_total;
  if((!status.running || complete) && pollTimer){ clearInterval(pollTimer as any); pollTimer = undefined; }
  }catch{ /* noop */ }
}

// When the user explicitly clicks Refresh, if nothing is running, reset the panel to a basic/idle view
async function onRefreshClick(){
  await refreshStatus();
  if(!status.running){
    status.mode = null;
    status.started_at = null;
    // Keep last_run_ts for reference, but clear progress/log/log chip
    status.orch_tail = '';
    status.progress_current = 0;
    status.progress_total = 0;
    status.progress_label = '';
  }
}

onMounted(()=>{ refreshStatus(); });

async function openAliasList(){
  try{
    const r = await fetch('/api/pid_alias');
    const j = await r.json();
    const map = j?.pid_alias || {};
    const arr = Object.keys(map).map(k=>({ pid:k, alias: String(map[k] ?? '') }));
    arr.sort((a,b)=> a.pid.localeCompare(b.pid));
    aliasList.value = arr;
    modals.aliasList = true;
  }catch{
    aliasList.value = [];
    modals.aliasList = true;
  }
}

const aliasListFiltered = computed(()=>{
  const q = aliasFilter.value.trim().toLowerCase();
  if(!q){ return aliasList.value; }
  return aliasList.value.filter(r=> r.pid.toLowerCase().includes(q) || r.alias.toLowerCase().includes(q));
});
</script>
<style scoped>
label { color:#8892a0; }
.spinner { width:14px; height:14px; border:2px solid rgba(255,255,255,.2); border-top-color: #fff; border-radius: 50%; animation: spin 0.8s linear infinite; display:inline-block; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
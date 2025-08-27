<template>
  <section class="card">
    <div class="toolbar">
      <input class="input" v-model.trim="filters.host" placeholder="Filter host" />
      <input class="input" v-model.trim="filters.model" placeholder="Filter model" />
      <input class="input" v-model.trim="filters.rec" placeholder="Filter recommendation" />
      <button class="btn" @click="clear">Clear</button>
    </div>
  <div class="table-wrap" style="border:1px solid var(--border); border-radius: var(--radius);">
      <table>
        <thead>
          <tr>
            <th>Host</th>
            <th>Model</th>
            <th>Platform</th>
            <th>Version</th>
            <th>Recommended</th>
            <th>Designation</th>
            <th>Rec</th>
            <th>Critical</th>
            <th>High</th>
            <th>Status</th>
            <th>Series Release</th>
            <th>End-of-Sale</th>
            <th>End-of-Support</th>
            <th>URL</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="d in filtered" :key="d.host" :class="{ 'needs-upgrade': d.upgrade_recommended }">
            <td>{{ d.host }}</td>
            <td>{{ d.model }}</td>
            <td>{{ d.platform }}</td>
            <td>{{ d.current_version }}</td>
            <td>{{ d.recommended_version }}</td>
            <td>
              <span v-if="d.release_designation" class="badge desig" @click="showDesig(d.release_designation)">{{ d.release_designation }}</span>
            </td>
            <td>{{ d.recommendation }}</td>
            <td>
              <span class="chip chip-critical" :title="'Critical CVEs'">{{ (d.cve_counts||{}).Critical || 0 }}</span>
            </td>
            <td>
              <span class="chip chip-high" :title="'High CVEs'">{{ (d.cve_counts||{}).High || 0 }}</span>
            </td>
            <td>
              <template v-if="statusLevel(statusText(d))">
                <span :class="['status-badge', 'status-' + statusLevel(statusText(d))]">{{ statusText(d) }}</span>
              </template>
              <template v-else>
                <span>{{ statusText(d) }}</span>
              </template>
            </td>
            <td>
              <span>{{ d.series_release_date || (d.eol_details && d.eol_details.series_release_date) || '' }}</span>
            </td>
            <td>
              <span>{{ d.end_of_sale_date || (d.eol_details && d.eol_details.end_of_sale_date) || '' }}</span>
            </td>
            <td>
              <span>{{ d.end_of_support_date || (d.eol_details && d.eol_details.end_of_support_date) || '' }}</span>
            </td>
            <td>
              <a v-if="d.final_url" :href="d.final_url" target="_blank" rel="noopener">link</a>
            </td>
            <td>
              <button class="btn btn-xs" @click="openTimeline(d.host)">Timeline</button>
              <button class="btn btn-xs" @click="openCVEs(d.host)">CVEs</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
  <Modal :open="modals.desig.open" :title="desigInfo(modals.desig.code).title" @close="modals.desig.open=false">
    <div class="desig-body">{{ desigInfo(modals.desig.code).desc }}</div>
  </Modal>
  <Modal :open="modals.timeline.open" title="Timeline" @close="modals.timeline.open=false">
    <div v-if="timeline.rows.length===0">No data</div>
    <table v-else>
      <thead>
        <tr>
          <th>Batch</th><th>Version</th><th>Recommended</th><th>Designation</th><th>Rec</th><th>Critical</th><th>High</th><th>CPU</th><th>URL</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="r in timeline.rows" :key="r.batch_ts">
          <td>{{ r.batch_ts }}</td>
          <td>{{ r.version }}</td>
          <td>{{ r.recommended_version }}</td>
          <td>
            <span v-if="r.release_designation" class="badge desig" @click="showDesig(r.release_designation)">{{ r.release_designation }}</span>
          </td>
          <td>{{ r.recommendation }}</td>
          <td>{{ r.critical_cves || 0 }}</td>
          <td>{{ r.high_cves || 0 }}</td>
          <td>{{ r.cpu_usage || '' }}</td>
          <td>
            <a v-if="r.final_url" :href="r.final_url" target="_blank" rel="noopener">link</a>
          </td>
        </tr>
      </tbody>
    </table>
  </Modal>
  <Modal :open="modals.cves.open" :title="`CVEs: ${modals.cves.host||''}`" @close="modals.cves.open=false">
    <div v-if="!cves.data">No record</div>
    <template v-else>
      <h4 style="margin:4px 0 8px;">{{ modals.cves.host }}</h4>
      <div v-for="sev in ['Critical','High','Medium','Low']" :key="sev" style="margin-top:4px;">
        <strong>{{ sev }} ({{ (cves.data.cves?.[sev]||[]).length }})</strong>
        <ul v-if="(cves.data.cves?.[sev]||[]).length" style="margin:2px 0 6px 16px; padding:0;">
          <li v-for="item in cves.data.cves?.[sev]" :key="item.id || item.title" style="margin:2px 0;">
            <template v-if="(item.cisco_url || item.nvd_url)">
              <a :href="item.cisco_url || item.nvd_url" target="_blank" rel="noopener">
                <span v-if="item.id" class="mono">{{ item.id }}</span>
                <span v-if="item.title"> - {{ item.title }}</span>
              </a>
            </template>
            <template v-else>
              <span v-if="item.id" class="mono">{{ item.id }}</span>
              <span v-if="item.title"> - {{ item.title }}</span>
            </template>
          </li>
        </ul>
      </div>
    </template>
  </Modal>
</template>
<script setup lang="ts">
import { computed, onMounted, reactive, watch } from 'vue';
import Modal from './Modal.vue';

const props = defineProps<{ batch: string }>();

type Device = Record<string, any>;
const rows = reactive<Device[]>([]);
const filters = reactive({ host:'', model:'', rec:'' });
const modals = reactive({
  timeline: { open:false },
  cves: { open:false, host:'' as string },
  desig: { open:false, code:'' as string }
});
const timeline = reactive<{rows:any[]}>({ rows: [] });
const cves = reactive<{data:any|null}>({ data: null });

async function fetchJSON<T>(url: string): Promise<T>{ const r = await fetch(url); if(!r.ok) throw new Error(await r.text()); return r.json(); }
async function load(){ if(!props.batch) { rows.splice(0); return; } const data = await fetchJSON<{devices:Device[]}>(`/api/batch/${props.batch}/devices`); rows.splice(0); rows.push(...(data.devices||[])); }

const filtered = computed(()=> rows.filter(d=>{
  const qh = filters.host.toLowerCase();
  const qm = filters.model.toLowerCase();
  const qr = filters.rec.toLowerCase();
  if(qh && !(String(d.host||'').toLowerCase().includes(qh))) return false;
  if(qm && !(String(d.model||'').toLowerCase().includes(qm))) return false;
  if(qr && !(String(d.recommendation||'').toLowerCase().includes(qr))) return false;
  return true;
}));

function clear(){ filters.host=''; filters.model=''; filters.rec=''; }

function desigInfo(code: string): {title:string, desc:string} {
  const k = (code||'').toUpperCase();
  const map: Record<string,{title:string,desc:string}> = {
    DF:{
      title:'Deferral (DF)',
      desc:`The purpose of the Deferral Advisory is to announce the removal of affected IOS image(s) and to introduce replacement image(s). Customers are strongly urged to migrate from the affected image(s) to the replacement image(s).`
    },
    ED:{
      title:'Early Deployment (ED)',
      desc:`Software releases that provide new features and new platform support in addition to bug fixes.`
    },
    MD:{
      title:'Maintenance Deployment (MD)',
      desc:`A Cisco software release that provides bug fix support and ongoing software maintenance.`
    },
    GD:{
      title:'General Deployment (GD)',
      desc:`Release has reached the General Deployment milestone and is suitable for broad deployment where its features are required. Based on customer feedback, bug reports, and field experience.`
    },
    LD:{
      title:'Limited Deployment (LD)',
      desc:`Phase between initial FCS and the General Deployment milestone for a major IOS release.`
    },
    F:{
      title:'F (NX-OS)',
      desc:`NX-OS software release that provides new features and new platform support in addition to bug fixes.`
    },
    M:{
      title:'M (NX-OS)',
      desc:`NX-OS software release that provides bug fix support or PSIRT fixes as part of ongoing maintenance.`
    },
  };
  return map[k] || { title: `Designation: ${code||''}`, desc: 'No additional information available.' };
}
function showDesig(code: string){
  modals.desig.code = code;
  modals.desig.open = true;
}

watch(()=>props.batch, ()=> load());

onMounted(()=> load());
async function openTimeline(host: string){
  try{
    const res = await fetch(`/api/device/${encodeURIComponent(host)}/timeline`);
    if(!res.ok) throw new Error(await res.text());
    const data = await res.json();
    timeline.rows = data.timeline || [];
    modals.timeline.open = true;
  }catch(err){
    timeline.rows = [];
    modals.timeline.open = true;
  }
}

async function openCVEs(host: string){
  try{
    const res = await fetch(`/api/batch/${encodeURIComponent(props.batch)}/cves`);
    if(!res.ok) throw new Error(await res.text());
    const data = await res.json();
    const rec = (data.cves||[]).find((r:any)=> r.host===host);
    cves.data = rec || null;
    modals.cves.host = host;
    modals.cves.open = true;
  }catch(err){
    cves.data = null;
    modals.cves.host = host;
    modals.cves.open = true;
  }
}

// --- Status helpers (color coding) ---
function statusText(d: any): string {
  return String(d?.status || d?.eol_details?.status || '').trim();
}
function statusLevel(text: string): 'ok'|'eos'|'eosup'|null {
  const s = (text || '').toLowerCase();
  if (!s) return null;
  if (s.includes('end of support') || s.includes('last date of support')) return 'eosup';
  if (s.includes('end-of-support')) return 'eosup';
  if (s.includes('end of sale') || s.includes('end-of-sale')) return 'eos';
  if (s.includes('available') || s.includes('active') || s.includes('orderable')) return 'ok';
  return null;
}
</script>
<style scoped>
.card { /* global card styles apply */ padding:12px; }
.toolbar { display:flex; gap:8px; margin-bottom:8px; }
.table-wrap { overflow:auto; max-height:60vh; }
.badge { background:#31435b; border:1px solid #405374; color:#dfe7ff; padding:2px 8px; border-radius:999px; cursor:pointer; }
.desig{ transition:background-color .15s ease, color .15s ease; }
.desig:hover{ background:#3d82f7; color:#0a1020; }
th, td { padding:6px 8px; white-space:nowrap; }
thead th { position:sticky; top:0; }
tr:nth-child(even) { background:#161d2a; }
tr:hover { background:#1a2333; }

/* Status badge colors */
.status-badge { padding:2px 8px; border-radius:999px; border:1px solid transparent; font-size:12px; }
.status-ok { background:#16341f; border-color:#265a2a; color:#a8f0b0; }
.status-eos { background:#3a3315; border-color:#6b5e17; color:#ffe08a; }
.status-eosup { background:#3b1717; border-color:#6b1e1e; color:#ffb3b3; }

.desig-body { white-space: pre-wrap; line-height: 1.35; }
</style>

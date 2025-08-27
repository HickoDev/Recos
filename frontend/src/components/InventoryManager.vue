<template>
  <section class="card">
    <h3 style="margin:0 0 8px; display:flex; align-items:center; gap:8px;">Inventory <span class="chip">Ansible</span></h3>
    <div class="toolbar" style="flex-wrap:wrap; gap:8px;">
      <label>Group</label>
      <select class="input" v-model="group" @change="loadGroup">
        <option value="ios">ios</option>
        <option value="nxos">nxos</option>
      </select>
      <button class="btn" @click="loadGroup">Reload</button>
      <span v-if="msg" class="chip" :style="msgStyle">{{ msg }}</span>
    </div>
    <div style="overflow:auto; border:1px solid var(--border); border-radius: var(--radius); margin-top:8px;">
      <table>
        <thead>
          <tr>
            <th style="width:14rem;">Host (inventory name)</th>
            <th>ansible_host</th>
            <th>ansible_user</th>
            <th>ansible_password</th>
            <th>ansible_network_os</th>
            <th>ansible_connection</th>
            <th style="width:10rem;">Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row,idx) in rows" :key="row.host || idx">
            <td>
              <input class="input mono" v-model.trim="row.editHost" />
            </td>
            <td>
              <input class="input mono" v-model.trim="row.ansible_host" placeholder="1.2.3.4 or hostname" />
            </td>
            <td>
              <input class="input mono" v-model.trim="row.ansible_user" placeholder="username" />
            </td>
            <td>
              <input class="input mono" type="password" v-model="row.ansible_password" placeholder="password" />
            </td>
            <td>
              <input class="input mono" v-model.trim="row.ansible_network_os" placeholder="cisco.ios.ios or cisco.nxos.nxos" />
            </td>
            <td>
              <input class="input mono" v-model.trim="row.ansible_connection" placeholder="network_cli" />
            </td>
            <td>
              <div style="display:flex; gap:6px;">
                <button class="btn btn-primary" @click="save(idx)">Save</button>
                <button class="btn" style="border-color:#f3b0a8; color:#7a1b12;" @click="remove(row.host)">Delete</button>
              </div>
            </td>
          </tr>
          <tr v-if="rows.length===0"><td colspan="7">No hosts in {{ group }}</td></tr>
        </tbody>
      </table>
    </div>
    <div class="toolbar" style="margin-top:8px;">
      <button class="btn" @click="addRow">Add host</button>
    </div>
  </section>
  
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';

type InvRow = {
  host: string; // inventory name
  vars: Record<string, any>;
  editHost: string;
  ansible_host: string;
  ansible_user: string;
  ansible_password: string;
  ansible_network_os: string;
  ansible_connection: string;
  extra: Record<string, any>; // preserve unknown keys
};

const group = ref<'ios'|'nxos'>('ios');
const rows = reactive<Array<InvRow>>([]);
const msg = ref('');
const msgErr = ref(false);
const msgStyle = computed(()=>({
  borderColor: msgErr.value ? '#fbb0aa':'#86d792',
  background: msgErr.value ? 'linear-gradient(180deg,#ffcfcc,#fd9b94)':'linear-gradient(180deg,#d7f5c5,#b9ed95)',
  color: msgErr.value ? '#2a0a0a':'#0c1a0a'
}));

function splitVars(v: Record<string, any> | undefined){
  const vars = v || {};
  const known = ['ansible_host','ansible_user','ansible_password','ansible_network_os','ansible_connection'];
  const extra: Record<string, any> = {};
  for(const k of Object.keys(vars)){
    if(!known.includes(k)) extra[k] = vars[k];
  }
  return {
    ansible_host: String(vars.ansible_host ?? ''),
    ansible_user: String(vars.ansible_user ?? ''),
    ansible_password: String(vars.ansible_password ?? ''),
    ansible_network_os: String(vars.ansible_network_os ?? ''),
    ansible_connection: String(vars.ansible_connection ?? ''),
    extra,
  };
}

async function loadGroup(){
  msg.value = '';
  msgErr.value = false;
  try{
    const r = await fetch(`/api/inventory/${encodeURIComponent(group.value)}`);
    const j = await r.json();
    if(!r.ok) throw new Error(j?.detail || r.statusText);
    rows.splice(0); // clear
    for(const e of (j.hosts || [])){
      const parts = splitVars(e.vars);
      rows.push({
        host: e.host,
        vars: e.vars || {},
        editHost: e.host,
        ansible_host: parts.ansible_host,
        ansible_user: parts.ansible_user,
        ansible_password: parts.ansible_password,
        ansible_network_os: parts.ansible_network_os,
        ansible_connection: parts.ansible_connection,
        extra: parts.extra,
      });
    }
  }catch(err:any){
    msgErr.value = true;
    msg.value = String(err?.message || err);
    rows.splice(0);
  }
}

function addRow(){
  rows.push({
    host: '',
    vars: {},
    editHost: '',
    ansible_host: '',
    ansible_user: '',
    ansible_password: '',
    ansible_network_os: group.value === 'ios' ? 'cisco.ios.ios' : 'cisco.nxos.nxos',
    ansible_connection: 'network_cli',
    extra: {},
  });
}

async function save(idx: number){
  msg.value = '';
  msgErr.value = false;
  const row = rows[idx];
  if(!row.editHost.trim()){
    msgErr.value = true; msg.value = 'Host is required'; return;
  }
  // Build vars from five explicit fields + preserved extras
  const vars: Record<string, any> = {};
  if(row.ansible_host) vars.ansible_host = row.ansible_host;
  if(row.ansible_user) vars.ansible_user = row.ansible_user;
  if(row.ansible_password) vars.ansible_password = row.ansible_password;
  if(row.ansible_network_os) vars.ansible_network_os = row.ansible_network_os;
  if(row.ansible_connection) vars.ansible_connection = row.ansible_connection;
  for(const [k,v] of Object.entries(row.extra || {})) vars[k] = v;
  try{
    const r = await fetch('/api/inventory/host', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ group: group.value, host: row.editHost.trim(), vars }) });
    const j = await r.json();
    if(!r.ok) throw new Error(j?.detail || r.statusText);
    row.host = row.editHost.trim();
    row.vars = vars;
    msg.value = 'Saved';
    await loadGroup();
  }catch(err:any){
    msgErr.value = true; msg.value = String(err?.message || err);
  }
}

async function remove(host: string){
  if(!host) return;
  msg.value = '';
  msgErr.value = false;
  try{
    const r = await fetch('/api/inventory/host', { method:'DELETE', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ group: group.value, host }) });
    const j = await r.json();
    if(!r.ok) throw new Error(j?.detail || r.statusText);
    msg.value = 'Deleted';
    await loadGroup();
  }catch(err:any){
    msgErr.value = true; msg.value = String(err?.message || err);
  }
}

onMounted(()=>{ loadGroup(); });
</script>

<style scoped>
.mono{ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, Liberation Mono, monospace; }
/* inputs auto-resize nicely in table */
td > .input { width: 100%; }
</style>

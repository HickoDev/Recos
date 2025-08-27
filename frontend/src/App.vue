<template>
  <div>
    <header class="app-header">
      <div class="container app-header-inner">
        <div class="brand">
          <h1>retrievos</h1>
          <small>Dashboard</small>
        </div>
        <div class="auth">
          <template v-if="auth.authenticated">
            <span class="chip" title="Authentication status"
              :style="{borderColor:'#86d792', background:'linear-gradient(180deg,#d7f5c5,#b9ed95)', color:'#0c1a0a'}">
              👤 {{ auth.userName || 'user' }}
            </span>
            <button class="btn" @click="logout">Logout</button>
          </template>
          <template v-else>
            <button class="btn btn-primary" @click="openLogin = true">Login</button>
          </template>
        </div>
      </div>
    </header>
    <main v-if="showDashboard" class="container main">
      <ControlPanel />
      <InventoryManager />
      <Summary :batch="state.batch" @changeBatch="onChangeBatch" />
      <Devices :batch="state.batch" />
    </main>
    <section v-else class="container" style="display:grid; place-items:center; min-height:60vh;">
      <div class="login-card">
        <h2 style="margin:0 0 12px;">Sign in</h2>
        <p style="margin:0 0 12px; color:#8892a0;">Enter your credentials to access the dashboard.</p>
        <form @submit.prevent="login">
          <div class="row">
            <label>Username</label>
            <input class="input" v-model.trim="loginForm.username" placeholder="admin" autocomplete="username" />
          </div>
          <div class="row">
            <label>Password</label>
            <input class="input" v-model="loginForm.password" type="password" placeholder="••••••••" autocomplete="current-password" />
          </div>
          <div v-if="auth.error" class="error">{{ auth.error }}</div>
          <div class="row" style="display:flex; gap:8px; justify-content:flex-end;">
            <button type="submit" class="btn btn-primary">Login</button>
          </div>
        </form>
      </div>
    </section>

    <Modal :open="openLogin" title="Sign in" @close="onCloseLogin">
      <div v-if="auth.authDisabled" class="notice">
        <p>Authentication is currently disabled (open mode). Set ADMIN_PASSWORD in .env to enable login.</p>
      </div>
      <form @submit.prevent="login">
        <div class="row">
          <label>Username</label>
          <input class="input" v-model.trim="loginForm.username" placeholder="admin" autocomplete="username" />
        </div>
        <div class="row">
          <label>Password</label>
          <input class="input" v-model="loginForm.password" type="password" placeholder="••••••••" autocomplete="current-password" />
        </div>
        <div v-if="auth.error" class="error">{{ auth.error }}</div>
        <div class="row" style="display:flex; gap:8px; justify-content:flex-end;">
          <button type="button" class="btn" @click="onCloseLogin">Cancel</button>
          <button type="submit" class="btn btn-primary">Login</button>
        </div>
      </form>
    </Modal>
  </div>
  
</template>

<script setup lang="ts">
import { reactive, ref, onMounted, computed } from 'vue';
import Summary from './components/Summary.vue';
import Devices from './components/Devices.vue';
import ControlPanel from './components/ControlPanel.vue';
import InventoryManager from './components/InventoryManager.vue';
import Modal from './components/Modal.vue';

const state = reactive({ batch: '' });

function onChangeBatch(v: string){ state.batch = v; }

// Auth state and handlers
const auth = reactive<{ authenticated: boolean; userName: string; error: string }>({
  authenticated: false,
  userName: '',
  error: ''
});
const openLogin = ref(false);
const loginForm = reactive({ username: '', password: '' });

async function refreshAuth(){
  try{
  const r = await fetch(`/api/auth/me?t=${Date.now()}`, { credentials: 'same-origin', cache: 'no-store' });
    const j = await r.json();
  auth.authenticated = !!j.authenticated;
  auth.userName = (j.user && j.user.name) ? j.user.name : '';
  }catch{
  auth.authenticated = false;
  auth.userName = '';
  }
}

async function login(){
  auth.error = '';
  try{
    const r = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
  credentials: 'same-origin',
  body: JSON.stringify({ username: loginForm.username, password: loginForm.password })
    });
    const j = await r.json();
    if(!r.ok){ throw new Error(j?.detail || 'Login failed'); }
    await refreshAuth();
    openLogin.value = false;
    loginForm.username = '';
    loginForm.password = '';
  }catch(err:any){
    auth.error = String(err?.message || 'Login failed');
  }
}

async function logout(){
  try{
    await fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' });
  }catch{}
  // Optimistically update UI
  auth.authenticated = false;
  auth.userName = '';
  await refreshAuth();
}

function onCloseLogin(){
  openLogin.value = false;
  auth.error = '';
}

onMounted(()=>{ refreshAuth(); });

const showDashboard = computed(()=> auth.authenticated);
</script>

<style scoped>
/* page-specific tweaks if needed */
.app-header-inner{ display:flex; align-items:center; justify-content:space-between; }
.auth{ display:flex; align-items:center; gap:8px; }
.notice{ margin: 8px 0; padding:8px; border:1px solid var(--border); border-radius: var(--radius); background: #202733; }
.row{ margin:8px 0; display:grid; gap:6px; }
.error{ color:#ffb3ae; margin:6px 0; }
.login-card{ width:min(520px, 96vw); background:#1b2029; border:1px solid #2a313d; border-radius:12px; padding:16px; box-shadow:0 10px 40px rgba(0,0,0,.4); }
</style>

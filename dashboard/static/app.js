// retrievos dashboard main JS (extracted)
const batchSelect = document.getElementById('batch-select');
const latestBatchLabel = document.getElementById('latest-batch-label');
const refreshBtn = document.getElementById('refresh-btn');
const devicesTableBody = document.querySelector('#devices-table tbody');
const filterHost = document.getElementById('filter-host');
const filterModel = document.getElementById('filter-model');
const filterRec = document.getElementById('filter-rec');
const clearFilterBtn = document.getElementById('clear-filter');
const modal = document.getElementById('modal');
const themeToggle = document.getElementById('theme-toggle');
const densityToggle = document.getElementById('density-toggle');
const sevLegend = document.getElementById('sev-legend');
const sevFilters = document.querySelectorAll('.sev-filter');
const exportCsvBtn = document.getElementById('export-csv');
const exportJsonBtn = document.getElementById('export-json');
const columnsBtn = document.getElementById('columns-btn');
const columnsMenu = document.getElementById('columns-menu');
const sideDrawer = document.getElementById('side-drawer');
const drawerClose = document.getElementById('drawer-close');
const drawerBody = document.getElementById('drawer-body');
const trendSpark = document.getElementById('trend-spark');
const severityPie = document.getElementById('severity-pie');
const upgradePie = document.getElementById('upgrade-pie');
const modalClose = document.getElementById('modal-close');
const modalTitle = document.getElementById('modal-title');
const modalBody = document.getElementById('modal-body');
const viewLogBtn = document.getElementById('view-log-btn');
const viewMailBtn = document.getElementById('view-mail-btn');

let currentBatch = null;
let rawDevices = [];
let sortState = { key: null, dir: 1 };
let summariesCache = [];
let lastRenderedRows = [];

// Designation dictionary and helpers
const DESIGNATION_INFO = {
  DF: {
    title: 'Deferral (DF)',
    desc: "Announces removal of affected IOS image(s) from Cisco offerings and introduces replacement image(s). Customers are strongly urged to migrate to the replacement image(s)."
  },
  ED: {
    title: 'Early Deployment (ED)',
    desc: 'Releases that provide new features and new platform support in addition to bug fixes. Variants include CTED, STED, SMED, and XED.'
  },
  MD: {
    title: 'Maintenance Deployment (MD)',
    desc: 'Provides bug fix support and ongoing software maintenance.'
  },
  GD: {
    title: 'General Deployment (GD)',
    desc: 'Major IOS release milestone for broad deployment based on field experience and feedback. Note: GD is not applied to future 12.4 maintenance releases/rebuilds.'
  },
  LD: {
    title: 'Limited Deployment (LD)',
    desc: 'Phase between initial FCS and General Deployment (GD) milestones for a Major IOS release. Note: LD is not applied to future 12.4 maintenance releases/rebuilds.'
  },
  F: {
    title: 'F (NX-OS)',
    desc: 'NX-OS release that provides new features and new platform support in addition to bug fixes.'
  },
  M: {
    title: 'M (NX-OS)',
    desc: 'NX-OS release that provides bug fix support or PSIRT fixes as part of ongoing maintenance.'
  },
};
function getDesignationInfo(code){ if(!code) return null; const k=String(code).toUpperCase(); return DESIGNATION_INFO[k] || null; }
function designationBadge(code){ const info=getDesignationInfo(code); const k=(code||'').toString().toUpperCase(); const title=info?info.title:('Designation '+k); return `<span class="badge b-same desig" data-desig="${k}" title="${title}" role="button" tabindex="0" aria-label="${title}. Press Enter for details.">${k}</span>`; }
function openDesignation(code){ const info=getDesignationInfo(code); const k=(code||'').toString().toUpperCase(); if(!info){ openModal('Designation', `<p>No details available for: <strong>${escapeHtml(k)}</strong></p>`); return; } const html=`<div class="desig-pop"><div class="pill mono">${escapeHtml(k)}</div><h4 style="margin:6px 0 8px;">${escapeHtml(info.title)}</h4><p style="white-space:normal;">${escapeHtml(info.desc)}</p></div>`; openModal('Designation Info', html); }

function openModal(title, html){
  modalTitle.textContent = title;
  modalBody.innerHTML = html;
  modal.style.display='flex';
  // lock background scroll and focus modal body for wheel/keys
  document.body.classList.add('modal-open');
  // Ensure modal body can receive keyboard focus for arrow/PageUp/PageDown
  if (!modalBody.hasAttribute('tabindex')) modalBody.setAttribute('tabindex','0');
  // Force a computed max-height for body to guarantee scroll in all browsers
  setTimeout(()=>{
    try{
      const modalPanel = modal.querySelector('.modal');
      if(modalPanel){
        const rect = modalPanel.getBoundingClientRect();
        const styles = getComputedStyle(modalPanel);
        const paddingTop = parseFloat(styles.paddingTop)||0;
        const paddingBottom = parseFloat(styles.paddingBottom)||0;
        const header = modalPanel.querySelector('h3');
        const headerH = header ? header.getBoundingClientRect().height : 0;
        const chrome = paddingTop + paddingBottom + headerH + 10; // include close button margin
        const maxH = Math.max(120, Math.min(window.innerHeight*0.85 - chrome, window.innerHeight - 2*24));
        modalBody.style.maxHeight = maxH + 'px';
      }
      modalBody.focus();
    }catch(_){ }
  }, 0);
}
function closeModal(){
  modal.style.display='none';
  document.body.classList.remove('modal-open');
}
modalClose.onclick = closeModal; modal.onclick = e=>{ if(e.target===modal) closeModal(); };

async function fetchJSON(url){ const r = await fetch(url); if(!r.ok) throw new Error(await r.text()); return r.json(); }
async function fetchText(url){ const r = await fetch(url); if(!r.ok) throw new Error(await r.text()); return r.text(); }
function badge(text, cls){ return `<span class="badge ${cls||''}">${text}</span>`; }
function classifyRecommendation(r){ if(!r) return ''; const t=r.toLowerCase(); if(t.includes('obligatory')||t.includes('critical')) return 'b-upgrade'; if(t.includes('suggested')) return 'b-upgrade'; if(t.includes('same')) return 'b-same'; return ''; }

function renderSummary(devs){ const upgrades=devs.filter(d=>d.upgrade_recommended); const crit=devs.filter(d=> (d.cve_counts||{}).Critical>0); document.getElementById('stat-devices').textContent=devs.length; document.getElementById('stat-devices-sub').textContent='total devices'; document.getElementById('stat-upgrades').textContent=upgrades.length; document.getElementById('stat-upgrades-sub').textContent='need action'; document.getElementById('stat-critical').textContent=crit.length; document.getElementById('stat-critical-sub').textContent='with Critical CVEs'; }

function renderTable(){ const qh=filterHost.value.trim().toLowerCase(); const qm=filterModel.value.trim().toLowerCase(); const qr=filterRec.value.trim().toLowerCase(); const activeSev=Array.from(sevFilters).filter(c=>c.checked).map(c=>c.value); const totalSev=sevFilters.length; devicesTableBody.innerHTML=''; let rows=rawDevices.filter(d=>{ if(qh && !(d.host||'').toLowerCase().includes(qh)) return false; if(qm && !(d.model||'').toLowerCase().includes(qm)) return false; if(qr && !(d.recommendation||'').toLowerCase().includes(qr)) return false; const cc=(d.cve_counts||{}); // Apply severity filter only when a strict subset is selected
  if(activeSev.length && activeSev.length < totalSev){ let show=false; for(const sev of activeSev){ if((cc[sev]||0)>0){ show=true; break; } } if(!show) return false; }
  return true; }); if(sortState.key){ rows.sort((a,b)=>{ const k=sortState.key; function val(row){ if(k==='cve_critical') return (row.cve_counts||{}).Critical||0; if(k==='cve_high') return (row.cve_counts||{}).High||0; return (row[k]||''); } const va=val(a), vb=val(b); if(va===vb) return 0; if(typeof va==='number' && typeof vb==='number') return (va-vb)*sortState.dir; return (''+va).localeCompare(''+vb)*sortState.dir; }); } lastRenderedRows = rows.slice(); for(const d of rows){ const tr=document.createElement('tr'); const recCls=classifyRecommendation(d.recommendation); const cc=(d.cve_counts||{}); tr.innerHTML=`<td class="nowrap host-cell sticky-cell" data-host="${d.host}">${d.host}</td>
<td data-col="alias">${d.alias_name||''}</td>
<td data-col="model" class="model-cell" style="cursor:pointer;">${d.model||''}</td>
<td data-col="platform">${d.platform||''}</td>
<td>${d.current_version||''}</td>
<td data-col="recommended_version">${d.recommended_version||''}</td>
<td data-col="designation">${d.release_designation?designationBadge(d.release_designation):''}</td>
<td data-col="rec">${d.recommendation?badge(d.recommendation,recCls):''}</td>
<td data-col="cpu_usage">${d.cpu_usage||''}</td>
<td data-col="ports">${d.connected_count||0}/${d.total_interfaces||0}</td>
<td data-col="critical">${cc.Critical||0}</td>
<td data-col="high">${cc.High||0}</td>
<td data-col="uptime">${d.uptime||''}</td>
<td data-col="eol">${d.end_of_life==='X'?badge('EoL','b-eol'):''}</td>
<td data-col="url">${d.final_url?`<a href=\"${d.final_url}\" target=\"_blank\">link</a>`:''}</td>
<td>\n<button data-host="${d.host}" class="mini-btn" data-action="timeline">Timeline</button> <button data-host="${d.host}" data-action="cves" class="mini-btn">CVEs</button></td>`;
  tr.dataset.raw = JSON.stringify(d);
  devicesTableBody.appendChild(tr); }
  applyColumnVisibility();
}

async function loadBatchList(){ const data=await fetchJSON('/api/batches'); batchSelect.innerHTML=''; data.batches.forEach(ts=>{ const opt=document.createElement('option'); opt.value=ts; opt.textContent=ts; batchSelect.appendChild(opt); }); if(!currentBatch && data.batches.length){ currentBatch=data.batches[0]; } batchSelect.value=currentBatch||''; }
async function loadDevices(){ if(!currentBatch){ rawDevices=[]; renderTable(); return; } const data=await fetchJSON(`/api/batch/${currentBatch}/devices`); rawDevices=data.devices; latestBatchLabel.textContent='Batch: '+currentBatch; renderSummary(rawDevices); renderTable(); drawSeverityPie(); drawUpgradePie(); }

batchSelect.onchange=()=>{ currentBatch=batchSelect.value; persistState(); loadDevices(); };
refreshBtn.onclick=async ()=>{ await loadBatchList(); await loadDevices(); };
clearFilterBtn.onclick=()=>{ filterHost.value=''; filterModel.value=''; filterRec.value=''; sevFilters.forEach(c=>c.checked=true); persistState(); renderTable(); };
[filterHost,filterModel,filterRec].forEach(inp=> inp.addEventListener('input', ()=>{ persistState(); renderTable(); }));
sevFilters.forEach(c=> c.addEventListener('change', ()=>{ persistState(); renderTable(); }));

// Row actions
devicesTableBody.addEventListener('click', async e=>{ 
  // Click on designation badge in table row
  const dz = e.target.closest('[data-desig]');
  if(dz && devicesTableBody.contains(dz)){
    const code = dz.getAttribute('data-desig');
    openDesignation(code);
    return;
  }
  const btn=e.target.closest('button'); if(!btn) return; const host=btn.getAttribute('data-host'); const action=btn.getAttribute('data-action'); if(action==='timeline'){ try{ const data=await fetchJSON(`/api/device/${host}/timeline`); let html='<table style="width:100%;font-size:12px;">\n<tr><th>Batch</th><th>Version</th><th>Recommended</th><th>Designation</th><th>Rec</th><th>Critical</th><th>High</th><th>CPU</th><th>URL</th></tr>'; for(const row of data.timeline){ const des = row.release_designation?designationBadge(row.release_designation):''; html+=`<tr><td>${row.batch_ts}</td><td>${row.version||''}</td><td>${row.recommended_version||''}</td><td>${des}</td><td>${row.recommendation||''}</td><td>${row.critical_cves||0}</td><td>${row.high_cves||0}</td><td>${row.cpu_usage||''}</td><td>${row.final_url?`<a href='${row.final_url}' target='_blank'>link</a>`:''}</td></tr>`; } html+='</table>'; openModal(`Timeline: ${host}`, html);}catch(err){ openModal('Error', `<pre>${err}</pre>`);} } else if(action==='cves'){
  try{
    const data=await fetchJSON(`/api/batch/${currentBatch}/cves`);
    const rec=data.cves.find(r=>r.host===host);
    if(!rec){ openModal('CVEs','No record'); return;}
    let html=`<h4 style="margin:4px 0 8px;">${host}</h4>`;
    const sevOrder=['Critical','High','Medium','Low'];
    for(const sev of sevOrder){
      const list=(rec.cves||{})[sev]||[];
      html+=`<div style="margin-top:4px;"><strong>${sev} (${list.length})</strong></div>`;
      if(list.length){
        html+='<ul style="margin:2px 0 6px 16px; padding:0;">';
        for(const item of list){
          const cveId=(item.id||'').trim();
          const title=(item.title||cveId||'untitled');
          const idHtml=cveId?`<span class="mono">${escapeHtml(cveId)}</span> - `:'';
          const url = item.cisco_url || item.nvd_url || (cveId?`https://nvd.nist.gov/vuln/detail/${encodeURIComponent(cveId)}`:null);
          if(url){
            html+=`<li data-url="${url}" style="margin:2px 0;"><a href="${url}" target="_blank" rel="noopener">${idHtml}${escapeHtml(title)}</a></li>`;
          } else {
            html+=`<li style="margin:2px 0;">${idHtml}${escapeHtml(title)}</li>`;
          }
        }
        html+='</ul>';
      }
    }
    openModal('CVEs: '+host, html);
  } catch(err){ openModal('Error', `<pre>${err}</pre>`);} 
} });
// Side drawer
devicesTableBody.addEventListener('click', e=>{ const modelCell=e.target.closest('.model-cell'); if(!modelCell) return; const rowEl=modelCell.parentElement; devicesTableBody.querySelectorAll('tr').forEach(r=> r.classList.remove('selected-row')); rowEl.classList.add('selected-row'); const host=rowEl.querySelector('.host-cell').dataset.host; const rec=rawDevices.find(r=>r.host===host); if(!rec) return; drawerBody.innerHTML=renderDeviceDrawer(rec); sideDrawer.classList.add('open'); drawDeviceSeverityHistogram(rec); });
drawerClose.onclick=()=> sideDrawer.classList.remove('open');
function renderDeviceDrawer(d){ const cc=d.cve_counts||{}; const des = d.release_designation?designationBadge(d.release_designation):''; return `<h3 style='margin:4px 0 8px;'>${d.host}</h3><div style='font-size:11px; margin-bottom:8px;'>Model: ${d.model||'-'} | Platform: ${d.platform||'-'} | Version: ${d.current_version||'-'} | Rec: ${d.recommended_version||'-'} ${des}</div><div style='margin:4px 0;'>Recommendation: ${d.recommendation||'-'}</div><div>CPU: ${d.cpu_usage||'-'} | Ports: ${d.connected_count||0}/${d.total_interfaces||0} | Uptime: ${d.uptime||'-'}</div><div style='margin:6px 0;'>Severity: C ${cc.Critical||0} / H ${cc.High||0} / M ${cc.Medium||0} / L ${cc.Low||0}</div><div style='margin:6px 0;'>URL: ${d.final_url?`<a href='${d.final_url}' target='_blank'>image</a>`:'-'}</div><canvas class='inline-spark' id='cpu-spark' width='120' height='30'></canvas><h4 style='margin:10px 0 4px;font-size:12px;'>Severity Histogram</h4><canvas id='severity-hist' width='320' height='120' style='background:#14181f;border:1px solid #222a33;border-radius:6px;'></canvas><h4 style='margin:10px 0 4px;font-size:12px;'>Raw JSON</h4><pre style='max-height:180px;'>${escapeHtml(JSON.stringify(d,null,2))}</pre>`; }
function drawDeviceSeverityHistogram(d){ const canvas=document.getElementById('severity-hist'); if(!canvas) return; try{ const ctx=canvas.getContext('2d'); ctx.clearRect(0,0,canvas.width,canvas.height); const counts={Critical:0,High:0,Medium:0,Low:0,...(d.cve_counts||{})}; const keys=['Critical','High','Medium','Low']; const colors={Critical:'var(--critical)',High:'var(--high)',Medium:'var(--medium)',Low:'var(--low)'}; const max=Math.max(1,...keys.map(k=>counts[k]||0)); const barW=(canvas.width-60)/keys.length; ctx.font='12px system-ui'; ctx.textBaseline='middle'; keys.forEach((k,i)=>{ const v=counts[k]||0; const x=40+i*barW; const h=(v/max)*(canvas.height-40); const y=canvas.height-20-h; ctx.fillStyle=getComputedStyle(document.body).getPropertyValue(colors[k]); ctx.fillRect(x+4,y,barW-12,h); ctx.fillStyle='#e6e9ef'; ctx.fillText(String(v), x+8, y-10); ctx.fillStyle='#8892a0'; ctx.fillText(k[0], x+barW/2-4, canvas.height-10); }); ctx.strokeStyle='#444d58'; ctx.beginPath(); ctx.moveTo(30,canvas.height-20); ctx.lineTo(canvas.width-10,canvas.height-20); ctx.stroke(); ctx.fillStyle='#8892a0'; ctx.textAlign='right'; ctx.fillText('Severity', 28, 12); }catch(err){ console.warn('severity histogram error', err); } }
function escapeHtml(s){ return s.replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }
// Sorting
Array.from(document.querySelectorAll('#devices-table thead th[data-sort]')).forEach(th=>{ th.style.cursor='pointer'; th.addEventListener('click', ()=>{ const key=th.getAttribute('data-sort'); if(sortState.key===key){ sortState.dir*=-1; } else { sortState.key=key; sortState.dir=1; } persistState(); renderTable(); }); });
// Theme & density
themeToggle.onclick=()=>{ document.body.classList.toggle('light'); persistState(); };
densityToggle.onclick=()=>{ document.body.classList.toggle('density-condensed'); persistState(); };
// Column visibility
columnsBtn.onclick=()=>{ columnsMenu.style.display=columnsMenu.style.display==='none'?'block':'none'; };
columnsMenu.addEventListener('change', e=>{ if(e.target.matches('input[type=checkbox][data-col]')){ const col=e.target.getAttribute('data-col'); toggleColumn(col, e.target.checked); persistState(); } });
document.addEventListener('click', e=>{ if(!columnsMenu.contains(e.target) && e.target!==columnsBtn) columnsMenu.style.display='none'; });
function toggleColumn(col, show){ document.querySelectorAll(`[data-col='${col}']`).forEach(c=> c.style.display=show?'':'none'); }
function applyColumnVisibility(){ if(!columnsMenu) return; columnsMenu.querySelectorAll("input[type=checkbox][data-col]").forEach(ch=>{ const col=ch.getAttribute('data-col'); toggleColumn(col, ch.checked); }); }
// Export (updated)
let exportInProgress = false;
let lastExportAt = 0;
let exportCountWindow = {count:0, start: Date.now()};
let exportDisabled = false;
exportCsvBtn.onclick = (e) => exportData('csv', e);
exportJsonBtn.onclick = (e) => exportData('json', e);
// Structured CSV builder (Excel-friendly, stable column order, raw values)
function buildCsv(){
  const cols = [
    'host','alias_name','model','platform','current_version','recommended_version','release_designation','recommendation','cpu_usage','connected_count','total_interfaces','cve_critical','cve_high','cve_medium','cve_low','uptime','end_of_life','final_url'
  ];
  const header = cols.join(',');
  function esc(v){ if(v===null||v===undefined) return ''; if(typeof v==='string'){ const needs = /[",\n]/.test(v); const s=v.replace(/"/g,'""'); return needs?`"${s}"`:s; } return v; }
  const lines = lastRenderedRows.map(d=>{
    const cc = d.cve_counts||{};
    const rowObj = {
      host:d.host,
      alias_name:d.alias_name||'',
      model:d.model||'',
      platform:d.platform||'',
      current_version:d.current_version||'',
      recommended_version:d.recommended_version||'',
      release_designation:d.release_designation||'',
      recommendation:d.recommendation||'',
      cpu_usage:d.cpu_usage||'',
      connected_count:d.connected_count||'',
      total_interfaces:d.total_interfaces||'',
      cve_critical:cc.Critical||0,
      cve_high:cc.High||0,
      cve_medium:cc.Medium||0,
      cve_low:cc.Low||0,
      uptime:d.uptime||'',
      end_of_life:d.end_of_life||'',
      final_url:d.final_url||''
    };
    return cols.map(c=> esc(rowObj[c])).join(',');
  });
  return header+'\n'+lines.join('\n');
}
function exportData(fmt, evt){
  if(exportDisabled){ console.warn('Export disabled due to excessive triggers'); return; }
  // Only allow genuine user gesture (mouse/keyboard) not programmatic calls
  if(!evt || !evt.isTrusted){ console.warn('Blocked non-user initiated export'); return; }
  const now = Date.now();
  if(now - exportCountWindow.start > 10000){ // reset 10s window
    exportCountWindow.start = now; exportCountWindow.count=0;
  }
  exportCountWindow.count++;
  if(exportCountWindow.count > 5){
    exportDisabled = true;
    openModal('Export Disabled', '<p>Export triggered too many times automatically and was suspended.<br/>Reload the page to re-enable.</p>');
    return;
  }
  // Hard throttle: 2s min interval
  if(now - lastExportAt < 2000) { console.warn('Export throttled'); return; }
  if(exportInProgress) { console.warn('Export already in progress'); return; }
  exportInProgress = true; lastExportAt = now;
  setTimeout(()=>{ exportInProgress=false; }, 1200);
  try {
    if(fmt==='csv'){
      const csv = buildCsv();
      if(evt.shiftKey){
        const blob = new Blob([csv], {type:'text/csv;charset=utf-8'});
        const url = URL.createObjectURL(blob);
        window.open(url, '_blank');
        setTimeout(()=>URL.revokeObjectURL(url), 5000);
      } else {
        downloadFile(`devices_${currentBatch||'latest'}.csv`, csv, 'text/csv');
      }
    } else {
      const rows = [...devicesTableBody.querySelectorAll('tr')].map(tr=> JSON.parse(tr.dataset.raw||'{}'));
      downloadFile(`devices_${currentBatch||'latest'}.json`, JSON.stringify(rows,null,2), 'application/json');
    }
  } catch(err){
    console.error('Export failed', err);
    openModal('Export Error', `<pre>${(err && err.message)||err}</pre>`);
  }
}
// File download helper (was missing after refactor)
function downloadFile(name, content, type){
  try {
    const blob = new Blob([content], {type: type + ';charset=utf-8'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.style.display='none';
    a.href = url; a.download = name;
    document.body.appendChild(a);
    requestAnimationFrame(()=>{
      a.click();
      // Remove immediately to avoid reflows causing re-trigger in some buggy extensions
      a.remove();
      setTimeout(()=> URL.revokeObjectURL(url), 1500);
    });
  } catch(err){
    console.error('Download failed', err);
    openModal('Export Error', `<pre>${(err && err.message)||err}</pre>`);
  }
}
// Summaries & charts
async function loadSummaries(){ const data=await fetchJSON('/api/batch_summaries?limit=30'); summariesCache=data.summaries||[]; drawTrend(); }
function drawTrend(){ if(!trendSpark) return; const ctx=trendSpark.getContext('2d'); ctx.clearRect(0,0,trendSpark.width,trendSpark.height); const crit=summariesCache.slice().reverse().map(r=>r.devices_with_critical_cves||0); const high=summariesCache.slice().reverse().map(r=>r.total_high_cves||0); const all=crit.length; if(!all) return; const max=Math.max(...crit,...high,1); const w=trendSpark.width; const h=trendSpark.height; function line(data,color){ ctx.beginPath(); data.forEach((v,i)=>{ const x=i/(all-1)*w; const y=h-(v/max)*h; if(i===0) ctx.moveTo(x,y); else ctx.lineTo(x,y); }); ctx.strokeStyle=color; ctx.lineWidth=1.5; ctx.stroke(); } line(high,'#ff9f43'); line(crit,'#e55353'); }
function drawSeverityPie(){ if(!severityPie) return; const ctx=severityPie.getContext('2d'); ctx.clearRect(0,0,severityPie.width,severityPie.height); const agg={Critical:0,High:0,Medium:0,Low:0}; rawDevices.forEach(d=>{ const c=d.cve_counts||{}; agg.Critical+=c.Critical||0; agg.High+=c.High||0; agg.Medium+=c.Medium||0; agg.Low+=c.Low||0; }); const sum=Object.values(agg).reduce((a,b)=>a+b,0); if(sum===0){ ctx.fillStyle='#666'; ctx.font='12px system-ui'; ctx.textAlign='center'; ctx.fillText('No CVE data', severityPie.width/2, severityPie.height/2); sevLegend.innerHTML=''; return; } let start=0; const colors=['var(--critical)','var(--high)','var(--medium)','var(--low)']; Object.entries(agg).forEach(([k,v],i)=>{ const angle=(v/sum)*Math.PI*2; ctx.beginPath(); ctx.moveTo(80,80); ctx.arc(80,80,70,start,start+angle); ctx.closePath(); ctx.fillStyle=colors[i]; ctx.fill(); start+=angle; }); sevLegend.innerHTML=Object.entries(agg).map(([k,v],i)=>`<span><i style='background:${colors[i]}'></i>${k} ${v}</span>`).join(''); }
function drawUpgradePie(){ if(!upgradePie) return; const ctx=upgradePie.getContext('2d'); ctx.clearRect(0,0,upgradePie.width,upgradePie.height); let need=0, same=0; rawDevices.forEach(d=>{ if(d.upgrade_recommended) need++; else same++; }); const total=need+same; if(total===0){ ctx.fillStyle='#666'; ctx.font='12px system-ui'; ctx.textAlign='center'; ctx.fillText('No devices', upgradePie.width/2, upgradePie.height/2); return; } const data=[need,same]; const colors=['var(--accent)','var(--muted)']; let start=0; data.forEach((v,i)=>{ const angle=(v/total)*Math.PI*2; ctx.beginPath(); ctx.moveTo(80,80); ctx.arc(80,80,70,start,start+angle); ctx.closePath(); ctx.fillStyle=colors[i]; ctx.fill(); start+=angle; }); }
// State persistence
function persistState(){ const state={ batch:currentBatch, filters:{host:filterHost.value, model:filterModel.value, rec:filterRec.value, sev:Array.from(sevFilters).filter(c=>c.checked).map(c=>c.value)}, sort:sortState, theme:document.body.classList.contains('light'), density:document.body.classList.contains('density-condensed')}; localStorage.setItem('dashState', JSON.stringify(state)); const params=new URLSearchParams(); if(currentBatch) params.set('batch', currentBatch); if(filterHost.value) params.set('host', filterHost.value); if(filterModel.value) params.set('model', filterModel.value); if(filterRec.value) params.set('rec', filterRec.value); history.replaceState(null,'','?'+params.toString()); }
function restoreState(){ try{ const s=JSON.parse(localStorage.getItem('dashState')||'{}'); if(s.theme) document.body.classList.add('light'); if(s.density) document.body.classList.add('density-condensed'); if(s.filters){ filterHost.value=s.filters.host||''; filterModel.value=s.filters.model||''; filterRec.value=s.filters.rec||''; const set=new Set(s.filters.sev||[]); sevFilters.forEach(c=> c.checked=set.has(c.value)); } if(s.sort) sortState=s.sort; if(s.batch) currentBatch=s.batch; }catch(e){} const urlParams=new URLSearchParams(location.search); ['host','model','rec'].forEach(k=>{ if(urlParams.get(k)){ if(k==='host') filterHost.value=urlParams.get(k); if(k==='model') filterModel.value=urlParams.get(k); if(k==='rec') filterRec.value=urlParams.get(k); }}); if(urlParams.get('batch')) currentBatch=urlParams.get('batch'); }
function initLegend(){ sevLegend.innerHTML=['Critical','High','Medium','Low'].map(sev=>`<span><i style='background:var(--${sev.toLowerCase()})'></i>${sev}</span>`).join(''); }
viewLogBtn.onclick=async ()=>{ if(!currentBatch) return; try{ const raw=await fetchText(`/api/batch/${currentBatch}/log`); const esc= s=>s.replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); const lines=raw.split(/\r?\n/).map(l=>{ const safe=esc(l); if(/\bWARN(ING)?\b/i.test(l)) return `<span class='log-warn'>${safe}</span>`; return safe; }); openModal('Log '+currentBatch, `<pre class='log-output'>${lines.join('\n')}</pre>`);}catch(err){ openModal('Error', `<pre>${err}</pre>`);} };
viewMailBtn.onclick=async ()=>{ if(!currentBatch) return; try{ const txt=await fetchText(`/api/batch/${currentBatch}/mail`); openModal('Mail '+currentBatch, `<pre>${txt.replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}</pre>`);}catch(err){ openModal('Error', `<pre>${err}</pre>`);} };
// Fallback: open CVE URL if user clicks the list item (in case anchor click is blocked by extensions)
modalBody.addEventListener('click', (e)=>{
  const a = e.target.closest('a[href]');
  if (a) {
    try { e.preventDefault(); window.open(a.href, '_blank', 'noopener'); } catch(_){}
    return;
  }
  // If a designation badge is clicked within modal content, open info
  const des = e.target.closest('[data-desig]');
  if(des){ const code = des.getAttribute('data-desig'); openDesignation(code); return; }
  const li = e.target.closest('li[data-url]');
  if (!li) return;
  const url = li.getAttribute('data-url');
  if (url) {
    try { window.open(url, '_blank', 'noopener'); } catch(_){}
  }
});

// Ensure wheel/touch scroll is applied to modal body reliably
(function ensureModalScroll(){
  if(!modal || !modalBody) return;
  // Route wheel to modal body and prevent background scroll
  modal.addEventListener('wheel', (e)=>{
    // ignore if event originates outside the modal panel
    if(!e.target || !modal.contains(e.target)) return;
    // If the target is inside the modal, consume the event
    const el = modalBody;
    if(!el) return;
    const atTop = el.scrollTop <= 0;
    const atBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 1;
    if((e.deltaY < 0 && atTop) || (e.deltaY > 0 && atBottom)){
      // Block bounce to backdrop/body
      e.preventDefault();
    } else {
      e.preventDefault();
      el.scrollTop += e.deltaY;
    }
  }, { passive:false });

  // Basic touch support routing for mobile
  let touchY = null;
  modal.addEventListener('touchstart', (e)=>{
    if(!e.target || !modal.contains(e.target)) return;
    touchY = e.touches && e.touches.length ? e.touches[0].clientY : null;
  }, { passive:true });
  modal.addEventListener('touchmove', (e)=>{
    if(touchY==null) return;
    const el = modalBody; if(!el) return;
    const y = e.touches && e.touches.length ? e.touches[0].clientY : null;
    if(y==null) return;
    const dy = touchY - y;
    const atTop = el.scrollTop <= 0;
    const atBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 1;
    if((dy < 0 && atTop) || (dy > 0 && atBottom)){
      e.preventDefault();
    } else {
      e.preventDefault();
      el.scrollTop += dy;
      touchY = y;
    }
  }, { passive:false });

  // Keyboard scrolling for accessibility and reliability
  modal.addEventListener('keydown', (e)=>{
    const el = modalBody; if(!el) return;
    const key = e.key;
    const page = Math.max(40, el.clientHeight - 40);
    let delta = 0;
    if(key === 'ArrowDown') delta = 40;
    else if(key === 'ArrowUp') delta = -40;
    else if(key === 'PageDown') delta = page;
    else if(key === 'PageUp') delta = -page;
    else if(key === 'Home') { el.scrollTop = 0; e.preventDefault(); return; }
    else if(key === 'End') { el.scrollTop = el.scrollHeight; e.preventDefault(); return; }
    if(delta !== 0){
      e.preventDefault();
      el.scrollTop += delta;
    }
  });
})();

// Keyboard activation for designation badges (Enter/Space)
document.addEventListener('keydown', (e)=>{
  const active = document.activeElement;
  if(!active) return;
  if(!active.matches || !active.matches('.desig')) return;
  if(e.key === 'Enter' || e.key === ' '){
    const code = active.getAttribute('data-desig');
    if(code){ e.preventDefault(); openDesignation(code); }
  }
});

// Recompute modal body max-height on resize
window.addEventListener('resize', ()=>{
  if(modal.style.display !== 'flex') return;
  try{
    const modalPanel = modal.querySelector('.modal');
    if(!modalPanel) return;
    const styles = getComputedStyle(modalPanel);
    const paddingTop = parseFloat(styles.paddingTop)||0;
    const paddingBottom = parseFloat(styles.paddingBottom)||0;
    const header = modalPanel.querySelector('h3');
    const headerH = header ? header.getBoundingClientRect().height : 0;
    const chrome = paddingTop + paddingBottom + headerH + 10;
    const maxH = Math.max(120, Math.min(window.innerHeight*0.85 - chrome, window.innerHeight - 2*24));
    modalBody.style.maxHeight = maxH + 'px';
  }catch(_){ }
});
(async function init(){ restoreState(); await loadBatchList(); await loadDevices(); await loadSummaries(); initLegend(); })();

"""HTML/JS of the admin page (data update flow). AI-assisted: written with Claude (Anthropic), reviewed by the team."""
from __future__ import annotations

import html


def shell(title: str, body: str) -> str:
    return f"""<!doctype html><html lang=pt-BR><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<meta name=robots content=noindex><title>{html.escape(title)} · Calendário de Focos</title>
<link rel=preconnect href=https://fonts.googleapis.com>
<link rel=stylesheet href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&family=Space+Grotesk:wght@600;700&display=swap">
<style>{CSS}</style></head><body>{body}</body></html>"""


CSS = """
:root{--bg:#eceff2;--surface:#fff;--surface-2:#f4f6f8;--fg:#1a1f25;--muted:#5b6570;--line:#d9dde2;--accent:#c2410c;--accent-soft:rgba(194,65,12,.1);
 --ok:#23704a;--ok-soft:rgba(35,112,74,.11);--warn:#9a6700;--warn-soft:#fff6db;--crit:#b42318;--crit-soft:rgba(180,35,24,.09);
 --f-d:"Space Grotesk","Helvetica Neue",Arial,sans-serif;--f-b:"IBM Plex Sans",system-ui,sans-serif;--f-m:"IBM Plex Mono",ui-monospace,monospace}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 var(--f-b);padding-bottom:90px}
button,input{font:inherit;color:inherit}:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
header{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;padding:12px max(16px,env(safe-area-inset-left));background:var(--surface);border-bottom:1px solid var(--line)}
h1{font:700 19px/1.2 var(--f-d);margin:0}h2{font:600 17px/1.2 var(--f-d);margin:0}h3{font:600 13px var(--f-b);margin:12px 0 6px}
small,.muted{color:var(--muted)}nav{display:flex;gap:14px;align-items:center}nav a{color:var(--fg)}
main{max-width:1100px;margin:0 auto;padding:16px;display:flex;flex-direction:column;gap:14px}main.narrow{max-width:420px}
section,.tile{background:var(--surface);border:1px solid var(--line);border-radius:10px}
section{padding:16px 18px;display:flex;flex-direction:column;gap:10px}
.tiles{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
.tile{padding:12px 14px;display:flex;flex-direction:column;gap:2px;min-width:0}
.tile .k{font:500 10.5px var(--f-m);letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
.tile .v{font:600 22px var(--f-d)}.tile .d{font-size:12px;color:var(--muted)}
.tile.new{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-soft)}
.step{display:grid;grid-template-columns:36px minmax(0,1fr);gap:14px}
.num{width:32px;height:32px;border-radius:50%;display:grid;place-items:center;font:700 15px var(--f-d);background:var(--surface-2);border:1px solid var(--line)}
.step.done .num{background:var(--ok);border-color:var(--ok);color:#fff}.step.active .num{background:var(--accent);border-color:var(--accent);color:#fff}
.sh{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap}
.chip{display:inline-flex;align-items:center;gap:5px;font:600 11px var(--f-m);padding:2px 8px;border-radius:999px;background:var(--surface-2);color:var(--muted);white-space:nowrap}
.chip.ok{background:var(--ok-soft);color:var(--ok)}.chip.warn{background:var(--warn-soft);color:var(--warn)}.chip.crit{background:var(--crit-soft);color:var(--crit)}.chip.acc{background:var(--accent-soft);color:var(--accent)}
.two{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(0,1fr);gap:12px}
.box{border:1px solid var(--line);border-radius:8px;padding:12px;display:flex;flex-direction:column;gap:8px;min-width:0}
.drop{border:2px dashed var(--line);border-radius:10px;padding:22px 14px;text-align:center;display:flex;flex-direction:column;gap:6px;align-items:center;cursor:pointer;transition:background .15s,border-color .15s}
.drop:hover,.drop.over{border-color:var(--accent);background:var(--accent-soft)}
.drop b{font:600 15px var(--f-d)}
.btn{border:1px solid var(--line);background:var(--surface-2);border-radius:7px;padding:7px 13px;font-weight:500;cursor:pointer}
.btn:hover{border-color:var(--muted)}.btn.primary{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:600}
.btn.ok{background:var(--ok);border-color:var(--ok);color:#fff;font-weight:600}.btn.link{border:0;background:none;color:var(--accent);padding:0;text-decoration:underline}
.btn[disabled]{opacity:.45;cursor:not-allowed}
.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
input[type=date]{border:1px solid var(--line);border-radius:6px;padding:5px 8px}
.ups{display:flex;flex-direction:column;gap:6px;margin:0;padding:0;list-style:none}
.ups li{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:4px 10px;font-size:12.5px}
.bar{grid-column:1/-1;height:6px;border-radius:3px;background:var(--surface-2);overflow:hidden}.bar i{display:block;height:100%;background:var(--accent);transition:width .2s}
.bar.big{height:10px}.bar.ok i{background:var(--ok)}.bar.crit i{background:var(--crit)}
table{width:100%;border-collapse:collapse;font-size:12.5px}th,td{padding:6px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{font-size:11px;font-weight:500;color:var(--muted)}td.n{font-family:var(--f-m);text-align:right;white-space:nowrap}
tr.off td{opacity:.5}.tbl{overflow-x:auto}
.sw{position:relative;width:34px;height:20px;display:inline-block}.sw input{opacity:0;width:0;height:0}
.sw span{position:absolute;inset:0;border-radius:999px;background:#c9cfd6;transition:.15s;cursor:pointer}
.sw span::after{content:"";position:absolute;width:14px;height:14px;left:3px;top:3px;border-radius:50%;background:#fff;transition:.15s}
.sw input:checked+span{background:var(--ok)}.sw input:checked+span::after{transform:translateX(14px)}
.cmp{display:grid;grid-template-columns:auto minmax(0,1fr) minmax(0,1fr);gap:4px 16px;font-size:13px}
.cmp .h{font:500 10.5px var(--f-m);letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}.cmp .new{font-weight:600}
ul.av{margin:0;padding-left:18px;font-size:12.5px}
.callout{padding:10px 12px;border-radius:8px;background:var(--surface-2);border:1px solid var(--line);font-size:13px}
.callout.acc{background:var(--accent-soft);border-color:rgba(194,65,12,.3)}.callout.warn{background:var(--warn-soft);border-color:#f1dc9a}
.jobbar{position:fixed;left:0;right:0;bottom:0;background:var(--fg);color:#fff;padding:10px max(16px,env(safe-area-inset-left)) calc(10px + env(safe-area-inset-bottom));display:none;z-index:10}
.jobbar.show{display:block}.jobbar .in{max-width:1100px;margin:0 auto;display:flex;flex-direction:column;gap:6px}
.jobbar .bar{background:rgba(255,255,255,.18)}.jobbar summary{cursor:pointer;font-size:12px;opacity:.8}
.jobbar pre{max-height:200px;overflow:auto;background:rgba(0,0,0,.35);border-radius:6px;padding:8px;font:12px var(--f-m);white-space:pre-wrap;margin:6px 0 0}
.toast{position:fixed;right:16px;top:16px;background:var(--fg);color:#fff;padding:9px 14px;border-radius:8px;font-size:13px;opacity:0;transition:opacity .2s;pointer-events:none;z-index:20;max-width:360px}
.toast.show{opacity:1}
form.login{display:flex;flex-direction:column;gap:10px}form.login label{display:flex;flex-direction:column;gap:4px}
form.login input{padding:8px 10px;border:1px solid var(--line);border-radius:7px}
.warn{color:var(--warn)}
@media (max-width:820px){.tiles,.two{grid-template-columns:1fr}.step{grid-template-columns:1fr}.num{display:none}}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
"""


def page_html(csrf: str) -> str:
    body = f"""
<header><div><h1>Atualizar dados</h1><small>Traga dados novos, confira, processe e publique, nesta ordem.</small></div>
<nav><a href="/" target=_blank rel=noopener>Calendário ↗</a><a href="/sala" target=_blank rel=noopener>Sala de Situação ↗</a>
<form method=post action=/admin/logout><input type=hidden name=csrf value={html.escape(csrf)}><button class="btn link">Sair</button></form></nav></header>
<main>
  <div id=online></div>
  <div class=tiles id=tiles></div>

  <section class=step id=s1><div class=num>1</div><div>
    <div class=sh><h2>Trazer dados novos</h2><span id=c1></span></div>
    <div class=two style="margin-top:10px">
      <div class=box>
        <label class=drop id=drop for=fileinput>
          <b>Arraste os arquivos aqui</b>
          <span class=muted>Pacote do time de dados (.tar.gz, .zip) ou CSVs <code>focos_brutos*</code> / <code>focos_mensais*</code></span>
          <span class="btn">Escolher arquivos</span>
        </label>
        <input type=file id=fileinput multiple accept=".csv,.gz,.tgz,.tar,.zip" hidden>
        <ul class=ups id=ups></ul>
        <small class=muted>Do pacote, só os CSVs de focos são guardados. Um arquivo com o mesmo nome substitui o anterior.</small>
      </div>
      <div class=box>
        <b>Buscar dias recentes no NASA FIRMS</b>
        <span class=muted>MODIS, S-NPP, NOAA-20 e NOAA-21 da América do Sul. O período já começa no dia seguinte ao último dado.</span>
        <div class=row><label>De <input type=date id=fstart></label><label>até <input type=date id=fend></label></div>
        <label class=row><input type=checkbox id=fproc checked> Processar em seguida</label>
        <div class=row><button class="btn primary" id=fbtn>Buscar no FIRMS</button><span id=fnote class=muted></span></div>
      </div>
    </div>
  </div></section>

  <section class=step id=s2><div class=num>2</div><div>
    <div class=sh><h2>Conferir arquivos</h2><span id=c2></span></div>
    <p class=muted style="margin:4px 0 8px">Desligue um arquivo para deixá-lo de fora do processamento sem apagar.</p>
    <div class=tbl id=files></div>
  </div></section>

  <section class=step id=s3><div class=num>3</div><div>
    <div class=sh><h2>Processar e aplicar no painel</h2><span id=c3></span></div>
    <p class=muted style="margin:4px 0 8px">Junta os arquivos ligados sem duplicar focos e prepara uma versão nova. O painel só muda quando você clicar em <b>Aplicar</b>.</p>
    <div class=row><button class="btn primary" id=pbtn>Processar dados</button><span id=pnote class=muted></span></div>
    <div id=cand></div>
  </div></section>

  <section class=step id=s4><div class=num>4</div><div>
    <div class=sh><h2>Publicar no site</h2><span id=c4></span></div>
    <div id=pub></div>
  </div></section>

  <div id=rollback></div>
</main>
<div class=jobbar id=jobbar><div class=in>
  <div class=row style="justify-content:space-between"><b id=jtitle></b><span id=jpct style="font-family:var(--f-m)"></span></div>
  <div class="bar big" id=jbarw><i id=jbar style="width:0"></i></div>
  <details id=jdet><summary>Ver detalhes</summary><pre id=jlog></pre></details>
</div></div>
<div class=toast id=toast role=status aria-live=polite></div>
<script>
const CSRF={csrf!r};
{JS}
</script>"""
    return shell("Atualizar dados", body)


JS = r"""
const $=id=>document.getElementById(id);
const nf=new Intl.NumberFormat('pt-BR');
const fmt=n=>nf.format(Math.round(n||0));
const mb=b=>b>=1e9?(b/1e9).toFixed(1).replace('.',',')+' GB':(b/1e6).toFixed(b>1e7?0:1).replace('.',',')+' MB';
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const dt=s=>!s?'—':(s.length===7?s.slice(5,7)+'/'+s.slice(0,4):s.slice(8,10)+'/'+s.slice(5,7)+'/'+s.slice(0,4));
const KIND={conferir:'Conferindo arquivos',processar:'Processando dados',firms:'Baixando do NASA FIRMS',publicar:'Publicando no site'};
let S=null,timer=null,datesSet=false,wasRunning=false;

function toast(m){const t=$('toast');t.textContent=m;t.classList.add('show');clearTimeout(t._h);t._h=setTimeout(()=>t.classList.remove('show'),3500)}
async function api(action,body){
  const r=await fetch('/admin/api/'+action,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF':CSRF},body:JSON.stringify(body||{})});
  let j={};try{j=await r.json()}catch(e){}
  if(!r.ok||j.ok===false){toast(j.msg||('Não foi possível concluir ('+r.status+').'));return false}
  return true}
async function load(){
  try{const r=await fetch('/admin/api/state');if(r.status===403){location.reload();return}S=await r.json();render()}
  catch(e){toast('Sem conexão com o servidor.')}
  clearTimeout(timer);timer=setTimeout(load,S&&S.job.running?1500:15000)}

function chip(cls,t){return `<span class="chip ${cls}">${esc(t)}</span>`}
function setStep(n,state,label){$('s'+n).className='step '+(state||'');$('c'+n).innerHTML=label||''}

function render(){
  const L=S.live,C=S.candidate,J=S.job,local=S.mode==='local';
  $('online').innerHTML=local?'':`<div class="callout warn"><b>Este é o site publicado.</b> Aqui você só consulta a situação dos dados. Para atualizar, use o admin na máquina do time (passos 1 a 4) e publique.</div>`;
  ['s1','s2','s3','s4'].forEach(id=>$(id).hidden=!local);
  const last=S.publish.history[0];
  $('tiles').innerHTML=
    tile('No painel',L?fmt(L.total_focos)+' focos':'Sem dados',L?`${dt(L.inicio)} a ${dt(L.fim)} · processado em ${esc(L.gerado_em.slice(0,16))}`:'Processe para começar')+
    tile('Versão nova',C?fmt(C.total_focos)+' focos':'Nenhuma',C?`${dt(C.inicio)} a ${dt(C.fim)} · aguardando Aplicar`:'Processe para gerar',C?'new':'')+
    tile('Online',last?dt(last.fim):(local?'—':'Este site'),last?`publicado em ${esc(last.quando)}`:(S.publish.space?esc(S.publish.space):''));
  if(!datesSet&&S.firms){$('fstart').value=S.firms.start;$('fend').value=S.firms.end;datesSet=true}
  $('fbtn').disabled=J.running||!S.firms.key;$('fnote').textContent=S.firms.key?'':'Defina FIRMS_MAP_KEY no servidor.';
  // step 1/2
  const F=S.files,active=F.filter(f=>f.active),brutos=active.filter(f=>f.tipo==='brutos');
  setStep(1,F.length?'done':'active',F.length?chip('ok',F.length+' arquivo'+(F.length>1?'s':'')):chip('acc','Comece aqui'));
  const unchecked=F.filter(f=>!f.stats).length,problems=F.filter(f=>f.stats&&(f.stats.erro||(f.stats.faltando||[]).length)).length;
  setStep(2,!F.length?'':problems?'active':unchecked?'active':'done',!F.length?'':problems?chip('crit',problems+' com problema'):unchecked?chip('warn',unchecked+' a conferir'):chip('ok','Tudo conferido'));
  $('files').innerHTML=F.length?filesTable(F,J.running)+(unchecked?`<div class=row style="margin-top:8px"><button class="btn" onclick="run('inspect')" ${J.running?'disabled':''}>Conferir ${unchecked} arquivo${unchecked>1?'s':''}</button><span class=muted>Lê cada arquivo e mostra período, satélites e colunas.</span></div>`:''):'<p class=muted>Nenhum arquivo ainda. Envie no passo 1.</p>';
  // step 3
  $('pbtn').disabled=J.running||!brutos.length;
  $('pnote').textContent=brutos.length?`${brutos.length} arquivo${brutos.length>1?'s':''} de focos ligado${brutos.length>1?'s':''}`:'Ligue pelo menos um focos_brutos no passo 2.';
  setStep(3,C?'active':(L?'done':''),C?chip('acc','Versão nova pronta'):(L?chip('ok','Painel atualizado'):''));
  $('cand').innerHTML=C?candidate(L,C,S.candidate_diff,J.running):'';
  // step 4
  const P=S.publish,pub=P.history[0],stale=!pub||(L&&(pub.fim!==L.fim.slice(0,10)||pub.total_focos!==L.total_focos));
  setStep(4,!P.available?'':stale?'active':'done',!P.available?chip('','Indisponível'):stale?chip('warn','Site desatualizado'):chip('ok','Site em dia'));
  $('pub').innerHTML=publishBox(P,L,stale,J.running);
  // rollback
  $('rollback').innerHTML=local&&S.prev?`<section><div class=sh><div><h2>Voltar à versão anterior</h2><span class=muted>${fmt(S.prev.total_focos)} focos, ${dt(S.prev.inicio)} a ${dt(S.prev.fim)}, processada em ${esc(S.prev.gerado_em.slice(0,16))}.</span></div><button class=btn onclick="confirmRun('rollback','Trocar o painel pela versão anterior?')" ${J.running?'disabled':''}>Voltar à versão anterior</button></div></section>`:'';
  renderJob(J);
}
function tile(k,v,d,cls){return `<div class="tile ${cls||''}"><span class=k>${k}</span><span class=v>${v}</span><span class=d>${d}</span></div>`}
function filesTable(F,busy){
  return `<table><thead><tr><th>Usar</th><th>Arquivo</th><th class=n>Tamanho</th><th>Período</th><th class=n>Linhas</th><th>Conteúdo</th><th></th></tr></thead><tbody>`+
  F.map(f=>{const s=f.stats;let info,period='—',rows='—';
    if(!s)info=chip('warn','não conferido');
    else if(s.erro)info=chip('crit','erro ao ler')+`<div class=muted>${esc(s.erro)}</div>`;
    else{period=`${dt(s.inicio)} a ${dt(s.fim)}`;rows=fmt(s.linhas);
      info=f.tipo==='mensais'?chip('','totais mensais')+' '+chip('',fmt(s.total)+' focos'):
        ((s.faltando||[]).length?chip('crit','falta: '+s.faltando.join(', ')):chip('ok','colunas ok'))+' '+(s.satelites||[]).map(x=>chip('',x)).join(' ')+
        ((s.extras||[]).length?' '+chip('acc','+ '+s.extras.join(', ')):'')+(s.paises?` <span class=muted>${s.paises} países</span>`:'')}
    return `<tr class="${f.active?'':'off'}"><td><label class=sw title="Usar no processamento"><input type=checkbox ${f.active?'checked':''} ${busy?'disabled':''} onchange="run('toggle',{name:'${esc(f.name)}'})"><span></span></label></td>
      <td><b>${esc(f.name)}</b><div class=muted>${f.tipo==='brutos'?'focos individuais':'totais mensais (conferência)'}</div></td><td class=n>${mb(f.size)}</td><td>${period}</td><td class=n>${rows}</td><td>${info}</td>
      <td><button class="btn link" ${busy?'disabled':''} onclick="confirmRun('delete','Apagar ${esc(f.name)}?',{name:'${esc(f.name)}'})">Apagar</button></td></tr>`}).join('')+'</tbody></table>'}
function candidate(L,C,D,busy){
  const rows=[['Focos',L?fmt(L.total_focos):'—',fmt(C.total_focos)+(D&&L?` (${D.delta_focos>=0?'+':''}${fmt(D.delta_focos)})`:'')],
    ['Período',L?`${dt(L.inicio)} a ${dt(L.fim)}`:'—',`${dt(C.inicio)} a ${dt(C.fim)}`],
    ['Satélites',L?L.satelites.join(', '):'—',C.satelites.join(', ')],
    ['Colunas extras',L?(L.colunas_extras.join(', ')||'nenhuma'):'—',C.colunas_extras.join(', ')||'nenhuma'],
    ['Harmonização',L?(L.tem_harmonizacao?'sim':'não'):'—',C.tem_harmonizacao?'sim':'não (falta peso_harm)']];
  const av=(D.novos_avisos.length?`<h3>Avisos novos</h3><ul class=av>${D.novos_avisos.map(a=>`<li class=warn>${esc(a)}</li>`).join('')}</ul>`:'')+
           (D.avisos_resolvidos.length?`<h3>Avisos resolvidos</h3><ul class=av>${D.avisos_resolvidos.map(a=>`<li style="color:var(--ok)">${esc(a)}</li>`).join('')}</ul>`:'');
  return `<div class="callout acc" style="margin-top:10px"><div class=cmp><span class=h></span><span class=h>No painel</span><span class=h>Versão nova</span>`+
    rows.map(r=>`<span class=muted>${r[0]}</span><span>${r[1]}</span><span class=new>${r[2]}</span>`).join('')+`</div>${av}
    <div class=row style="margin-top:10px"><button class="btn ok" onclick="run('apply')" ${busy?'disabled':''}>Aplicar no painel</button>
    <button class=btn onclick="confirmRun('discard','Descartar a versão nova?')" ${busy?'disabled':''}>Descartar</button>
    <span class=muted>Aplicar troca os dados do painel na hora, sem reiniciar.</span></div></div>`}
function publishBox(P,L,stale,busy){
  if(!P.available)return `<p class=muted>${esc(P.reason)}</p>`;
  const h=P.history.map(p=>`<li>${esc(p.quando)}: ${fmt(p.total_focos)} focos, ${dt(p.inicio)} a ${dt(p.fim)}</li>`).join('');
  return `<p class=muted style="margin:4px 0">Envia a versão que está no painel para o site público (${P.site?`<a href="${esc(P.site)}" target=_blank rel=noopener>${esc(P.site.replace('https://',''))}</a>`:esc(P.space)}). Leva alguns minutos: empacota, envia ao GitHub e reinicia o site.</p>
    <div class=row><button class="btn primary" onclick="confirmRun('publish','Publicar a versão do painel no site público?')" ${busy||!L?'disabled':''}>Publicar no site</button>
    <span class=muted>${stale?'O site está com dados diferentes do painel.':'O site já tem esta versão.'}</span></div>
    ${h?`<h3>Últimas publicações</h3><ul class=av>${h}</ul>`:''}`}
function renderJob(J){
  const bar=$('jobbar');const show=J.running||(J.finished&&Date.now()/1000-J.finished<8);
  bar.classList.toggle('show',!!show);
  if(!show){if(wasRunning)wasRunning=false;return}
  $('jtitle').textContent=(KIND[J.kind]||'Tarefa')+(J.running?' · '+(J.stage||''):(J.ok?' · concluído':' · falhou'));
  $('jpct').textContent=J.running?J.pct+'%':(J.ok?'✓':'!');
  $('jbar').style.width=(J.running?J.pct:100)+'%';$('jbarw').className='bar big'+(J.running?'':(J.ok?' ok':' crit'));
  const pre=$('jlog');const atEnd=pre.scrollTop+pre.clientHeight>=pre.scrollHeight-4;pre.textContent=J.log.join('\n');if(atEnd)pre.scrollTop=pre.scrollHeight;
  if(!J.running&&wasRunning){toast(J.ok?(KIND[J.kind]+': concluído.'):('Falhou: '+(J.error||'veja os detalhes')));if(!J.ok)$('jdet').open=true}
  wasRunning=J.running}

async function run(action,body){if(await api(action,body)){if(action==='apply')toast('Painel atualizado.');if(action==='rollback')toast('Versão anterior restaurada.')}load()}
function confirmRun(action,msg,body){if(confirm(msg))run(action,body)}

$('fbtn').onclick=()=>run('firms',{start:$('fstart').value,end:$('fend').value,process:$('fproc').checked});
$('pbtn').onclick=()=>run('process');

// upload with per-file progress
const drop=$('drop'),inp=$('fileinput');
['dragenter','dragover'].forEach(e=>drop.addEventListener(e,ev=>{ev.preventDefault();drop.classList.add('over')}));
['dragleave','drop'].forEach(e=>drop.addEventListener(e,ev=>{ev.preventDefault();drop.classList.remove('over')}));
drop.addEventListener('drop',ev=>send([...ev.dataTransfer.files]));
inp.addEventListener('change',()=>{send([...inp.files]);inp.value=''});
async function send(list){
  if(!list.length)return;
  const ul=$('ups');let any=false;
  for(const f of list){
    const li=document.createElement('li');li.innerHTML=`<span>${esc(f.name)} <span class=muted>${mb(f.size)}</span></span><span class=st>0%</span><div class=bar><i style="width:0"></i></div>`;ul.prepend(li);
    const res=await new Promise(ok=>{const x=new XMLHttpRequest();x.open('POST','/admin/upload');x.setRequestHeader('X-CSRF',CSRF);
      x.upload.onprogress=e=>{if(e.lengthComputable){const p=Math.round(e.loaded/e.total*100);li.querySelector('i').style.width=p+'%';li.querySelector('.st').textContent=p<100?p+'%':'extraindo…'}};
      x.onload=()=>{let j={};try{j=JSON.parse(x.responseText)}catch(e){}ok({status:x.status,j})};x.onerror=()=>ok({status:0,j:{}});
      const fd=new FormData();fd.append('arquivos',f);x.send(fd)});
    const st=li.querySelector('.st');
    if(res.status===200&&res.j.saved&&res.j.saved.length){any=true;st.innerHTML=chip('ok','recebido: '+res.j.saved.join(', '));li.querySelector('.bar').className='bar ok'}
    else{st.innerHTML=chip('crit',res.j.msg||(res.j.skipped&&res.j.skipped.length?'nenhum CSV de focos no arquivo':'falhou ('+res.status+')'));li.querySelector('.bar').className='bar crit'}
    if(res.j.skipped&&res.j.skipped.length&&res.j.saved&&res.j.saved.length)st.innerHTML+=' '+chip('','ignorados: '+res.j.skipped.length)}
  await load();
  if(any&&S.files.some(f=>!f.stats))run('inspect');
}
load();
"""

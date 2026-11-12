#!/usr/bin/env python3
"""TinySLM local monitor. Standard library only; reads the existing queue, never mutates it."""
import argparse
import fcntl
import html
import contextlib
import json
from pathlib import Path
import re
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
GUIDES = ['README.md','dados/README.md','dados/GERAR_CHAT.md','dados/GERAR_CLI.md',
          'notebooks/README.md','notebooks/NOVO_TREINO.md','modelos/README.md']
HTML = r'''<!doctype html>
<html lang="pt"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TinySLM · Painel</title>
<style>
:root{color-scheme:light dark;--bg:light-dark(#f4f7fa,#101827);--fg:light-dark(#172b43,#e4edf8);--card:light-dark(#fff,#19263a);--muted:light-dark(#52677c,#acbdd1);--border:light-dark(#dbe4eb,#34465e);--accent:light-dark(#0a776f,#66dbcc);--soft:light-dark(#e4f4f0,#163b3a);--bad:light-dark(#b13535,#ffaaaa)}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 system-ui,sans-serif}header{background:var(--card);border-bottom:1px solid var(--border);padding:20px 28px;display:flex;justify-content:space-between;align-items:center;gap:15px;flex-wrap:wrap}.brand{font-weight:750;font-size:22px;letter-spacing:-.5px}.brand span{color:var(--accent)}.muted{color:var(--muted)}.small{font-size:13px}main{max-width:1280px;margin:0 auto;padding:24px}nav{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:24px}button,select,input{font:inherit;border:1px solid var(--border);border-radius:8px;padding:9px 12px;background:var(--card);color:var(--fg)}button{cursor:pointer}button:hover{border-color:var(--accent)}button.active{background:var(--accent);color:var(--bg);border-color:var(--accent)}button:disabled{opacity:.45;cursor:default}h1{font-size:26px;line-height:1.25;margin:0 0 8px}h2{font-size:18px;margin:24px 0 12px}h3{font-size:16px;margin:0 0 8px}p{margin:8px 0 16px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(175px,1fr));gap:14px}.card{padding:18px;background:var(--card);border:1px solid var(--border);border-radius:12px}.value{font-size:30px;font-weight:650;letter-spacing:-1px}.pgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px}.tag{display:inline-block;background:var(--soft);color:var(--accent);border-radius:5px;padding:2px 8px;font-size:12px}.toolbar{display:flex;gap:10px;flex-wrap:wrap;align-items:end;margin:18px 0}label{display:flex;flex-direction:column;gap:4px;color:var(--muted)}label input,label select{color:var(--fg)}input[type=search]{min-width:220px}.tablewrap{overflow:auto}table{border-collapse:collapse;width:100%}th,td{padding:12px 10px;text-align:left;border-bottom:1px solid var(--border);vertical-align:top}th{color:var(--muted);font-size:13px}td button{padding:5px 9px;font-size:13px}.pill{font-size:12px;white-space:nowrap}.pager{display:flex;align-items:center;gap:12px;justify-content:flex-end;margin:16px 0}.text{white-space:pre-wrap;overflow-wrap:anywhere}.detail{margin-top:20px;padding:22px;background:var(--card);border:1px solid var(--border);border-radius:12px}.detail code{overflow-wrap:anywhere}blockquote{margin:10px 0 16px;padding:10px 14px;background:var(--soft);border-left:3px solid var(--accent);white-space:pre-wrap;overflow-wrap:anywhere}.message{padding:14px 0;border-bottom:1px solid var(--border)}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.6 ui-monospace,monospace;max-height:480px;overflow:auto;background:var(--bg);padding:15px;border-radius:8px}summary{cursor:pointer;padding:10px 0;color:var(--accent)}#error{color:var(--bad);padding:12px 0}#error:empty{display:none}.statusline{display:flex;gap:14px;align-items:center;flex-wrap:wrap}.statusline label{display:flex;flex-direction:row;align-items:center}.bar{height:10px;border-radius:5px;background:var(--border);overflow:hidden;margin:16px 0 8px}.bar span{height:100%;display:block;background:var(--accent)}a{color:var(--accent)}.empty{padding:26px;color:var(--muted);text-align:center}.mono{font-family:ui-monospace,monospace;font-size:12px;overflow-wrap:anywhere}@media(max-width:640px){header{padding:16px}main{padding:16px}.value{font-size:25px}.grid{grid-template-columns:repeat(2,minmax(0,1fr))}.toolbar label,.toolbar input,.toolbar select{width:100%}.detail{padding:14px}th,td{padding:9px 7px}}
main{max-width:1500px}.reader{display:grid;grid-template-columns:minmax(260px,0.8fr) minmax(0,1.4fr);gap:24px;margin-top:20px}.recipebody{white-space:pre-wrap;overflow-wrap:anywhere;font:15px/1.75 system-ui;max-height:72vh;overflow:auto;padding:18px;background:var(--bg);border-radius:10px}.reader>*{min-width:0}.bubble{margin:12px 0;padding:16px 18px;border:1px solid var(--border);border-radius:12px}.bubble.user{background:var(--bg);margin-right:24px}.bubble.assistant{background:var(--soft);margin-left:24px}.bubble p{margin:8px 0 0}.profilebox{background:var(--bg);padding:14px 18px;border-radius:10px;margin:14px 0}.profilebox p{margin:5px 0}.conversation{border-top:2px solid var(--border);margin-top:20px;padding-top:12px}.reader h2{margin-top:0}.detail{scroll-margin-top:12px}.detailtop{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}.detailtop h2{margin:0}.frameworkhint{color:var(--muted);font-size:14px}@media(max-width:850px){.reader{grid-template-columns:1fr}.recipebody{max-height:340px}.bubble.user,.bubble.assistant{margin-left:0;margin-right:0}}
</style></head><body>
<header><div class="brand">Tiny<span>SLM</span> <span class="muted small">/ produção culinária</span></div><div class="statusline small"><label><input id="live" type="checkbox" checked> Atualizar a cada 30 s · pausa na leitura</label><span id="updated" class="muted">A ligar…</span></div></header>
<main><nav id="tabs" aria-label="Secções"></nav><div id="error" role="alert"></div><section id="view"></section></main>
<script>
'use strict';
const $=s=>document.querySelector(s);
const labels={overview:'Visão geral',personas:'Personas',framework:'Comportamentos',recipes:'Receitas',outputs:'Respostas',jobs:'Pedidos',guides:'Instruções',project:'Projeto e treinos'};
const personas={P1:'Principiante',P2:'Prático',P3:'Restrições',P4:'Adaptação',P5:'Explorador'};
const caps={C1:'Extrair',C2:'Selecionar',C3:'Relacionar',C4:'Aplicar restrições',C5:'Transformar',C6:'Conversar',C7:'Reconhecer lacunas',C8:'Usar ferramentas'};
const states={pending:'Pendente',running:'Em execução',done:'Concluído',manual:'Reservado · chat',error:'Erro',auto_valid:'Validação automática',accepted:'Revisto / aceite',rejected:'Rejeitado',needs_review:'Precisa de revisão'};
const num=v=>Number(v||0).toLocaleString('pt-PT');
const esc=v=>String(v??'').replace(/[&<>"']/g,x=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[x]));
let detailTicket=0;
let tab='overview',config=null,offset=0,filters={q:'',persona:'',capability:'',status:''},selected=null,busy=false,epoch=0;
async function api(path){const r=await fetch(path,{cache:'no-store'});const data=await r.json();if(!r.ok)throw Error(data.error||'Falha ao ler dados');return data;}
function title(text,sub){return '<h1>'+esc(text)+'</h1><p class="muted">'+esc(sub)+'</p>';}
function badge(value){return '<span class="tag">'+esc(states[value]||value)+'</span>';}
function setError(e){$('#error').textContent=e?e.message||String(e):'';}
function option(value,text,selectedValue){return '<option value="'+esc(value)+'"'+(value===selectedValue?' selected':'')+'>'+esc(text)+'</option>';}
function select(id,title,values){return '<label>'+title+'<select id="'+id+'">'+option('','Todos',filters[id])+values.map(([v,t])=>option(v,t,filters[id])).join('')+'</select></label>';}
function renderNav(){ $('#tabs').innerHTML=Object.entries(labels).map(([key,name])=>'<button type="button" data-tab="'+key+'" class="'+(tab===key?'active':'')+'" aria-pressed="'+(tab===key)+'">'+name+'</button>').join('');$('#tabs').querySelectorAll('button').forEach(b=>b.onclick=()=>switchTab(b.dataset.tab)); }
async function switchTab(next){detailTicket++;epoch++;tab=next;offset=0;selected=null;filters={q:'',persona:'',capability:'',status:''};renderNav();await render(true);}
async function overview(){const d=await api('/api/overview');if(tab!=='overview')return;const total=Object.values(d.jobs).reduce((a,b)=>a+b,0),done=d.jobs.done||0;const pct=total?100*done/total:0;
$('#view').innerHTML=title('Acompanhar a produção','O painel lê a mesma fila do gerador. Pode ficar aberto enquanto o Codex trabalha.')+'<div class="grid">'+[['Receitas',d.recipes],['Pedidos em fila',total],['Concluídos',done],['Em execução',d.jobs.running||0],['Exemplos guardados',d.examples_total],['Pedidos com erro',d.jobs.error||0]].map(([k,v])=>'<div class="card"><div class="muted small">'+k+'</div><div class="value">'+num(v)+'</div></div>').join('')+'</div><div class="bar"><span style="width:'+pct+'%"></span></div><p class="small muted">'+pct.toFixed(1)+'% dos pedidos concluídos · '+num(d.jobs.pending)+' pendentes · '+num(d.jobs.manual)+' reservados para chats</p><h2>Personas × comportamentos</h2><div class="tablewrap"><table><thead><tr><th>Persona</th>'+Object.entries(caps).map(([c,n])=>'<th>'+c+'<br>'+esc(n)+'</th>').join('')+'</tr></thead><tbody>'+Object.entries(personas).map(([p,n])=>'<tr><th>'+p+' · '+n+'</th>'+Object.keys(caps).map(c=>'<td>'+num(d.coverage.find(x=>x.persona===p&&x.capability===c)?.n)+'</td>').join('')+'</tr>').join('')+'</tbody></table></div><p class="small muted">Contagens excluem exemplos rejeitados. C8 está reservado para a próxima iteração.</p><h2>Estado dos exemplos</h2><p>'+Object.entries(d.examples).map(([s,n])=>badge(s)+' '+num(n)).join(' · ')+'</p><h2>Últimos pedidos concluídos</h2>'+jobsTable(d.recent)+'<p class="small muted">auto_valid confirma estrutura e verificações mecânicas; não é garantia factual. chatgpt-demo identifica os exemplos iniciais incluídos no pacote.</p><p class="small muted">Tokens comunicados pelo CLI: entrada '+num(d.usage.input_tokens)+' · saída '+num(d.usage.output_tokens)+'. Valores apenas dos pedidos concluídos e guardados; não representam a quota restante.</p>';bindJobButtons();}
function renderPersonas(){ $('#view').innerHTML=title('Personas','Representam a necessidade de quem pergunta. O assistente mantém um tom claro e factual.')+'<div class="pgrid">'+config.personas.map(p=>'<article class="card"><span class="tag">'+esc(p.id)+'</span><h2>'+esc(personas[p.id]||p.name)+'</h2><p>'+esc(p.description)+'</p><button type="button" data-persona="'+esc(p.id)+'">Ver outputs desta persona</button></article>').join('')+'</div>';$('#view').querySelectorAll('[data-persona]').forEach(b=>b.onclick=async()=>{const p=b.dataset.persona;await switchTab('outputs');filters.persona=p;await render(true)});}
function renderFramework(){const desc={C1:'Localizar informação explicitamente presente na receita.',C2:'Escolher os ingredientes ou passos relevantes para o pedido.',C3:'Relacionar detalhes do contexto e explicar uma conclusão sustentada.',C4:'Aplicar preferências, exclusões e requisitos do utilizador.',C5:'Resumir, simplificar ou reorganizar sem alterar o significado.',C6:'Manter referências e informação entre duas trocas de mensagens.',C7:'Reconhecer dados em falta ou contraditórios sem inventar.',C8:'Delegar cálculos e operações em ferramentas determinísticas.'};$('#view').innerHTML=title('Framework de comportamentos','Cada pedido: quatro capacidades entre C1–C5, uma conversa C6 e uma tarefa C7.')+'<div class="pgrid">'+config.capabilities.map(c=>'<article class="card"><span class="tag">'+esc(c.id)+(c.id==='C8'?' · próxima iteração':'')+'</span><h2>'+esc(caps[c.id])+'</h2><p>'+esc(desc[c.id])+'</p><details><summary>Definição original</summary><p>'+esc(c.description)+'</p></details></article>').join('')+'</div><h2>Evidência</h2><p>E0: insuficiente · E1: explícita · E2: derivada do contexto · E3: cálculo (futuro) · E4: nota externa anexada</p><details><summary>Ver prompt comum usado pelo gerador</summary><pre>'+esc(config.prompt)+'</pre></details><p class="small muted">A definição executada em cada pedido fica guardada nesse pedido. Alterar o ficheiro de configuração não reescreve pedidos antigos.</p>';}
function jobsTable(rows){return rows.length?'<div class="tablewrap"><table><thead><tr><th>Receita</th><th>Persona</th><th>Estado</th><th>Professor</th><th>Detalhe</th></tr></thead><tbody>'+rows.map(r=>'<tr><td>'+esc(r.title)+'</td><td>'+esc(r.persona)+'</td><td>'+badge(r.status)+'</td><td>'+esc(r.provider||'—')+'</td><td><button data-job="'+esc(r.id)+'">Abrir</button></td></tr>').join('')+'</tbody></table></div>':'<p class="empty">Ainda não há pedidos nesta seleção.</p>';}
function bindJobButtons(){ $('#view').querySelectorAll('[data-job]').forEach(b=>b.onclick=()=>showDetail('job',b.dataset.job)); }
function filtersHtml(){return '<form id="search" class="toolbar"><label>Pesquisar receita<input id="q" type="search" value="'+esc(filters.q)+'" placeholder="Título ou texto da receita"></label>'+(tab!=='recipes'?select('persona','Persona',Object.entries(personas).map(([p,n])=>[p,p+' · '+n])):'')+(tab==='outputs'?select('capability','Capacidade',Object.entries(caps)): '')+(tab!=='recipes'?select('status','Estado',(tab==='jobs'?['pending','running','done','manual','error']:['auto_valid','accepted','needs_review','rejected']).map(s=>[s,states[s]])):'')+'<button type="submit">Filtrar</button></form>';}
async function listing(rebuild){const activeTab=tab;const params=new URLSearchParams({...filters,offset:String(offset)});const d=await api('/api/'+tab+'?'+params);if(tab!==activeTab)return;if(rebuild||!$('#listing')){$('#view').innerHTML=title(labels[tab],tab==='recipes'?'Pesquise e leia a receita completa, a origem e os pedidos associados.':tab==='outputs'?'Explore todas as respostas guardadas, com evidência, contexto e identificação do professor.':'Acompanhe o estado, erros, prompt enviado e respostas de cada pedido.')+filtersHtml()+'<div id="listing"></div><div id="pagination" class="pager"></div><div id="detail"></div>';$('#search').onsubmit=e=>{e.preventDefault();['q','persona','capability','status'].forEach(k=>{if($('#'+k))filters[k]=$('#'+k).value});offset=0;selected=null;$('#detail').replaceChildren();render(false)};}
let body='';if(tab==='jobs')body=jobsTable(d.items);else if(tab==='recipes')body='<div class="tablewrap"><table><thead><tr><th>Receita</th><th>Caracteres</th><th>Fonte</th><th></th></tr></thead><tbody>'+d.items.map(r=>'<tr><td>'+esc(r.title)+'</td><td>'+num(r.characters)+'</td><td>'+esc(r.source)+'</td><td><button data-recipe="'+esc(r.id)+'">Abrir</button></td></tr>').join('')+'</tbody></table></div>';else body='<div class="tablewrap"><table><thead><tr><th>Receita / pergunta</th><th>Mapa</th><th>Estado</th><th>Professor</th><th></th></tr></thead><tbody>'+d.items.map(r=>'<tr><td>'+esc(r.title)+'<div class="small muted">'+esc(r.question)+'</div></td><td>'+esc((personas[r.persona]||r.persona)+' · '+(caps[r.capability]||r.capability))+'<div class="small muted">'+esc(r.persona+' / '+r.capability+' / '+r.evidence_type)+'</div>'+'</td><td>'+badge(r.status)+'</td><td>'+esc(r.provider||'—')+'</td><td><button data-example="'+esc(r.id)+'">Ler</button></td></tr>').join('')+'</tbody></table></div>';
$('#listing').innerHTML=d.items.length?body:'<p class="empty">Nenhum resultado nesta seleção.</p>';$('#pagination').innerHTML='<span class="small muted">'+num(d.total)+' resultados · página '+(Math.floor(offset/d.limit)+1)+'</span><button id="prev" '+(offset===0?'disabled':'')+'>Anterior</button><button id="next" '+(offset+d.limit>=d.total?'disabled':'')+'>Seguinte</button>';$('#prev').onclick=()=>{offset=Math.max(0,offset-d.limit);selected=null;render(true)};$('#next').onclick=()=>{offset+=d.limit;selected=null;render(true)};bindJobButtons();$('#view').querySelectorAll('[data-recipe]').forEach(b=>b.onclick=()=>showDetail('recipe',b.dataset.recipe));$('#view').querySelectorAll('[data-example]').forEach(b=>b.onclick=()=>showDetail('example',b.dataset.example));}
const evidenceNames={E0:'Informação insuficiente ou contraditória',E1:'Informação explícita na receita',E2:'Conclusão derivada do contexto',E3:'Cálculo',E4:'Nota externa de apoio'};
const capHelp={C1:'Encontrar informação expressa na receita.',C2:'Selecionar o que interessa ao pedido.',C3:'Relacionar detalhes e chegar a uma conclusão sustentada.',C4:'Avaliar requisitos e restrições do utilizador.',C5:'Reorganizar ou simplificar sem alterar o significado.',C6:'Usar o histórico para responder à continuação.',C7:'Reconhecer lacunas ou contradições sem inventar.',C8:'Usar ferramentas quando necessário.'};
const personaHelp={P1:'Precisa de explicações simples e claras.',P2:'Quer realizar uma tarefa concreta.',P3:'Tem preferências, exclusões ou requisitos a respeitar.',P4:'Quer adaptar ou reorganizar a receita para outra situação.',P5:'Explora o assunto através de perguntas e continuações.'};
function messagesHtml(messages){return (messages||[]).map((m,i)=>'<div class="bubble '+(m.role==='user'?'user':'assistant')+'"><strong>'+(m.role==='user'?'Utilizador · pergunta':'Assistente · resposta')+' '+(Math.floor(i/2)+1)+'</strong><p class="text">'+esc(m.content)+'</p></div>').join('');}
function profileHtml(req,p){const profile=req?.persona||config.personas.find(x=>x.id===p)||{};return '<div class="profilebox"><strong>Perfil: '+esc(personas[p]||profile.name||p)+' · '+esc(p)+'</strong><p>'+esc(personaHelp[p]||profile.description||'')+'</p><details><summary>Definição usada neste pedido</summary><p>'+esc(profile.description||'Não disponível')+'</p></details></div>';}
function conversationHtml(e,req){const def=req?.capabilities?.find(c=>c.id===e.capability);return '<section class="conversation"><h3>'+esc(e.capability)+' · '+esc(caps[e.capability]||e.capability)+'</h3><p class="frameworkhint">'+esc(capHelp[e.capability]||def?.description||'')+'</p><p class="small">'+esc(evidenceNames[e.evidence_type]||e.evidence_type)+' · Dificuldade: '+esc(({easy:'fácil',medium:'média',hard:'difícil'})[e.difficulty]||e.difficulty)+'</p>'+(e.supported===false?'<p>Exemplo não gerado: '+esc(e.evidence_note)+'</p>':messagesHtml(e.messages))+'<details><summary>Evidências e justificação</summary>'+(e.evidence||[]).map(ev=>'<blockquote>'+esc(ev.quote)+'<div class="mono">'+esc(ev.source_id)+'</div></blockquote>').join('')+'<p>'+esc(e.evidence_note)+'</p></details>'+(def?'<details><summary>Definição original da capacidade</summary><p>'+esc(def.description)+'</p></details>':'')+'</section>';}
function recipeHtml(req){return '<aside><h2>Receita de referência</h2><div class="recipebody">'+esc(req?.recipe?.text||'Receita indisponível')+'</div>'+(req?.knowledge||[]).map(n=>'<details><summary>Nota de apoio · '+esc(n.source_id)+'</summary><div class="text">'+esc(n.text)+'</div></details>').join('')+'</aside>';}
async function showDetail(kind,id,refresh=false){const ticket=++detailTicket;try{const requestedTab=tab;const d=await api('/api/'+kind+'?id='+encodeURIComponent(id));if(tab!==requestedTab||ticket!==detailTicket)return;let host=$('#detail');if(!host){host=document.createElement('div');host.id='detail';$('#view').append(host);}selected={kind,id};let body='';
if(kind==='recipe'){body='<h2>'+esc(d.title)+'</h2><div class="recipebody">'+esc(d.text)+'</div><details><summary>Origem e metadados</summary><pre>'+esc(JSON.stringify(d.metadata,null,2))+'</pre></details><h2>Conversas por pedido e perfil</h2>'+jobsTable(d.jobs);}
else{const req=d.request||{};body='<h2>'+esc(d.title)+'</h2><p>'+badge(d.status)+' · '+esc(d.provider||'—')+' / '+esc(d.teacher||'—')+'</p>'+profileHtml(req,d.persona);
const examples=kind==='example'?[d.data]:(d.result?.examples||[]);
body+='<div class="reader">'+recipeHtml(req)+'<div><h2>'+(kind==='example'?'Conversa':'Conversas do pedido · '+examples.length)+'</h2>'+examples.map(e=>conversationHtml(e,req)).join('')+(!examples.length?'<p class="muted">Ainda sem conversas guardadas.</p>':'')+'</div></div>';
if(d.error)body+='<blockquote>'+esc(d.error)+'</blockquote>';
if(kind==='example')body+='<div class="card"><h3>Revisão humana</h3><select id="reviewDecision"><option value="accepted">Aceitar</option><option value="needs_review">Marcar para rever</option><option value="rejected">Rejeitar</option></select><label>Nota<input id="reviewNote" value="'+esc(d.review_note||'')+'"></label><button id="saveReview">Guardar revisão</button></div>';
if(d.review_note)body+='<p>Revisão: '+esc(d.review_note)+'</p>';
body+='<details><summary>Dados técnicos / JSON</summary><p class="mono">'+esc(d.id)+'</p><pre>'+esc(JSON.stringify(kind==='example'?d.data:d.result,null,2))+'</pre></details>';
if(kind==='job')body+='<details><summary>Prompt enviado</summary><pre>'+esc(d.prompt)+'</pre></details><details><summary>Eventos e diagnóstico · tentativa '+esc(d.attempts)+'</summary><pre>'+esc(d.log_tail||'Ainda sem eventos.')+'</pre></details>';
}
const opened=refresh?Array.from(host.querySelectorAll('details')).map(x=>x.open):[];
const recipeScroll=refresh?host.querySelector('.recipebody')?.scrollTop||0:0;
host.innerHTML='<article class="detail"><div class="detailtop"><span class="muted small">Leitura da receita e das conversas</span><button id="closeDetail">Fechar detalhe</button></div>'+body+'</article>';
if(refresh){host.querySelectorAll('details').forEach((x,i)=>{if(i<opened.length)x.open=opened[i]});if(host.querySelector('.recipebody'))host.querySelector('.recipebody').scrollTop=recipeScroll;}
if($('#saveReview'))$('#saveReview').onclick=()=>saveReview(id);
$('#closeDetail').onclick=()=>{detailTicket++;selected=null;host.replaceChildren()};bindJobButtons();if(!refresh)host.scrollIntoView({behavior:'smooth',block:'start'});}catch(e){if(ticket===detailTicket)setError(e)}}

// Os guias são os próprios Markdown do projeto: não existe uma segunda cópia.
async function renderGuides(){
 const d=await api('/api/guides');
 const docs=tab==='project'?d.filter(x=>x.path.startsWith('modelos')||x.path.startsWith('notebooks')):d;
 $('#view').innerHTML=title(labels[tab],'Abra apenas o guia da tarefa que pretende fazer.')+docs.map(x=>'<details class="card"><summary>'+esc(x.title)+'</summary><div class="text">'+esc(x.text)+'</div></details>').join('');
 if(tab==='project'){const models=await api('/api/models');$('#view').innerHTML+='<h2>Resultados locais</h2>'+(models.length?models.map(m=>'<details class="card"><summary>'+esc(m.path)+'</summary><pre>'+esc(JSON.stringify(m.data,null,2))+'</pre></details>').join(''):'<p>Ainda não há métricas em modelos/. Consulte o guia acima.</p>');}
}
async function saveReview(id){
 try{
 const r=await fetch('/api/review',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id,decision:$('#reviewDecision').value,note:$('#reviewNote').value})});
 const d=await r.json();if(!r.ok)throw Error(d.error);await showDetail('example',id,true);
 }catch(e){setError(e);}
}

async function render(rebuild){if(busy){if(rebuild)setTimeout(()=>render(true),100);return;}busy=true;try{if(!config)config=await api('/api/config');if(tab==='overview')await overview();else if(tab==='personas')renderPersonas();else if(tab==='framework')renderFramework();else if(tab==='guides'||tab==='project')await renderGuides();else await listing(rebuild);setError(null);$('#updated').textContent='Atualizado '+new Date().toLocaleTimeString('pt-PT');}catch(e){setError(e);$('#updated').textContent='Sem atualização';}finally{busy=false}}
// Evita perder a posição de leitura ao atualizar automaticamente ou carregar F5.
const readingStateKey = 'tinyslm-monitor-leitura-v3';
if ('scrollRestoration' in history) history.scrollRestoration = 'manual';

function takeReadingSnapshot() {
  return {
    tab, offset, filters: {...filters},
    selected: selected ? {...selected} : null,
    pageY: window.scrollY,
    recipeY: $('#detail .recipebody')?.scrollTop ?? 0,
    detailsOpen: Array.from(document.querySelectorAll('#detail details')).map(x => x.open),
    preY: Array.from(document.querySelectorAll('#detail pre')).map(x => x.scrollTop),
    live: $('#live').checked
  };
}

function saveReadingSnapshot() {
  try { sessionStorage.setItem(readingStateKey, JSON.stringify(takeReadingSnapshot())); }
  catch (_) { /* armazenamento indisponível: não bloquear o painel */ }
}
window.addEventListener('beforeunload', saveReadingSnapshot);

function readingInProgress() {
  // O detalhe é a área principal de leitura. Não voltar a criar o seu HTML.
  if (selected) return true;
  // O browser está abaixo do topo: atualizar iria reconstruir partes da página.
  if (window.scrollY > 25) return true;
  // Também protege eventuais áreas com barra de scroll própria.
  if (Array.from(document.querySelectorAll('.recipebody, pre, .tablewrap'))
      .some(el => el.scrollTop > 5)) return true;
  // Não alterar resultados enquanto a pessoa está a escrever ou a selecionar texto.
  if (document.activeElement?.closest('#search')) return true;
  if (window.getSelection()?.toString().trim()) return true;
  return false;
}

async function autoRefresh() {
  if (!$('#live').checked || busy || ['personas','framework','guides','project'].includes(tab)) return;
  if (readingInProgress()) {
    $('#updated').textContent = 'Atualização pausada durante a leitura';
    return;
  }
  // Só reconstruímos listas/indicadores quando estamos no início, sem leitura aberta.
  // A posição é preservada caso haja um pequeno deslocamento do layout.
  const pageY = window.scrollY;
  await render(false);
  if (Math.abs(window.scrollY - pageY) > 2) window.scrollTo(0, pageY);
}

async function initialize() {
  let previous = null;
  try { previous = JSON.parse(sessionStorage.getItem(readingStateKey) || 'null'); }
  catch (_) { /* estado guardado inválido */ }
  if (previous && Object.prototype.hasOwnProperty.call(labels, previous.tab)) {
    tab = previous.tab;
    offset = Number.isInteger(previous.offset) && previous.offset >= 0 ? previous.offset : 0;
    if (previous.filters && typeof previous.filters === 'object')
      filters = {...filters, ...previous.filters};
    if (typeof previous.live === 'boolean') $('#live').checked = previous.live;
  }
  renderNav();
  await render(true);
  if (previous?.selected && ['recipe','example','job'].includes(previous.selected.kind)
      && typeof previous.selected.id === 'string') {
    // refresh=true não invoca scrollIntoView e mantém a posição da página.
    await showDetail(previous.selected.kind, previous.selected.id, true);
    const host = $('#detail');
    (previous.detailsOpen || []).forEach((open, i) => {
      const el = host?.querySelectorAll('details')[i];
      if (el) el.open = Boolean(open);
    });
    const recipe = host?.querySelector('.recipebody');
    if (recipe) recipe.scrollTop = previous.recipeY || 0;
    (previous.preY || []).forEach((pos, i) => {
      const el = host?.querySelectorAll('pre')[i];
      if (el) el.scrollTop = pos;
    });
  }
  // Esperar que o layout seja calculado antes de restaurar a posição vertical.
  requestAnimationFrame(() => requestAnimationFrame(() => {
    if (previous && typeof previous.pageY === 'number')
      window.scrollTo(0, previous.pageY);
  }));
  setInterval(autoRefresh, 30000);
}
initialize();
</script></body></html>'''


def query(db, sql, params=()):
    return [dict(row) for row in db.execute(sql, params)]


def tail(path, count=12000):
    with path.open('rb') as f:
        f.seek(0, 2)
        f.seek(max(0, f.tell()-count))
        return f.read().decode('utf-8', errors='replace')


def endpoint(db, route, p, root, work):
    one=lambda k,default='':p.get(k,[default])[0]
    if route=='config':
        cfg=json.loads((root/'config.json').read_text(encoding='utf-8'))
        cfg['prompt']=(root/'prompt.txt').read_text(encoding='utf-8')
        return cfg
    if route=='overview':
        jobs=dict(db.execute('SELECT status,count(*) FROM jobs GROUP BY status'))
        examples=dict(db.execute('SELECT status,count(*) FROM examples GROUP BY status'))
        usage={}
        for row in db.execute('SELECT usage FROM jobs WHERE usage IS NOT NULL'):
            for k,v in json.loads(row[0]).items():
                if isinstance(v,(float,int)):usage[k]=usage.get(k,0)+v
        return {'recipes':db.execute('SELECT count(*) FROM recipes').fetchone()[0],'jobs':jobs,'examples':examples,
          'examples_total':sum(examples.values()),'usage':usage,
          'coverage':query(db,"SELECT persona,capability,count(*) n FROM examples WHERE status!='rejected' GROUP BY persona,capability"),
          'recent':query(db,"SELECT j.id,j.persona,j.status,j.provider,r.title FROM jobs j JOIN recipes r ON r.id=j.recipe_id WHERE j.status='done' ORDER BY j.updated DESC LIMIT 6")}
    if route in ('recipes','outputs','jobs'):
        offset=max(0,min(int(one('offset','0')),10000000));limit=30
        where=[];args=[]
        if one('q'):
            where.append('(r.title LIKE ? OR r.text LIKE ?)');args += ['%'+one('q')+'%']*2
        alias='e' if route=='outputs' else 'j'
        if route!='recipes':
            for field in ('persona','status'):
                if one(field):where.append(f'{alias}.{field}=?');args.append(one(field))
        if route=='outputs' and one('capability'):
            where.append('e.capability=?');args.append(one('capability'))
        tables={'recipes':'recipes r','outputs':'examples e JOIN recipes r ON r.id=e.recipe_id JOIN jobs j ON j.id=e.job_id',
                'jobs':'jobs j JOIN recipes r ON r.id=j.recipe_id'}
        cols={'recipes':'r.id,r.title,length(r.text) characters,r.metadata','outputs':'e.id,e.persona,e.capability,e.evidence_type,e.status,e.data,j.provider,r.title',
              'jobs':'j.id,j.persona,j.status,j.provider,j.updated,r.title'}
        order={'recipes':'r.title,r.id','outputs':'e.rowid DESC','jobs':"CASE j.status WHEN 'running' THEN 0 WHEN 'error' THEN 1 WHEN 'done' THEN 2 WHEN 'manual' THEN 3 ELSE 4 END,j.updated DESC,j.id"}
        clause=' WHERE '+' AND '.join(where) if where else ''
        total=db.execute('SELECT count(*) FROM '+tables[route]+clause,args).fetchone()[0]
        rows=query(db,'SELECT '+cols[route]+' FROM '+tables[route]+clause+' ORDER BY '+order[route]+' LIMIT ? OFFSET ?',[*args,limit,offset])
        for row in rows:
            if route=='recipes':row['source']=json.loads(row.pop('metadata')).get('source','')
            if route=='outputs':row['question']=json.loads(row.pop('data'))['messages'][0]['content'][:180]
        return {'items':rows,'total':total,'limit':limit,'offset':offset}
    if route=='recipe':
        rows=query(db,'SELECT * FROM recipes WHERE id=?',(one('id'),))
        if not rows:raise LookupError('Receita não encontrada.')
        r=rows[0];r['metadata']=json.loads(r['metadata'])
        r['jobs']=query(db,'SELECT id,persona,status,provider,? title FROM jobs WHERE recipe_id=? ORDER BY created,id',(r['title'],r['id']))
        return r
    if route=='example':
        rows=query(db,'''SELECT e.*,j.provider,j.teacher,j.request,r.title FROM examples e
          JOIN jobs j ON j.id=e.job_id JOIN recipes r ON r.id=e.recipe_id WHERE e.id=?''',(one('id'),))
        if not rows:raise LookupError('Exemplo não encontrado.')
        r=rows[0];r['data']=json.loads(r['data']);req=json.loads(r.pop('request'))
        r['request']=req
        r['context']='\n\n'.join(s['text'] for s in [req['recipe'],*req.get('knowledge',[])])
        return r
    if route=='job':
        rows=query(db,'SELECT j.*,r.title FROM jobs j JOIN recipes r ON r.id=j.recipe_id WHERE j.id=?',(one('id'),))
        if not rows:raise LookupError('Pedido não encontrado.')
        r=rows[0];r['request']=json.loads(r['request']);r['result']=json.loads(r['result']) if r['result'] else None
        logs=[]
        if re.fullmatch(r'[0-9a-f]{24}',r['id']):
            for suffix in ('.stderr.txt','.events.jsonl'):
                path=work/'raw'/(r['id']+'-'+str(r['attempts'])+suffix)
                if path.is_file():logs.append(path.name+'\n'+tail(path))
        r['log_tail']='\n\n'.join(logs)
        return r
    raise LookupError('Rota não encontrada.')


def handler_for(root, work):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def send(self,code,body,kind):
            self.send_response(code)
            self.send_header('Content-Type',kind)
            self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            try:self.wfile.write(body)
            except (BrokenPipeError,ConnectionResetError):pass
        def do_POST(self):
            # Só aceita revisão a partir desta origem local. Não permite gravação por sites externos.
            origin = self.headers.get('Origin')
            expected = 'http://' + self.headers.get('Host', '')
            if (origin and origin != expected) or self.headers.get('Content-Type') != 'application/json':
                return self.send(403,b'{"error":"Origem ou formato recusado"}','application/json')
            try:
                if self.path != '/api/review': raise ValueError('Rota inválida')
                size=int(self.headers.get('Content-Length','0'))
                if not 0 < size <= 16000: raise ValueError('Pedido demasiado grande ou vazio')
                data=json.loads(self.rfile.read(size))
                if data.get('decision') not in ('accepted','rejected','needs_review'): raise ValueError('Decisão inválida')
                if not isinstance(data.get('note',''),str): raise ValueError('Nota inválida')
                # Mesmo bloqueio do gerador: evita alterar a fila durante uma escrita longa.
                with (work/'queue.lock').open('a') as lock:
                    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    with contextlib.closing(sqlite3.connect(work/'queue.sqlite')) as db:
                        with db:
                            changed=db.execute('UPDATE examples SET status=?,review_note=? WHERE id=?',
                                (data['decision'],data.get('note',''),data.get('id'))).rowcount
                            if not changed: raise ValueError('Conversa não encontrada')
                return self.send(200,b'{"ok":true}','application/json')
            except BlockingIOError:
                return self.send(409,b'{"error":"Geracao em curso. Guarde a revisao quando o lote terminar."}','application/json')
            except (ValueError,sqlite3.Error) as exc:
                return self.send(400,json.dumps({'error':str(exc)}).encode(),'application/json')

        def do_GET(self):
            route=urlparse(self.path)
            if route.path=='/':return self.send(200,HTML.encode(),'text/html; charset=utf-8')
            if route.path=='/favicon.ico':return self.send(204,b'','image/x-icon')
            try:
                if route.path=='/api/models':
                    data=[]
                    for p in sorted((root/'modelos').rglob('*.json')):
                        if p.name not in ('metrics.json','run_config.json','dataset_report.json'): continue
                        if p.stat().st_size > 2000000: continue
                        try: value=json.loads(p.read_text())
                        except (ValueError,OSError): continue
                        data.append({'path':str(p.relative_to(root)),'data':value})
                    return self.send(200,json.dumps(data,ensure_ascii=False).encode(),'application/json; charset=utf-8')
                if route.path=='/api/guides':
                    data=[{'path':p,'title':(root/p).read_text().splitlines()[0].lstrip('# '),'text':(root/p).read_text()} for p in GUIDES]
                    return self.send(200,json.dumps(data,ensure_ascii=False).encode(),'application/json; charset=utf-8')
                if route.path=='/api/config':
                    data=json.loads((root/'config.json').read_text());data['prompt']=(root/'prompt.txt').read_text()
                    return self.send(200,json.dumps(data).encode(),'application/json')
                if not route.path.startswith('/api/'):raise LookupError('Rota não encontrada.')
                if not (work/'queue.sqlite').is_file():raise LookupError('Não existe work/queue.sqlite nesta pasta. Execute a partir da pasta do programa ou indique --work.')
                with contextlib.closing(sqlite3.connect((work/'queue.sqlite').as_uri()+'?mode=ro',uri=True,timeout=3)) as db:
                    db.row_factory=sqlite3.Row;db.execute('PRAGMA query_only=ON')
                    data=endpoint(db,route.path[5:],parse_qs(route.query),root,work)
                return self.send(200,json.dumps(data,ensure_ascii=False).encode(),'application/json; charset=utf-8')
            except LookupError as exc:code=404;message=str(exc)
            except (ValueError,sqlite3.Error) as exc:code=400;message=str(exc)
            except Exception as exc:code=500;message=str(exc)
            self.send(code,json.dumps({'error':message},ensure_ascii=False).encode(),'application/json; charset=utf-8')
    return Handler


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work',default=str(ROOT/'dados'))
    parser.add_argument('--port',type=int,default=8765)
    args=parser.parse_args()
    work=Path(args.work).resolve()
    # Permite ler os guias antes de importar dados; as listas indicam que falta a fila.
    server=ThreadingHTTPServer(('127.0.0.1',args.port),handler_for(ROOT,work))
    print(f'Painel: http://127.0.0.1:{args.port}',flush=True)
    print(f'Fila: {work / "queue.sqlite"}',flush=True)
    print('Consulta e revisão humana. Deixe este terminal aberto. Ctrl+C para fechar.',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()


if __name__=='__main__':main()

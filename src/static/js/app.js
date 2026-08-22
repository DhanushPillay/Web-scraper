/** Sniffer — drawer + interactions (compact row layout) */
const $ = (s,c=document)=>c.querySelector(s);
const $$ = (s,c=document)=>[...c.querySelectorAll(s)];

const icons={
  saved:'<svg viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="1.8"><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/></svg>',
  bookmark:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/></svg>',
  read:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M5 12l5 5L20 7"/></svg>',
  unread:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="9"/><path d="M8 12l2 2 4-4"/></svg>'
};

function toast(msg,type='success'){
  const c=$('#toastContainer'); if(!c) return;
  const el=document.createElement('div');
  el.className=`toast${type==='error'?' toast-error':''}`;
  el.textContent=msg; c.append(el);
  setTimeout(()=>el.remove(),3200);
}
async function request(url,opts={}){
  const r=await fetch(url,{headers:{'Content-Type':'application/json',...opts.headers},...opts});
  const d=await r.json().catch(()=>({})); if(!r.ok) throw new Error(d.message||d.error||'Something went wrong'); return d;
}
function setActionState(btn,active,type){
  btn.classList.toggle('is-active',active);
  btn.setAttribute('aria-pressed',String(active));
  const isBook=type==='bookmark';
  btn.title=isBook?(active?'Remove from saved':'Save'):(active?'Mark unread':'Mark read');
  const svg=btn.querySelector('svg'); if(svg) svg.remove();
  btn.insertAdjacentHTML('afterbegin', isBook?(active?icons.saved:icons.bookmark):(active?icons.read:icons.unread));
}
async function toggleArticleState(btn,action){
  const card=btn.closest('[data-article-id]'); if(!card||btn.disabled) return;
  btn.disabled=true;
  try{
    const ep=action==='bookmark'?'/bookmark':'/toggle_read';
    const d=await request(ep,{method:'POST',body:JSON.stringify({article_id:Number(card.dataset.articleId)})});
    const active=d.status===(action==='bookmark'?'saved':'read');
    setActionState(btn,active,action);
    if(action==='read') card.classList.toggle('is-read',active);
    toast(active?(action==='bookmark'?'Saved':'Marked read'):(action==='bookmark'?'Removed':'Marked unread'));
  }catch(e){ toast(e.message||'Could not update','error'); } finally{ btn.disabled=false; }
}

// Drawer
function openDrawer(){
  const d=$('#summaryDrawer'), o=$('#drawerOverlay');
  d?.classList.add('show'); o?.classList.add('show');
  d?.setAttribute('aria-hidden','false'); o?.setAttribute('aria-hidden','false');
  document.body.style.overflow='hidden';
  setTimeout(()=> $('[data-drawer-close]',d)?.focus(), 10);
}
function closeDrawer(){
  const d=$('#summaryDrawer'), o=$('#drawerOverlay');
  d?.classList.remove('show'); o?.classList.remove('show');
  d?.setAttribute('aria-hidden','true'); o?.setAttribute('aria-hidden','true');
  document.body.style.overflow='';
}
// legacy compat
function openSummary(){ openDrawer(); }
function closeSummary(){ closeDrawer(); }

async function summarizeArticle(url, titleHint){
  const body=$('#drawerBody'), title=$('#drawerTitle'), meta=$('#drawerMeta'), link=$('#drawerLink');
  if(!body||!title) return;
  title.textContent=titleHint||'Quick read'; meta.textContent='Fetching…';
  body.innerHTML='<div class="sn-summary-loading"><span></span><p>Extracting summary…</p></div>';
  if(link){ link.hidden=true; link.href=url; }
  openDrawer();
  try{
    const d=await request('/api/summarize',{method:'POST',body:JSON.stringify({url})});
    title.textContent=d.title||titleHint||'Quick read';
    meta.textContent=`${d.read_time||3} min · ${d.word_count||''} words`.replace('  ',' ');
    const frag=document.createDocumentFragment();
    if(d.dek){
      const dekEl=document.createElement('p'); dekEl.className='sn-drawer-dek'; dekEl.textContent=d.dek; frag.append(dekEl);
    }
    if(d.bullets && d.bullets.length){
      const ul=document.createElement('ul'); ul.className='sn-drawer-bullets';
      d.bullets.forEach(b=>{ const li=document.createElement('li'); li.textContent=b; ul.append(li); });
      frag.append(ul);
    } else if(d.summary){
      const p=document.createElement('p'); p.textContent=d.summary; frag.append(p);
    }
    body.replaceChildren(frag);
    if(link){ link.href=url; link.hidden=false; }
  }catch(e){
    body.textContent=e.message||'Unable to summarize — try opening the article directly.';
  }
}

function initScrollTop(){
  const b=$('#scrollTop'); if(!b) return;
  const upd=()=>b.classList.toggle('visible', window.scrollY>350);
  window.addEventListener('scroll',upd,{passive:true}); b.addEventListener('click',()=>window.scrollTo({top:0,behavior:'smooth'})); upd();
}
function initKeys(){
  document.addEventListener('keydown',e=>{
    const typing=['INPUT','TEXTAREA','SELECT'].includes(e.target.tagName);
    if(e.key==='/'&&!typing){ e.preventDefault(); $('#searchInput')?.focus(); }
    if(e.key==='Escape') closeDrawer();
  });
}

document.addEventListener('DOMContentLoaded',()=>{
  $('#scrapeForm')?.addEventListener('submit',()=>{
    const o=$('#loadingOverlay'), p=$('#loadingProgress'); o?.classList.add('show');
    if(!p) return;
    const steps=[[2000,'Scanning sources…'],[6000,'Processing stories…'],[12000,'Almost done…']];
    const s=Date.now();
    const id=setInterval(()=>{
      const e=Date.now()-s;
      for(const[ms,t] of steps) if(e>=ms) p.textContent=t;
      if(e>=16000) clearInterval(id);
    },800);
  });
  document.addEventListener('click',e=>{
    const a=e.target.closest('[data-action]');
    if(a){
      const t=a.dataset.action;
      if(t==='bookmark'||t==='read') toggleArticleState(a,t);
      if(t==='summary') summarizeArticle(a.dataset.url, a.dataset.title||a.closest('[data-article-id]')?.querySelector('.sn-row-title, .sn-featured-title')?.textContent?.trim());
      return;
    }
    if(e.target.closest('[data-drawer-close]')) closeDrawer();
    if(e.target===$('#drawerOverlay')) closeDrawer();
    // legacy
    if(e.target.closest('[data-modal-close]')) closeDrawer();
    if(e.target===$('#summaryModal')) closeDrawer();
  });
  initScrollTop(); initKeys();
});

import json, re
from pathlib import Path
SC=str(Path(__file__).resolve().parent)   # inputs and outputs live next to this script
REPO=str(Path(__file__).resolve().parents[2])
players=open(f"{SC}/players.json").read()
league=json.load(open(f"{SC}/league_rows.json"))
# pull the shared <style> from the first build so both pages match
first=open(f"{SC}/bt-2026-retrospective.html").read()
style=first[first.index("<style>"):first.index("</style>")+8]
style=style.replace("</style>","""
.plot svg .pt.s0{fill:var(--s1)}
.plot svg .db{stroke:var(--rule);stroke-width:3}
.plot svg .lbl.team{font-size:12.5px;font-weight:600}
.two{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:24px;align-items:start}
</style>""")
league_sorted=sorted(league,key=lambda r:r["rank"])
def num(n): return f"{n:,}"
def sgn(n): return f"{n:+,}"
proj_rank={r["team"]:i+1 for i,r in enumerate(sorted(league,key=lambda r:-r["proj"]))}
draft_rank={r["team"]:i+1 for i,r in enumerate(sorted(league,key=lambda r:-r["noswap"]))}
for r in league: r["proj_rank"]=proj_rank[r["team"]]; r["draft_rank"]=draft_rank[r["team"]]
def tbl(head,rows,aligns):
    h="<div class='tw'><table><thead><tr>"+"".join(f"<th class='{a}'>{c}</th>" for c,a in zip(head,aligns))+"</tr></thead><tbody>"
    for r in rows: h+="<tr>"+"".join(f"<td class='{a}'>{c}</td>" for c,a in zip(r,aligns))+"</tr>"
    return h+"</tbody></table></div>"
t1=tbl(["#","Team","Official","Projected","Proj. rank","vs projection"],
       [[r["rank"],r["team"],num(r["official"]),num(r["proj"]),proj_rank[r["team"]],sgn(r["official"]-r["proj"])] for r in league_sorted],
       ["right","left","right","right","right","right"])
t2=tbl(["Team","Drafted 16, no moves","Draft rank","Official","Final rank","Value of in-season moves"],
       [[r["team"],num(r["noswap"]),draft_rank[r["team"]],num(r["official"]),r["rank"],sgn(r["moves"])] for r in sorted(league,key=lambda r:-r["moves"])],
       ["left","right","right","right","right","right"])
t3=tbl(["Team","Hitters proj.","Hitters official","SP proj.","SP official","RP proj.","RP official"],
       [[r["team"],num(r["proj_hit"]),num(r["off_hit"]),r["proj_sp"],r["off_sp"],r["proj_rp"],r["off_rp"]] for r in league_sorted],
       ["left","right","right","right","right","right","right"])
pos=[("C",-50),("1B",-27),("2B",1),("3B",-35),("SS",-49),("OF (1st drafted)",-84),("OF (2nd)",-65),("OF (3rd)",11),("DH",-79),("RP",-13),("SP1",-2),("SP2",-23),("SP3",14),("SP4",17),("SP5",-4),("SP6",-22)]
t4=tbl(["Draft slot","Avg. actual minus projected (9 teams)"],[[a,sgn(b)] for a,b in pos],["left","right"])
t5=tbl(["Team","Best pick vs projection","Worst pick vs projection","Picks at or above projection"],
       [[r["team"],r["best"],r["worst"],r["beat"]] for r in league_sorted],["left","left","left","right"])

body=f'''
<header class="mast">
  <div class="eyebrow">BT Baseball Pool 2026 · Season review · Final, 162 games · MLERA 4.17</div>
  <h1>BT 2026 Season Analysis</h1>
  <p class="sub">How every team's preseason projection compared with its official final score, how much each roster gained or lost from in-season moves, and which picks made the difference. Hover any dot in the charts for the numbers behind it.</p>
  <p class="sub" style="margin-top:12px">The preseason projections throughout are from a proprietary dataset and formula built for the Levinsons team, applied here to every roster as of draft day. They are one team's view of the league, not an official league projection.</p>
</header>
<div class="tiles">
  <div class="tile"><div class="v">4,788<small>Cobey</small></div><div class="k">Champion. 112 clear of the field.</div></div>
  <div class="tile"><div class="v">4 of 9</div><div class="k">Teams that finished at or above their preseason projection.</div></div>
  <div class="tile"><div class="v">-515</div><div class="k">League total versus projection (41,158 vs 41,673). Injuries, mostly.</div></div>
  <div class="tile"><div class="v">+2,302</div><div class="k">Points the league added through in-season moves, over drafted rosters alone.</div></div>
</div>
<nav class="toc" aria-label="Sections"><a href="#s1">Standings vs projection</a><a href="#s2">Draft vs moves</a><a href="#s3">Where projections missed</a><a href="#s4">Best &amp; worst picks</a><a href="#s5">Every player</a></nav>
<main>
<section id="s1"><h2><span class="num">1</span>Final standings versus preseason projection</h2>
<p>Each team's draft-day roster was scored on preseason projections under the BT formula. The table compares that number with the official final. Four teams beat their projection; the champion was projected second.</p>
{t1}
<div class="chart" id="chart-teams"></div>
<ul>
<li><strong>The projected order held in the middle.</strong> Cobey, Lerner, Mudge and Washington each finished within one place of where their draft-day rosters projected.</li>
<li><strong>The top was wrong.</strong> Winters projected first and finished fourth: no single collapse, but Seager, Ohtani, Kurtz and Rodríguez each fell 70 to 112 short. Palma projected fifth and finished ninth, 427 short, the largest miss in the league. Washington, holder of the first overall pick, got 299 points from Judge.</li>
<li><strong>Two teams climbed from the bottom three.</strong> Tchir (projected 9th, finished 7th) and Williams (8th to 6th) both beat their projections by more than 70. Levinsons went from a projected 6th to 2nd on a total only 39 above projection, because the teams above it fell.</li>
</ul>
</section>
<section id="s2"><h2><span class="num">2</span>Draft versus in-season moves</h2>
<p>"Drafted 16, no moves" scores every team's original draft on the players' actual full 2026 seasons, as if no substitution had ever been made. The gap to the official score is what the team's in-season moves were worth, whether forced by injury or chosen freely.</p>
{t2}
<div class="chart" id="chart-moves"></div>
<ul>
<li><strong>Tchir drafted the best roster in the league</strong> at 4,728 on full-season actuals, and is the only team whose moves cost points. Held as drafted, that roster finishes first by 156.</li>
<li><strong>Levinsons and Williams gained the most from moves</strong>, 552 and 470 points. Both drafted rosters that would have finished in the bottom three.</li>
<li><strong>Cobey won by doing both.</strong> Third-best draft, with Misiorowski (pick 70, the second half of a starting-pitcher pair) and King (pick 88), plus the fourth-largest gain from moves, made at the slots where the draft missed: Jordan Walker for Roman Anthony in the outfield, Miguel Vargas for Maikel García at third, and Jonathan Aranda for Pasquantino at DH.</li>
<li><strong>Across the league, moves were worth 2,302 points</strong>, about 256 per team. That is roughly the gap between second and seventh place.</li>
</ul>
</section>
<section id="s3"><h2><span class="num">3</span>Where projections missed</h2>
<p>By category, hitting fell short of projection for eight of nine teams, while starting pitching beat projection for all nine. The SP scoring rule (best three of six, times 3.5) only counts the arms that hit, so a staff with three good starters and three busts loses nothing to the busts.</p>
{t3}
<p>By draft slot, the first two outfielders, designated hitters, catchers and shortstops carried the biggest average shortfall. The second starting-pitcher pair (SP3 and SP4 below) was the only slot to beat projection on average, driven by Schlittler, Misiorowski and Cease. Starters are drafted in pairs, so SP1/SP2, SP3/SP4 and SP5/SP6 each share a pick; the DH is a separate final round.</p>
{t4}
</section>
<section id="s4"><h2><span class="num">4</span>Best and worst picks, by team</h2>
{t5}
<div class="two"><div>
<p><strong>Biggest shortfalls, league-wide.</strong> Rooker (Palma) -320, Judge (Washington) -290, Stanton (Levinsons) -275, Anthony (Cobey) -221, Robert (Williams) -211, Raleigh (Levinsons) -167, Crochet (Mudge) -161. All seven lost most of the season to injury or lost their role.</p>
</div><div>
<p><strong>Biggest gains.</strong> Schlittler (Mudge) +186, Misiorowski (Cobey) +148, Crow-Armstrong (Levinsons) +116, Alvarez (Lerner) +101, Cade Smith (Tchir) +91, Rasmussen (Palma) +89, Arozarena (Cobey) +80. The two best starting-pitcher seasons in the league, Schlittler and Misiorowski, were the second halves of pitcher pairs taken at picks 79 and 70, on projections under 70.</p>
</div></div>
<p><strong>Top scorers.</strong> Hitters: Crow-Armstrong 592, Alvarez 570, Tatis 531, Alonso 528, Arozarena 525, Caminero 522, De La Cruz 521. Starters (individual RSAR × 3.5): Schlittler 231, Misiorowski 217, Sale and Yamamoto 179, Cease 172. Relievers: Cade Smith 235, Mason Miller 215, Bednar 210.</p>
</section>
<section id="s5"><h2><span class="num">5</span>Every drafted player</h2>
<p>All 144 drafted players, projection against full-season actual. Dots below the dashed line scored less than projected. Hover or tab to a dot for the player's team, pick (starters drafted in pairs share a pick; the DH is a 13th round), and the stat line behind the score; "Show as table" lists everyone from largest shortfall to largest gain.</p>
<div class="chart" id="chart-hit"></div>
<div class="chart" id="chart-pit"></div>
</section>
<p class="foot">Sources: preseason projections as of draft day (March 30, 2026), the league draft tracker, MLB Stats API 2026 regular-season totals, and the commissioner's final RESULTS workbook. Scoring: hitters BA × 1000 (300 AB floor) + HR + RBI + R + SB; starters RSAR = (1.2 × MLERA − ERA) × IP/9, shown here per pitcher × 3.5 before the best-three rule, zero under 3.5 IP per appearance; relievers 5 × (W + SV). Team totals in sections 1 to 3 use the commissioner's official per-slot scores.</p>
</main>
'''

js=r'''
<script id="players" type="application/json">__DATA__</script>
<script id="league" type="application/json">__LEAGUE__</script>
<script>
(function(){
const P=JSON.parse(document.getElementById('players').textContent);
const L=JSON.parse(document.getElementById('league').textContent);
const MLERA=4.17;
const fmt=(n,d=0)=>Number(n).toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d});
const sg=(n,d=0)=>(n>=0?'+':'')+fmt(n,d);
const avgS=(h,ab)=>{const a=ab?h/ab:0;return a.toFixed(3).replace(/^0/,'')};
const NS='http://www.w3.org/2000/svg';
const el=(n,a,txt)=>{const e=document.createElementNS(NS,n);for(const k in a)e.setAttribute(k,a[k]);if(txt!=null)e.textContent=txt;return e;};
function row(parent,k,v,strong){const r=document.createElement('div');r.className='row';const a=document.createElement('span');a.className='k';a.textContent=k;const b=document.createElement(strong?'b':'span');b.textContent=String(v);r.appendChild(a);r.appendChild(b);parent.appendChild(r);}
function sep(parent){const s=document.createElement('div');s.className='sep';parent.appendChild(s);}
function breakdown(p){
  if(p.t==='hitter'){const floor=p.AB<300,den=Math.max(p.AB,300),ba=Math.round((den?p.H/den:0)*1000);
    return {rows:[['AB / H',`${p.AB} / ${p.H}`],['AVG',avgS(p.H,p.AB)+(floor?' (floor: '+avgS(p.H,300)+')':'')],['HR',p.HR],['RBI',p.RBI],['R',p.R],['SB',p.SB],['Games',p.G]],calc:`${ba} (BA×1000${floor?', 300 AB floor':''}) + ${p.HR} HR + ${p.RBI} RBI + ${p.R} R + ${p.SB} SB = ${p.ac}`};}
  if(p.t==='sp'){const short=p.G>0&&p.IP/p.G<3.5;const rsar=p.ERA==null||p.IP===0?0:Math.round((1.2*MLERA-p.ERA)*p.IP/9);
    return {rows:[['IP',fmt(p.IP,1)],['ERA',p.ERA==null?'—':p.ERA.toFixed(2)],['G / GS',`${p.G} / ${p.GS}`],['W',p.W],['K',p.K]],calc:short?'Under 3.5 IP per appearance: RSAR set to 0':`RSAR = (1.2×4.17 − ${p.ERA.toFixed(2)}) × ${fmt(p.IP,1)}/9 = ${rsar}\n${rsar} × 3.5 = ${p.ac}`};}
  return {rows:[['W',p.W],['SV',p.SV],['G',p.G],['ERA',p.ERA==null?'—':p.ERA.toFixed(2)],['IP',fmt(p.IP,1)]],calc:`5 × (${p.W} W + ${p.SV} SV) = ${p.ac}`};
}
const pickLabel=p=>p.pk>108?`DH round (13th), order ${p.pk-108}`:`pick ${p.pk} (round ${Math.ceil(p.pk/9)}${p.pair?', second of SP pair':''})`;
function playerTip(p){return {name:p.n,meta:`${p.o} · ${p.pos.replace(/\d/,'')} · ${pickLabel(p)}`,top:[['Projected',fmt(p.pr)],['Actual',fmt(p.ac)],['Difference',sg(p.ac-p.pr)]],...breakdown(p)};}

function makeTip(plot){const tip=document.createElement('div');tip.className='tip';tip.hidden=true;plot.appendChild(tip);return tip;}
function fillTip(tip,t){tip.replaceChildren();const n=document.createElement('div');n.className='n';n.textContent=t.name;tip.appendChild(n);const m=document.createElement('div');m.className='m';m.textContent=t.meta;tip.appendChild(m);t.top.forEach(([k,v])=>row(tip,k,v,true));if(t.rows&&t.rows.length){sep(tip);t.rows.forEach(([k,v])=>row(tip,k,v,false));}if(t.calc){sep(tip);const c=document.createElement('div');c.className='calc';c.textContent=t.calc;tip.appendChild(c);}}
function placeTip(tip,plot,px,py){tip.hidden=false;const pr=plot.getBoundingClientRect(),tw=tip.offsetWidth,th=tip.offsetHeight;let lx=px+14,ly=py-10;if(lx+tw>pr.width-4)lx=px-tw-14;if(lx<0)lx=4;if(ly+th>pr.height-4)ly=pr.height-th-4;if(ly<0)ly=4;tip.style.left=lx+'px';tip.style.top=ly+'px';}

function scatter(host,cfg){
  const W=900,H=cfg.h||600,m={l:64,r:24,t:18,b:56},iw=W-m.l-m.r,ih=H-m.t-m.b;
  const sx=v=>m.l+(v-cfg.x[0])/(cfg.x[1]-cfg.x[0])*iw,sy=v=>m.t+ih-(v-cfg.y[0])/(cfg.y[1]-cfg.y[0])*ih;
  const data=cfg.data;host.innerHTML='';
  const hd=document.createElement('div');hd.className='hd';const h3=document.createElement('h3');h3.textContent=cfg.title;hd.appendChild(h3);host.appendChild(hd);
  const note=document.createElement('p');note.className='note';note.textContent=cfg.note;host.appendChild(note);
  if(cfg.legend){const lg=document.createElement('div');lg.className='legend';cfg.legend.forEach(([cls,shape,txt])=>{const s=document.createElement('span');const i=document.createElement('i');i.className=shape==='d'?'d':'';i.style.background=`var(--${cls})`;s.appendChild(i);s.appendChild(document.createTextNode(txt));lg.appendChild(s);});host.appendChild(lg);}
  const plot=document.createElement('div');plot.className='plot';host.appendChild(plot);
  const svg=el('svg',{viewBox:`0 0 ${W} ${H}`,role:'img','aria-label':cfg.title});
  cfg.xt.forEach(v=>{svg.appendChild(el('line',{class:'grid',x1:sx(v),x2:sx(v),y1:m.t,y2:m.t+ih}));svg.appendChild(el('text',{x:sx(v),y:m.t+ih+18,'text-anchor':'middle'},fmt(v)));});
  cfg.yt.forEach(v=>{svg.appendChild(el('line',{class:'grid',x1:m.l,x2:m.l+iw,y1:sy(v),y2:sy(v)}));svg.appendChild(el('text',{x:m.l-10,y:sy(v)+4,'text-anchor':'end'},fmt(v)));});
  svg.appendChild(el('line',{class:'ax',x1:m.l,x2:m.l+iw,y1:m.t+ih,y2:m.t+ih}));svg.appendChild(el('line',{class:'ax',x1:m.l,x2:m.l,y1:m.t,y2:m.t+ih}));
  const d0=Math.max(cfg.x[0],cfg.y[0]),d1=Math.min(cfg.x[1],cfg.y[1]);
  svg.appendChild(el('line',{class:'diag',x1:sx(d0),y1:sy(d0),x2:sx(d1),y2:sy(d1)}));
  svg.appendChild(el('text',{x:sx(d1)-6,y:sy(d1)+16,'text-anchor':'end'},'actual = projected'));
  svg.appendChild(el('text',{x:m.l+iw/2,y:H-10,'text-anchor':'middle'},cfg.xLabel));
  svg.appendChild(el('text',{x:16,y:m.t+ih/2,'text-anchor':'middle',transform:`rotate(-90 16 ${m.t+ih/2})`},cfg.yLabel));
  const nodes=new Map();
  data.forEach(p=>{const x=sx(p.pr),y=sy(p.ac);let n;const r=cfg.r||5.5;
    if(p.t==='rp'){const q=r+1.5;n=el('path',{d:`M${x} ${y-q}L${x+q} ${y}L${x} ${y+q}L${x-q} ${y}Z`});}else n=el('circle',{cx:x,cy:y,r});
    n.setAttribute('class','pt s0');n.setAttribute('tabindex','0');n.setAttribute('role','img');n.setAttribute('aria-label',`${p.n}: projected ${fmt(p.pr)}, actual ${fmt(p.ac)}`);svg.appendChild(n);nodes.set(p,n);});
  (cfg.labels||[]).forEach(([name,dx,dy,anchor,cls])=>{const p=data.find(q=>q.n===name);if(!p)return;svg.appendChild(el('text',{class:'lbl '+(cls||''),x:sx(p.pr)+dx,y:sy(p.ac)+dy+4,'text-anchor':anchor},p.n));});
  plot.appendChild(svg);
  const tip=makeTip(plot);let cur=null;
  function show(p,px,py){if(cur&&cur!==p)nodes.get(cur).classList.remove('on');cur=p;nodes.get(p).classList.add('on');fillTip(tip,cfg.tip(p));placeTip(tip,plot,px,py);}
  function hide(){if(cur)nodes.get(cur).classList.remove('on');cur=null;tip.hidden=true;}
  svg.addEventListener('pointermove',e=>{const pt=svg.createSVGPoint();pt.x=e.clientX;pt.y=e.clientY;const q=pt.matrixTransform(svg.getScreenCTM().inverse());let best=null,bd=1e9;data.forEach(p=>{const dx=sx(p.pr)-q.x,dy=sy(p.ac)-q.y,d=dx*dx+dy*dy;if(d<bd){bd=d;best=p;}});if(best&&bd<28*28){const pr=plot.getBoundingClientRect();show(best,e.clientX-pr.left,e.clientY-pr.top);}else hide();});
  svg.addEventListener('pointerleave',hide);
  nodes.forEach((n,p)=>{n.addEventListener('focus',()=>{const pr=plot.getBoundingClientRect(),b=n.getBoundingClientRect();show(p,b.left-pr.left+b.width/2,b.top-pr.top+b.height/2);});n.addEventListener('blur',hide);});
  if(cfg.cols){const det=document.createElement('details');det.className='tv';const sm=document.createElement('summary');sm.textContent='Show as table (click a column heading to sort)';det.appendChild(sm);const tw=document.createElement('div');tw.className='tw';const tb=document.createElement('table');const thead=document.createElement('thead');const trh=document.createElement('tr');const tbody=document.createElement('tbody');
    const textCol=k=>k==='Player'||k==='Team'||k==='Role';
    const raw=s=>{if(s==null)return NaN;const t=String(s).replace(/,/g,'').replace(/^\+/,'');if(t==='—'||t==='')return NaN;const n=Number(t);return isNaN(n)?NaN:n;};
    let sortKey='Diff',sortDir=1;
    function render(){const col=cfg.cols.find(c=>c[0]===sortKey)||cfg.cols[0];const f=col[1];const isText=textCol(col[0]);
      const rows=[...data].sort((a,b)=>{if(isText){return String(f(a)).localeCompare(String(f(b)))*sortDir;}const x=raw(f(a)),y=raw(f(b));if(isNaN(x)&&isNaN(y))return String(f(a)).localeCompare(String(f(b)));if(isNaN(x))return 1;if(isNaN(y))return -1;return (x-y)*sortDir;});
      tbody.replaceChildren();rows.forEach(p=>{const tr=document.createElement('tr');if(cfg.hl&&cfg.hl(p))tr.className='hl';cfg.cols.forEach(([k,ff])=>{const td=document.createElement('td');td.textContent=ff(p);if(!textCol(k))td.className='right';tr.appendChild(td);});tbody.appendChild(tr);});
      trh.querySelectorAll('th').forEach(th=>{const k=th.dataset.key;th.classList.toggle('sorted',k===sortKey);th.setAttribute('aria-sort',k===sortKey?(sortDir===1?'ascending':'descending'):'none');th.querySelector('.arr').textContent=k===sortKey?(sortDir===1?' ▲':' ▼'):'';});}
    cfg.cols.forEach(([k])=>{const th=document.createElement('th');th.dataset.key=k;th.textContent=k;const arr=document.createElement('span');arr.className='arr';th.appendChild(arr);if(!textCol(k))th.className='right';th.tabIndex=0;th.setAttribute('role','button');th.setAttribute('scope','col');
      const go=()=>{if(sortKey===k)sortDir=-sortDir;else{sortKey=k;sortDir=textCol(k)?1:-1;}render();};th.addEventListener('click',go);th.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();go();}});trh.appendChild(th);});
    thead.appendChild(trh);tb.appendChild(thead);tb.appendChild(tbody);render();tw.appendChild(tb);det.appendChild(tw);host.appendChild(det);}
}

// --- team chart
const T=L.map(r=>({n:r.team,pr:r.proj,ac:r.official,t:'team',r}));
scatter(document.getElementById('chart-teams'),{
  title:'Team totals: projected vs. official',note:'One dot per team. Above the dashed line beat projection; below fell short.',h:520,r:7,
  data:T,x:[4200,4900],y:[4200,4900],xt:[4200,4300,4400,4500,4600,4700,4800,4900],yt:[4200,4300,4400,4500,4600,4700,4800,4900],
  xLabel:'Preseason projection (BT points)',yLabel:'Official final (BT points)',
  labels:T.map(t=>{const right=['Winters','Palma','Mudge','Lerner','Williams'].includes(t.n);const dy=t.n==='Tchir'?-12:(t.n==='Williams'?10:0);return [t.n,right?12:-12,dy,right?'start':'end','team'];}),
  tip:t=>({name:t.n,meta:`Finished ${t.r.rank}${['st','nd','rd'][t.r.rank-1]||'th'} of 9 · projected ${t.r.proj_rank}${['st','nd','rd'][t.r.proj_rank-1]||'th'} · drafted roster ranked ${t.r.draft_rank}${['st','nd','rd'][t.r.draft_rank-1]||'th'}`,top:[['Official',fmt(t.ac)],['Projected',fmt(t.pr)],['Difference',sg(t.ac-t.pr)]],rows:[['Hitters',`${fmt(t.r.off_hit)} vs ${fmt(t.r.proj_hit)} proj.`],['SP (best 3 × 3.5)',`${t.r.off_sp} vs ${t.r.proj_sp} proj.`],['RP',`${t.r.off_rp} vs ${t.r.proj_rp} proj.`],['Drafted 16, no moves',fmt(t.r.noswap)],['In-season moves',sg(t.r.moves)]],calc:''})
});

// --- dumbbell: drafted vs official
(function(){
  const host=document.getElementById('chart-moves');host.innerHTML='';
  const hd=document.createElement('div');hd.className='hd';const h3=document.createElement('h3');h3.textContent='Drafted roster vs. official final, by team';hd.appendChild(h3);host.appendChild(hd);
  const note=document.createElement('p');note.className='note';note.textContent='Blue dot: the original 16 on full-season actuals with no moves. Orange dot: official final. The bar between them is what in-season moves were worth; for Tchir the moves cost points, so the orange dot sits to the left. Sorted by official finish.';host.appendChild(note);
  const lg=document.createElement('div');lg.className='legend';[['s1','Drafted 16, no moves'],['s2','Official final']].forEach(([c,t])=>{const s=document.createElement('span');const i=document.createElement('i');i.style.background=`var(--${c})`;s.appendChild(i);s.appendChild(document.createTextNode(t));lg.appendChild(s);});host.appendChild(lg);
  const plot=document.createElement('div');plot.className='plot';host.appendChild(plot);
  const rows=[...L].sort((a,b)=>a.rank-b.rank);const W=900,rh=40,m={l:110,r:70,t:14,b:44},H=m.t+m.b+rows.length*rh,iw=W-m.l-m.r;
  const x0=3800,x1=4900,sx=v=>m.l+(v-x0)/(x1-x0)*iw;
  const svg=el('svg',{viewBox:`0 0 ${W} ${H}`,role:'img','aria-label':'Drafted roster versus official final by team'});
  [3800,4000,4200,4400,4600,4800].forEach(v=>{svg.appendChild(el('line',{class:'grid',x1:sx(v),x2:sx(v),y1:m.t,y2:H-m.b}));svg.appendChild(el('text',{x:sx(v),y:H-m.b+18,'text-anchor':'middle'},fmt(v)));});
  svg.appendChild(el('text',{x:m.l+iw/2,y:H-6,'text-anchor':'middle'},'BT points'));
  const tip=makeTip(plot);const hits=[];
  rows.forEach((r,i)=>{const y=m.t+i*rh+rh/2;
    svg.appendChild(el('text',{class:'lbl team',x:m.l-12,y:y+4,'text-anchor':'end'},r.team));
    svg.appendChild(el('line',{class:'db',x1:sx(r.noswap),x2:sx(r.official),y1:y,y2:y}));
    const a=el('circle',{class:'pt s1',cx:sx(r.noswap),cy:y,r:6.5});const b=el('circle',{class:'pt s2',cx:sx(r.official),cy:y,r:6.5});
    svg.appendChild(a);svg.appendChild(b);
    const right=Math.max(sx(r.noswap),sx(r.official));svg.appendChild(el('text',{x:right+12,y:y+4,'text-anchor':'start'},sg(r.moves)));
    const hit=el('rect',{x:m.l,y:y-rh/2,width:iw,height:rh,fill:'transparent',tabindex:'0',role:'img','aria-label':`${r.team}: drafted ${fmt(r.noswap)}, official ${fmt(r.official)}, moves ${sg(r.moves)}`});
    svg.appendChild(hit);hits.push([hit,r,y,[a,b]]);
  });
  plot.appendChild(svg);
  let cur=null;
  function show(h,px,py){if(cur)cur[3].forEach(n=>n.classList.remove('on'));cur=h;h[3].forEach(n=>n.classList.add('on'));const r=h[1];fillTip(tip,{name:r.team,meta:`Finished ${r.rank}${['st','nd','rd'][r.rank-1]||'th'} of 9`,top:[['Official final',fmt(r.official)],['Drafted 16, no moves',fmt(r.noswap)],['In-season moves',sg(r.moves)]],rows:[['Best pick vs projection',r.best],['Worst pick vs projection',r.worst],['Picks at or above projection',r.beat]],calc:''});placeTip(tip,plot,px,py);}
  function hide(){if(cur)cur[3].forEach(n=>n.classList.remove('on'));cur=null;tip.hidden=true;}
  hits.forEach(h=>{h[0].addEventListener('pointermove',e=>{const pr=plot.getBoundingClientRect();show(h,e.clientX-pr.left,e.clientY-pr.top);});h[0].addEventListener('pointerleave',hide);h[0].addEventListener('focus',()=>{const pr=plot.getBoundingClientRect(),b=h[0].getBoundingClientRect();show(h,b.left-pr.left+b.width*0.6,b.top-pr.top+b.height/2);});h[0].addEventListener('blur',hide);});
})();

const hitters=P.filter(p=>p.t==='hitter'),pitchers=P.filter(p=>p.t!=='hitter');
scatter(document.getElementById('chart-hit'),{
  title:'Drafted hitters: projection vs. actual',note:'81 drafted hitters, full 2026 season regardless of when a player was swapped. Dots below the dashed line scored less than projected.',
  data:hitters,x:[350,630],y:[80,630],xt:[350,400,450,500,550,600],yt:[100,200,300,400,500,600],xLabel:'Preseason projection (BT points)',yLabel:'Actual 2026 (BT points)',tip:playerTip,
  labels:[['Pete Crow-Armstrong',-10,0,'end'],['Yordan Alvarez',-10,0,'end'],['Randy Arozarena',-10,0,'end'],['Fernando Tatis Jr.',10,-8,'start'],['Shohei Ohtani',0,16,'middle'],['Francisco Lindor',10,0,'start'],['Cal Raleigh',10,0,'start'],['Aaron Judge',-10,0,'end'],['Roman Anthony',10,0,'start'],['Brent Rooker',10,0,'start'],['Giancarlo Stanton',10,0,'start'],['Luis Robert Jr.',-10,0,'end']],
  cols:[['Player',p=>p.n],['Team',p=>p.o],['Pick',p=>p.pk>108?'DH':p.pk],['Proj',p=>fmt(p.pr)],['Actual',p=>fmt(p.ac)],['Diff',p=>sg(p.ac-p.pr)],['AB',p=>p.AB],['AVG',p=>avgS(p.H,p.AB)],['HR',p=>p.HR],['RBI',p=>p.RBI],['R',p=>p.R],['SB',p=>p.SB]]
});
scatter(document.getElementById('chart-pit'),{
  title:'Drafted pitchers: projection vs. actual',note:'54 starters (circles) and 9 relievers (diamonds), scored individually before the best-three rule. SP points are RSAR × 3.5; RP points are 5 × (W + SV).',
  data:pitchers,x:[30,200],y:[-60,250],xt:[40,60,80,100,120,140,160,180,200],yt:[-50,0,50,100,150,200,250],xLabel:'Preseason projection (BT points)',yLabel:'Actual 2026 (BT points)',tip:playerTip,
  labels:[['Cam Schlittler',10,0,'start'],['Jacob Misiorowski',10,0,'start'],['Cade Smith',10,0,'start'],['Mason Miller',-10,0,'end'],['Chris Sale',10,0,'start'],['Cristopher Sánchez',10,0,'start'],['Tarik Skubal',10,0,'start'],['Paul Skenes',10,0,'start'],['Edwin Díaz',10,0,'start'],['Garrett Crochet',-10,0,'end'],['Yoshinobu Yamamoto',-10,0,'end'],['Dylan Cease',10,0,'start'],['Drew Rasmussen',-10,0,'end']],
  cols:[['Player',p=>p.n],['Team',p=>p.o],['Role',p=>p.t.toUpperCase()],['Pick',p=>p.pk>108?'DH':p.pk],['Proj',p=>fmt(p.pr,1)],['Actual',p=>fmt(p.ac,1)],['Diff',p=>sg(p.ac-p.pr,1)],['IP',p=>fmt(p.IP,1)],['ERA',p=>p.ERA==null?'—':p.ERA.toFixed(2)],['G',p=>p.G],['W',p=>p.W],['SV',p=>p.SV],['K',p=>p.K]]
});
})();
</script>
'''
page="<title>BT Pool 2026 Season Review</title>\n"+style+"\n<div class='wrap'>"+body+"</div>\n"+js.replace("__DATA__",players.replace("</","<\\/")).replace("__LEAGUE__",json.dumps(league).replace("</","<\\/"))
open(f"{SC}/bt-2026-season-review.html","w").write(page); print("written",len(page))

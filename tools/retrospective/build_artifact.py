import json, re, html
from pathlib import Path
SC=str(Path(__file__).resolve().parent)   # inputs and outputs live next to this script
REPO=str(Path(__file__).resolve().parents[2])
md=open(f"{REPO}/season-2026-retrospective.md").read()
players=open(f"{SC}/players.json").read()

def inline(t):
    t=html.escape(t,quote=False)
    t=re.sub(r"\*\*(.+?)\*\*",r"<strong>\1</strong>",t)
    t=re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)",r"<em>\1</em>",t)
    t=re.sub(r"`([^`]+)`",r"<code>\1</code>",t)
    return t

lines=md.split("\n"); out=[]; i=0; sec=0; img=0
def flush_table(rows):
    hdr=rows[0]; align=rows[1]; body=rows[2:]
    cells=lambda r:[c.strip() for c in r.strip().strip("|").split("|")]
    al=["right" if a.strip().endswith(":") else "left" for a in cells(align)]
    h="<div class='tw'><table><thead><tr>"+"".join(f"<th class='{a}'>{inline(c)}</th>" for c,a in zip(cells(hdr),al))+"</tr></thead><tbody>"
    for r in body:
        cs=cells(r); strong=" class='hl'" if any("Levinsons" in c for c in cs) else ""
        h+=f"<tr{strong}>"+"".join(f"<td class='{a}'>{inline(c)}</td>" for c,a in zip(cs,al))+"</tr>"
    return h+"</tbody></table></div>"
while i<len(lines):
    l=lines[i]
    if l.startswith("# "): i+=1; continue  # page has its own masthead
    if l.startswith("## "):
        sec+=1; title=l[3:]
        if sec>1: out.append("</section>")
        sid="summary" if title.startswith("The short") else "s"+title.split(".")[0]
        t=re.sub(r"^\d+\.\s*","",title)
        out.append(f"<section id='{sid}'><h2><span class='num'>{'' if sid=='summary' else title.split('.')[0]}</span>{inline(t)}</h2>")
        i+=1; continue
    if l.startswith("!["):
        img+=1; out.append(f"<div class='chart' id='chart-{'hit' if img==1 else 'pit'}'></div>"); i+=1; continue
    if l.startswith("|"):
        rows=[]
        while i<len(lines) and lines[i].startswith("|"): rows.append(lines[i]); i+=1
        out.append(flush_table(rows)); continue
    if l.startswith("- "):
        out.append("<ul>")
        while i<len(lines) and lines[i].startswith("- "): out.append(f"<li>{inline(lines[i][2:])}</li>"); i+=1
        out.append("</ul>"); continue
    if re.match(r"^\d+\. ",l):
        out.append("<ol>")
        while i<len(lines) and re.match(r"^\d+\. ",lines[i]):
            item=re.sub(r"^\d+\. ","",lines[i]); out.append("<li>"+inline(item)+"</li>"); i+=1
        out.append("</ol>"); continue
    if l.strip()=="": i+=1; continue
    para=[]
    while i<len(lines) and lines[i].strip() and not re.match(r"^(#|\||- |\d+\. |!\[)",lines[i]): para.append(lines[i]); i+=1
    cls=" class='lede'" if sec==0 else ""
    out.append(f"<p{cls}>{inline(' '.join(para))}</p>")
out.append("</section>")
body="\n".join(out)

page=r'''<title>BT Pool 2026 Retrospective</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700&family=IBM+Plex+Sans:ital,wght@0,400;0,600;1,400&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
:root{
  --bg:#faf9f5; --bg2:#f1efe8; --ink:#17160f; --ink2:#5d5a50; --ink3:#8c887c; --rule:#dedbd1; --grid:#e7e4db;
  --s1:#2a78d6; --s2:#eb6834; --tip:#ffffff; --tipb:#cfcbbf;
  --display:"Barlow Condensed","Arial Narrow",Impact,sans-serif; --body:"IBM Plex Sans",-apple-system,"Segoe UI",Helvetica,Arial,sans-serif; --mono:"IBM Plex Mono",ui-monospace,Menlo,Consolas,monospace;
}
@media (prefers-color-scheme: dark){ :root:not([data-theme="light"]){ color-scheme:dark;
  --bg:#18181b; --bg2:#212125; --ink:#f0eee7; --ink2:#b8b4a8; --ink3:#86826f; --rule:#34343a; --grid:#2b2b30; --s1:#3987e5; --s2:#e2632f; --tip:#25252a; --tipb:#45454c; } }
:root[data-theme="dark"]{ color-scheme:dark;
  --bg:#18181b; --bg2:#212125; --ink:#f0eee7; --ink2:#b8b4a8; --ink3:#86826f; --rule:#34343a; --grid:#2b2b30; --s1:#3987e5; --s2:#e2632f; --tip:#25252a; --tipb:#45454c; }
*{box-sizing:border-box}
body{background:var(--bg);color:var(--ink);font-family:var(--body);font-size:16px;line-height:1.55;margin:0;padding-inline:16px;padding-block:0 64px}
.wrap{max-width:1080px;margin:0 auto}
.mast{padding-block:40px 20px;border-bottom:3px solid var(--ink)}
.eyebrow{font-family:var(--mono);font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--ink2)}
h1{font-family:var(--display);font-weight:700;font-size:clamp(40px,7vw,72px);line-height:.95;margin:8px 0 14px;letter-spacing:-.01em;text-wrap:balance}
.sub{font-size:17px;color:var(--ink2);max-width:62ch;margin:0}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:0;border-bottom:1px solid var(--rule)}
.tile{padding:18px 16px 16px 0;border-right:1px solid var(--rule);margin-right:16px}
.tile:last-child{border-right:0}
.tile .v{font-family:var(--display);font-weight:700;font-size:44px;line-height:1;font-variant-numeric:tabular-nums}
.tile .v small{font-size:22px;color:var(--ink2);font-weight:600;margin-left:4px}
.tile .k{font-size:13px;color:var(--ink2);margin-top:6px}
nav.toc{position:sticky;top:env(safe-area-inset-top,0px);background:var(--bg);border-bottom:1px solid var(--rule);z-index:5;overflow-x:auto;white-space:nowrap;margin-inline:-16px;padding-inline:16px}
nav.toc a{display:inline-block;padding:10px 12px 9px 0;margin-right:10px;font-family:var(--mono);font-size:12px;letter-spacing:.04em;text-transform:uppercase;color:var(--ink2);text-decoration:none;border-bottom:2px solid transparent}
nav.toc a:hover,nav.toc a:focus-visible{color:var(--ink);border-bottom-color:var(--s2);outline:none}
main{display:grid;grid-template-columns:minmax(0,1fr);gap:0}
section{padding-block:36px 8px;border-bottom:1px solid var(--rule)}
section:last-of-type{border-bottom:0}
h2{font-family:var(--display);font-weight:700;font-size:34px;line-height:1;margin:0 0 18px;text-wrap:balance;display:flex;align-items:baseline;gap:12px}
h2 .num{font-family:var(--mono);font-size:14px;color:var(--s2);font-weight:500;letter-spacing:.06em}
h2 .num:empty{display:none}
p,li{max-width:70ch}
p.lede{font-size:15px;color:var(--ink2);max-width:80ch}
ul,ol{padding-left:22px}
li{margin-bottom:8px}
li::marker{color:var(--ink3)}
strong{font-weight:600}
code{font-family:var(--mono);font-size:.86em;background:var(--bg2);padding:1px 5px;border-radius:3px}
.tw{overflow-x:auto;margin:14px 0 22px}
table{border-collapse:collapse;width:100%;font-size:14px;font-variant-numeric:tabular-nums}
th,td{padding:8px 10px;border-bottom:1px solid var(--rule);text-align:left;vertical-align:top}
th{font-family:var(--mono);font-size:11.5px;letter-spacing:.05em;text-transform:uppercase;color:var(--ink2);border-bottom:2px solid var(--ink);white-space:nowrap}
td.right,th.right{text-align:right}
tr.hl td{background:var(--bg2)}
/* charts */
.chart{margin:26px 0 30px;padding:0}
.chart .hd{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:baseline;gap:6px 18px;margin-bottom:6px}
.chart h3{font-family:var(--display);font-weight:600;font-size:24px;margin:0;line-height:1.1}
.chart .note{font-size:13px;color:var(--ink2);max-width:80ch;margin:2px 0 10px}
.legend{display:flex;flex-wrap:wrap;gap:6px 18px;font-size:13px;color:var(--ink2);margin:0 0 8px}
.legend span{display:inline-flex;align-items:center;gap:7px}
.legend i{display:inline-block;width:10px;height:10px;border-radius:50%}
.legend i.d{border-radius:2px;transform:rotate(45deg) scale(.85)}
.plot{position:relative}
.plot svg{width:100%;height:auto;display:block;overflow:visible}
.plot svg text{font-family:var(--body);fill:var(--ink2);font-size:12px}
.plot svg text.lbl{fill:var(--ink);font-size:11.5px}
.plot svg .grid{stroke:var(--grid);stroke-width:1}
.plot svg .ax{stroke:var(--rule)}
.plot svg .diag{stroke:var(--ink3);stroke-width:1.2;stroke-dasharray:5 4}
.plot svg .pt{stroke:var(--bg);stroke-width:2;cursor:pointer;transition:r .12s ease}
.plot svg .pt.s1{fill:var(--s1)} .plot svg .pt.s2{fill:var(--s2)}
.plot svg .pt.on{stroke:var(--ink);stroke-width:2.5}
.plot svg .pt:focus{outline:none}
.tip{position:absolute;z-index:6;pointer-events:none;background:var(--tip);border:1px solid var(--tipb);border-radius:6px;padding:10px 12px;min-width:220px;max-width:280px;box-shadow:0 6px 24px rgba(0,0,0,.12);font-size:13px;line-height:1.4}
.tip .n{font-weight:600;font-size:14px;color:var(--ink)}
.tip .m{color:var(--ink2);font-size:12px;margin-bottom:6px}
.tip .row{display:flex;justify-content:space-between;gap:14px;font-variant-numeric:tabular-nums}
.tip .row b{font-weight:600}
.tip .k{color:var(--ink2)}
.tip .sep{border-top:1px solid var(--tipb);margin:7px 0 6px}
.tip .calc{font-family:var(--mono);font-size:11.5px;color:var(--ink2);white-space:pre-line}
.tip .swatch{display:inline-block;width:14px;height:3px;vertical-align:middle;margin-right:6px;border-radius:2px}
details.tv{margin-top:8px;font-size:13px}
details.tv summary{cursor:pointer;color:var(--ink2);font-family:var(--mono);font-size:12px;letter-spacing:.04em;text-transform:uppercase}
details.tv summary:focus-visible{outline:2px solid var(--s1);outline-offset:2px}
th[role="button"]{cursor:pointer;user-select:none}
th[role="button"]:hover,th[role="button"]:focus-visible{color:var(--ink);outline:none}
th.sorted{color:var(--ink);border-bottom-color:var(--s2)}
th .arr{font-size:9px}

.foot{margin-top:40px;font-size:12.5px;color:var(--ink3);max-width:80ch}
@media (prefers-reduced-motion:reduce){.plot svg .pt{transition:none}}
@media (max-width:600px){.tile{border-right:0;padding-right:0;margin-right:0} .tile .v{font-size:36px} h2{font-size:28px}}
</style>

<div class="wrap">
<header class="mast">
  <div class="eyebrow">BT Baseball Pool 2026 · Levinsons · Draft retrospective · Data through Sep 27, 2026</div>
  <h1>What the model got right, and what the season did anyway</h1>
  <p class="sub">The preseason board from draft day (March 30) versus the official commissioner results, pick by pick, swap by swap. Hover any dot in the two charts for a player's projection, actual, and the stat line behind it.</p>
</header>
<div class="tiles">
  <div class="tile"><div class="v">4,676<small>2nd of 9</small></div><div class="k">Official final. 112 behind Cobey.</div></div>
  <div class="tile"><div class="v">4,637<small>6th</small></div><div class="k">Model projection on draft day. Total on the number, rank wrong.</div></div>
  <div class="tile"><div class="v">4,124<small>9th</small></div><div class="k">The drafted 16 on full-season actuals, no swaps.</div></div>
  <div class="tile"><div class="v">+552</div><div class="k">Points added by five in-season substitutions.</div></div>
</div>
<nav class="toc" aria-label="Sections">
  <a href="#summary">Summary</a><a href="#s1">Standings</a><a href="#s2">Picks</a><a href="#s3">Points</a><a href="#s4">Swaps</a><a href="#s5">Calibration &amp; charts</a><a href="#s6">Right</a><a href="#s7">Wrong</a><a href="#s8">2027</a>
</nav>
<main>
__BODY__
<p class="foot">Sources: PitcherList projections scored under the BT formula (draft-day cache), the league draft tracker, MLB Stats API 2026 regular-season totals and game logs, and the commissioner's RESULTS workbook. Actual points use the official final MLERA of 4.17. Hitter batting average applies the 300 AB floor. SP points shown per pitcher are RSAR × 3.5 before the top-3 rule; a starter under 3.5 IP per appearance scores zero.</p>
</main>
</div>

<script id="players" type="application/json">__DATA__</script>
<script>
(function(){
const P=JSON.parse(document.getElementById('players').textContent);
const MLERA=4.17;
const fmt=(n,d=0)=>Number(n).toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d});
const avgS=(h,ab)=>{const a=ab?h/ab:0;return a.toFixed(3).replace(/^0/,'')};

function breakdown(p){
  if(p.t==='hitter'){
    const floor=p.AB<300, den=Math.max(p.AB,300), ba=Math.round((den?p.H/den:0)*1000);
    return {rows:[['AB / H',`${p.AB} / ${p.H}`],['AVG',avgS(p.H,p.AB)+(floor?' (floor: '+avgS(p.H,300)+')':'')],['HR',p.HR],['RBI',p.RBI],['R',p.R],['SB',p.SB],['Games',p.G]],
      calc:`${ba} (BA×1000${floor?', 300 AB floor':''}) + ${p.HR} HR + ${p.RBI} RBI + ${p.R} R + ${p.SB} SB = ${p.ac}`};
  }
  if(p.t==='sp'){
    const short=p.G>0 && p.IP/p.G<3.5;
    const rsar=p.ERA==null||p.IP===0?0:Math.round((1.2*MLERA-p.ERA)*p.IP/9);
    return {rows:[['IP',fmt(p.IP,1)],['ERA',p.ERA==null?'—':p.ERA.toFixed(2)],['G / GS',`${p.G} / ${p.GS}`],['W',p.W],['K',p.K]],
      calc: short?`Under 3.5 IP per appearance: RSAR set to 0`:`RSAR = (1.2×4.17 − ${p.ERA==null?'—':p.ERA.toFixed(2)}) × ${fmt(p.IP,1)}/9 = ${rsar}\n${rsar} × 3.5 = ${p.ac}`};
  }
  return {rows:[['W',p.W],['SV',p.SV],['G',p.G],['ERA',p.ERA==null?'—':p.ERA.toFixed(2)],['IP',fmt(p.IP,1)]], calc:`5 × (${p.W} W + ${p.SV} SV) = ${p.ac}`};
}
function pickLabel(p){ return p.pk>108?`DH round (13th), order ${p.pk-108}`:`pick ${p.pk} (round ${Math.ceil(p.pk/9)}${p.pair?', second of SP pair':''})`; }

function scatter(host,cfg){
  const W=900,H=600,m={l:64,r:24,t:18,b:56}, iw=W-m.l-m.r, ih=H-m.t-m.b;
  const sx=v=>m.l+(v-cfg.x[0])/(cfg.x[1]-cfg.x[0])*iw, sy=v=>m.t+ih-(v-cfg.y[0])/(cfg.y[1]-cfg.y[0])*ih;
  const data=cfg.data;
  host.innerHTML='';
  const hd=document.createElement('div');hd.className='hd';
  const h3=document.createElement('h3');h3.textContent=cfg.title;hd.appendChild(h3);host.appendChild(hd);
  const note=document.createElement('p');note.className='note';note.textContent=cfg.note;host.appendChild(note);
  const lg=document.createElement('div');lg.className='legend';
  cfg.legend.forEach(([cls,shape,txt])=>{const s=document.createElement('span');const i=document.createElement('i');i.className=shape==='d'?'d':'';i.style.background=`var(--${cls})`;s.appendChild(i);s.appendChild(document.createTextNode(txt));lg.appendChild(s);});
  host.appendChild(lg);
  const plot=document.createElement('div');plot.className='plot';host.appendChild(plot);
  const NS='http://www.w3.org/2000/svg';
  const svg=document.createElementNS(NS,'svg');svg.setAttribute('viewBox',`0 0 ${W} ${H}`);svg.setAttribute('role','img');svg.setAttribute('aria-label',cfg.title);
  const el=(n,a,txt)=>{const e=document.createElementNS(NS,n);for(const k in a)e.setAttribute(k,a[k]);if(txt!=null)e.textContent=txt;return e;};
  // grid + ticks
  cfg.xt.forEach(v=>{svg.appendChild(el('line',{class:'grid',x1:sx(v),x2:sx(v),y1:m.t,y2:m.t+ih}));svg.appendChild(el('text',{x:sx(v),y:m.t+ih+18,'text-anchor':'middle'},fmt(v)));});
  cfg.yt.forEach(v=>{svg.appendChild(el('line',{class:'grid',x1:m.l,x2:m.l+iw,y1:sy(v),y2:sy(v)}));svg.appendChild(el('text',{x:m.l-10,y:sy(v)+4,'text-anchor':'end'},fmt(v)));});
  svg.appendChild(el('line',{class:'ax',x1:m.l,x2:m.l+iw,y1:m.t+ih,y2:m.t+ih}));
  svg.appendChild(el('line',{class:'ax',x1:m.l,x2:m.l,y1:m.t,y2:m.t+ih}));
  // diagonal
  const d0=Math.max(cfg.x[0],cfg.y[0]), d1=Math.min(cfg.x[1],cfg.y[1]);
  svg.appendChild(el('line',{class:'diag',x1:sx(d0),y1:sy(d0),x2:sx(d1),y2:sy(d1)}));
  svg.appendChild(el('text',{x:sx(d1)-6,y:sy(d1)+16,'text-anchor':'end'},'actual = projected'));
  svg.appendChild(el('text',{x:m.l+iw/2,y:H-10,'text-anchor':'middle'},cfg.xLabel));
  const yl=el('text',{x:16,y:m.t+ih/2,'text-anchor':'middle',transform:`rotate(-90 16 ${m.t+ih/2})`},cfg.yLabel);svg.appendChild(yl);
  // points (Levinsons drawn last so they sit on top)
  const order=[...data].sort((a,b)=>(a.o==='Levinsons')-(b.o==='Levinsons'));
  const nodes=new Map();
  order.forEach(p=>{
    const cls=(p.o==='Levinsons'?'s2':'s1'), x=sx(p.pr), y=sy(p.ac);
    let n;
    if(p.t==='rp'){const r=7;n=el('path',{d:`M${x} ${y-r}L${x+r} ${y}L${x} ${y+r}L${x-r} ${y}Z`});}
    else n=el('circle',{cx:x,cy:y,r:p.o==='Levinsons'?6.5:5.5});
    n.setAttribute('class',`pt ${cls}`);n.setAttribute('tabindex','0');n.setAttribute('role','img');
    n.setAttribute('aria-label',`${p.n}, ${p.o}: projected ${fmt(p.pr)}, actual ${fmt(p.ac)}`);
    svg.appendChild(n);nodes.set(p,n);
  });
  // selective labels
  (cfg.labels||[]).forEach(([name,dx,dy,anchor])=>{const p=data.find(q=>q.n===name);if(!p)return;svg.appendChild(el('text',{class:'lbl',x:sx(p.pr)+dx,y:sy(p.ac)+dy+4,'text-anchor':anchor},p.n));});
  plot.appendChild(svg);
  // tooltip
  const tip=document.createElement('div');tip.className='tip';tip.hidden=true;plot.appendChild(tip);
  let cur=null;
  function show(p,px,py){
    if(cur&&cur!==p)nodes.get(cur).classList.remove('on');
    cur=p;nodes.get(p).classList.add('on');
    tip.replaceChildren();
    const n=document.createElement('div');n.className='n';const sw=document.createElement('span');sw.className='swatch';sw.style.background=`var(--${p.o==='Levinsons'?'s2':'s1'})`;n.appendChild(sw);n.appendChild(document.createTextNode(p.n));tip.appendChild(n);
    const mm=document.createElement('div');mm.className='m';mm.textContent=`${p.o} · ${p.pos.replace(/\d/,'')} · ${pickLabel(p)}`;tip.appendChild(mm);
    const rows=[['Projected',fmt(p.pr)],['Actual',fmt(p.ac)],['Difference',(p.ac-p.pr>=0?'+':'')+fmt(p.ac-p.pr)]];
    rows.forEach(([k,v],i)=>{const r=document.createElement('div');r.className='row';const a=document.createElement('span');a.className='k';a.textContent=k;const b=document.createElement('b');b.textContent=v;r.appendChild(a);r.appendChild(b);tip.appendChild(r);});
    const sep=document.createElement('div');sep.className='sep';tip.appendChild(sep);
    const bd=breakdown(p);
    bd.rows.forEach(([k,v])=>{const r=document.createElement('div');r.className='row';const a=document.createElement('span');a.className='k';a.textContent=k;const b=document.createElement('span');b.textContent=String(v);r.appendChild(a);r.appendChild(b);tip.appendChild(r);});
    const sep2=document.createElement('div');sep2.className='sep';tip.appendChild(sep2);
    const c=document.createElement('div');c.className='calc';c.textContent=bd.calc;tip.appendChild(c);
    tip.hidden=false;
    const pr=plot.getBoundingClientRect(), tw=tip.offsetWidth, th=tip.offsetHeight;
    let lx=px+14, ly=py-10;
    if(lx+tw>pr.width-4)lx=px-tw-14; if(lx<0)lx=4;
    if(ly+th>pr.height-4)ly=pr.height-th-4; if(ly<0)ly=4;
    tip.style.left=lx+'px';tip.style.top=ly+'px';
  }
  function hide(){if(cur)nodes.get(cur).classList.remove('on');cur=null;tip.hidden=true;}
  svg.addEventListener('pointermove',e=>{
    const pt=svg.createSVGPoint();pt.x=e.clientX;pt.y=e.clientY;const q=pt.matrixTransform(svg.getScreenCTM().inverse());
    let best=null,bd=1e9;data.forEach(p=>{const dx=sx(p.pr)-q.x,dy=sy(p.ac)-q.y,d=dx*dx+dy*dy;if(d<bd){bd=d;best=p;}});
    if(best&&bd<28*28){const pr=plot.getBoundingClientRect();show(best,e.clientX-pr.left,e.clientY-pr.top);}else hide();
  });
  svg.addEventListener('pointerleave',hide);
  nodes.forEach((n,p)=>{n.addEventListener('focus',()=>{const pr=plot.getBoundingClientRect(),b=n.getBoundingClientRect();show(p,b.left-pr.left+b.width/2,b.top-pr.top+b.height/2);});n.addEventListener('blur',hide);});
  {const det=document.createElement('details');det.className='tv';const sm=document.createElement('summary');sm.textContent='Show as table (click a column heading to sort)';det.appendChild(sm);const tw=document.createElement('div');tw.className='tw';const tb=document.createElement('table');const thead=document.createElement('thead');const trh=document.createElement('tr');const tbody=document.createElement('tbody');
    const textCol=k=>k==='Player'||k==='Team'||k==='Role';
    const raw=s=>{if(s==null)return NaN;const t=String(s).replace(/,/g,'').replace(/^\+/,'');if(t==='—'||t==='')return NaN;const n=Number(t);return isNaN(n)?NaN:n;};
    let sortKey='Diff',sortDir=1;
    function render(){const col=cfg.cols.find(c=>c[0]===sortKey)||cfg.cols[0];const f=col[1];const isText=textCol(col[0]);
      const rows=[...data].sort((a,b)=>{if(isText){return String(f(a)).localeCompare(String(f(b)))*sortDir;}const x=raw(f(a)),y=raw(f(b));if(isNaN(x)&&isNaN(y))return String(f(a)).localeCompare(String(f(b)));if(isNaN(x))return 1;if(isNaN(y))return -1;return (x-y)*sortDir;});
      tbody.replaceChildren();rows.forEach(p=>{const tr=document.createElement('tr');if(p.o==='Levinsons')tr.className='hl';cfg.cols.forEach(([k,ff])=>{const td=document.createElement('td');td.textContent=ff(p);if(!textCol(k))td.className='right';tr.appendChild(td);});tbody.appendChild(tr);});
      trh.querySelectorAll('th').forEach(th=>{const k=th.dataset.key;th.classList.toggle('sorted',k===sortKey);th.setAttribute('aria-sort',k===sortKey?(sortDir===1?'ascending':'descending'):'none');th.querySelector('.arr').textContent=k===sortKey?(sortDir===1?' ▲':' ▼'):'';});}
    cfg.cols.forEach(([k])=>{const th=document.createElement('th');th.dataset.key=k;th.textContent=k;const arr=document.createElement('span');arr.className='arr';th.appendChild(arr);if(!textCol(k))th.className='right';th.tabIndex=0;th.setAttribute('role','button');th.setAttribute('scope','col');
      const go=()=>{if(sortKey===k)sortDir=-sortDir;else{sortKey=k;sortDir=textCol(k)?1:-1;}render();};th.addEventListener('click',go);th.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();go();}});trh.appendChild(th);});
    thead.appendChild(trh);tb.appendChild(thead);tb.appendChild(tbody);render();tw.appendChild(tb);det.appendChild(tw);host.appendChild(det);}
}

const hitters=P.filter(p=>p.t==='hitter'), pitchers=P.filter(p=>p.t!=='hitter');
scatter(document.getElementById('chart-hit'),{
  title:'Drafted hitters: projection vs. actual', note:'81 drafted hitters, full 2026 season regardless of when a player was swapped out. Correlation 0.20. Dots below the dashed line scored less than projected. Hover or tab to a dot for the stat line.',
  data:hitters, x:[350,630], y:[80,630], xt:[350,400,450,500,550,600], yt:[100,200,300,400,500,600],
  xLabel:'Preseason projection (BT points)', yLabel:'Actual 2026 (BT points)',
  legend:[['s1','c','Other teams’ hitters (72)'],['s2','c','Levinsons’ hitters (9)']],
  labels:[['Pete Crow-Armstrong',-10,0,'end'],['Yordan Alvarez',-10,0,'end'],['Randy Arozarena',-10,0,'end'],['Bryce Harper',10,-6,'start'],['Luis Arraez',-10,0,'end'],['Shohei Ohtani',0,16,'middle'],['Francisco Lindor',10,0,'start'],['Cal Raleigh',10,0,'start'],['Aaron Judge',-10,0,'end'],['Roman Anthony',10,0,'start'],['Brent Rooker',10,0,'start'],['Giancarlo Stanton',10,0,'start']],
  cols:[['Player',p=>p.n],['Team',p=>p.o],['Pick',p=>p.pk>108?'DH':p.pk],['Proj',p=>fmt(p.pr)],['Actual',p=>fmt(p.ac)],['Diff',p=>(p.ac-p.pr>=0?'+':'')+fmt(p.ac-p.pr)],['AB',p=>p.AB],['AVG',p=>avgS(p.H,p.AB)],['HR',p=>p.HR],['RBI',p=>p.RBI],['R',p=>p.R],['SB',p=>p.SB]]
});
scatter(document.getElementById('chart-pit'),{
  title:'Drafted pitchers: projection vs. actual', note:'54 starters (circles) and 9 relievers (diamonds), scored individually before the top-3 rule. SP correlation 0.25. SP points are RSAR × 3.5; RP points are 5 × (W + SV).',
  data:pitchers, x:[30,200], y:[-60,250], xt:[40,60,80,100,120,140,160,180,200], yt:[-50,0,50,100,150,200,250],
  xLabel:'Preseason projection (BT points)', yLabel:'Actual 2026 (BT points)',
  legend:[['s1','c','Other teams, SP (48)'],['s1','d','Other teams, RP (8)'],['s2','c','Levinsons, SP (6)'],['s2','d','Levinsons, RP (1)']],
  labels:[['Cam Schlittler',10,0,'start'],['Jacob Misiorowski',10,0,'start'],['Cade Smith',10,0,'start'],['Mason Miller',-10,0,'end'],['Chris Sale',10,0,'start'],['Cristopher Sánchez',10,0,'start'],['Tarik Skubal',10,0,'start'],['Paul Skenes',10,0,'start'],['Edwin Díaz',10,0,'start'],['Garrett Crochet',-10,0,'end'],['Chase Burns',-10,-4,'end'],['Zack Wheeler',10,-2,'start'],['Reid Detmers',-10,0,'end'],['Devin Williams',10,0,'start'],['Cole Ragans',10,0,'start'],['Emmet Sheehan',-10,0,'end']],
  cols:[['Player',p=>p.n],['Team',p=>p.o],['Role',p=>p.t.toUpperCase()],['Pick',p=>p.pk>108?'DH':p.pk],['Proj',p=>fmt(p.pr,1)],['Actual',p=>fmt(p.ac,1)],['Diff',p=>(p.ac-p.pr>=0?'+':'')+fmt(p.ac-p.pr,1)],['IP',p=>fmt(p.IP,1)],['ERA',p=>p.ERA==null?'—':p.ERA.toFixed(2)],['G',p=>p.G],['W',p=>p.W],['SV',p=>p.SV],['K',p=>p.K]]
});
})();
</script>
'''
page=page.replace("__BODY__",body).replace("__DATA__",players.replace("</","<\\/"))
open(f"{SC}/bt-2026-retrospective.html","w").write(page)
print("written",len(page),"bytes; sections:",sec)

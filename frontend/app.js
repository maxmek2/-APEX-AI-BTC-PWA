const API = window.APEX_API_BASE || "https://apex-ai-btc-pwa.onrender.com/api";
let selectedTimeframe = "5Min";
const labels = { "1Min":"1m", "5Min":"5m", "15Min":"15m", "1Hour":"1h" };
const money = value => new Intl.NumberFormat("en-US",{style:"currency",currency:"USD"}).format(Number(value || 0));
const byId = id => document.getElementById(id);

async function get(path) {
  const response = await fetch(API + path,{headers:{Accept:"application/json"},cache:"no-store"});
  if (!response.ok) throw new Error("HTTP " + response.status + " at " + path);
  return response.json();
}
function setText(id,value){const el=byId(id);if(el)el.textContent=value;}
function setConnection(message,ok=false){
  const el=byId("connection"); if(!el)return;
  el.textContent=message; el.style.color=ok?"var(--green)":"#ffb27d";
}
function ema(values,period){
  if(values.length<period)return [];
  const out=[]; let value=values.slice(0,period).reduce((a,b)=>a+b,0)/period;
  for(let i=0;i<period-1;i++)out.push(null);
  out.push(value); const alpha=2/(period+1);
  for(let i=period;i<values.length;i++){value=alpha*values[i]+(1-alpha)*value;out.push(value);}
  return out;
}
function atr(bars,period=14){
  if(bars.length<period+1)return null;
  const tr=[];
  for(let i=1;i<bars.length;i++){
    const b=bars[i],p=bars[i-1].c;
    tr.push(Math.max(b.h-b.l,Math.abs(b.h-p),Math.abs(b.l-p)));
  }
  let value=tr.slice(0,period).reduce((a,b)=>a+b,0)/period;
  for(let i=period;i<tr.length;i++)value=(value*(period-1)+tr[i])/period;
  return value;
}
function renderChart(rawBars){
  const svg=byId("price-chart"); if(!svg)return;
  const bars=(rawBars||[]).map(b=>({o:+b.o,h:+b.h,l:+b.l,c:+b.c}))
    .filter(b=>[b.o,b.h,b.l,b.c].every(Number.isFinite));
  if(!bars.length){svg.innerHTML="";setText("chart-meta","No candle data received");return;}
  const closes=bars.map(b=>b.c), e9=ema(closes,9), e21=ema(closes,21), a=atr(bars);
  const lo=Math.min(...bars.map(b=>b.l),...e9.filter(Number.isFinite),...e21.filter(Number.isFinite));
  const hi=Math.max(...bars.map(b=>b.h),...e9.filter(Number.isFinite),...e21.filter(Number.isFinite));
  const pad=(hi-lo)*.08||1, min=lo-pad, max=hi+pad, left=12,right=888,top=34,bottom=300;
  const y=v=>bottom-(v-min)/(max-min)*(bottom-top), step=(right-left)/bars.length, width=Math.max(2,Math.min(11,step*.62));
  const candles=bars.map((b,i)=>{
    const x=left+step*(i+.5),color=b.c>=b.o?"#35d49a":"#ff6b78";
    const bodyY=Math.min(y(b.o),y(b.c)),bodyH=Math.max(1.5,Math.abs(y(b.o)-y(b.c)));
    return '<g stroke="'+color+'" fill="'+color+'"><line x1="'+x+'" y1="'+y(b.h)+'" x2="'+x+'" y2="'+y(b.l)+'" stroke-width="1.3"/><rect x="'+(x-width/2)+'" y="'+bodyY+'" width="'+width+'" height="'+bodyH+'" rx="0.7"/></g>';
  }).join("");
  const path=series=>series.map((v,i)=>v==null?"":(i?"L ":"M ")+(left+step*(i+.5)).toFixed(2)+" "+y(v).toFixed(2)).filter(Boolean).join(" ");
  const grid=[70,125,180,235,300].map(v=>'<line x1="0" y1="'+v+'" x2="900" y2="'+v+'"/>').join("");
  svg.innerHTML='<g stroke="#203149" stroke-width="1">'+grid+'</g>'+candles+
    '<path d="'+path(e9)+'" fill="none" stroke="#f5c451" stroke-width="2"/>'+
    '<path d="'+path(e21)+'" fill="none" stroke="#65a9ff" stroke-width="2"/>'+
    '<g font-size="11" font-weight="700"><text x="12" y="15" fill="#f5c451">EMA 9</text><text x="68" y="15" fill="#65a9ff">EMA 21</text><text x="145" y="15" fill="#c4d0df">ATR 14: '+(a==null?"—":money(a))+'</text></g>';
  setText("chart-meta",bars.length+" "+(labels[selectedTimeframe]||"5m")+" candles · ATR 14: "+(a==null?"need 15 candles":money(a)));
  setText("chart-time-label",labels[selectedTimeframe]||"5m");setText("atr-mini",a==null?"—":money(a));
}
function signalFromBars(bars){
  const closes=bars.map(b=>+b.c).filter(Number.isFinite);
  if(closes.length<30)return null;
  const fast=ema(closes,9).at(-1),slow=ema(closes,21).at(-1),last=closes.at(-1),vol=atr(bars);
  const direction=fast>slow&&last>fast?"LONG_SETUP":fast<slow&&last<fast?"SHORT_SETUP":"WAIT";
  return {signal:direction,ema_9:fast,ema_21:slow,last_close:last,atr_14:vol,last_bar_time:bars.at(-1).t};
}
function renderChecks(signal,bars){
  const target=byId("signal-checks");if(!target)return;
  if(!signal){target.textContent="Not enough candle data to confirm the setup.";return;}
  const up=signal.ema_9>signal.ema_21,above=signal.last_close>signal.ema_9;
  const momentum=bars.length>1?(+bars.at(-1).c>+bars.at(-2).c?"UP":+bars.at(-1).c<+bars.at(-2).c?"DOWN":"FLAT"):"UNKNOWN";
  const rows=[["EMA trend · EMA 9 vs EMA 21",up?"BULLISH":"NOT BULLISH",up],["Price position · close vs EMA 9",above?"ABOVE":"NOT ABOVE",above],["ATR 14 · volatility available",signal.atr_14>0?"VALID":"UNAVAILABLE",signal.atr_14>0],["Last-candle momentum · informational",momentum,momentum==="UP"]];
  target.innerHTML=rows.map(r=>'<div class="check-row"><span>'+r[0]+'</span><strong class="'+(r[2]?"check-pass":"check-fail")+'">'+r[1]+'</strong></div>').join("");
}
function renderQuality(signal,bars){
  if(!byId("entry-score"))return;
  if(!signal||!["LONG_SETUP","SHORT_SETUP"].includes(signal.signal)||bars.length<2){
    setText("entry-score","—");setText("entry-quality-label","NO CONFIRMED DIRECTION");
    setText("entry-quality-detail","Waiting for a directional setup and sufficient candle data.");if(byId("entry-quality-checks"))byId("entry-quality-checks").innerHTML="";return;
  }
  const isLong=signal.signal==="LONG_SETUP",last=bars.at(-1),prev=bars.at(-2);
  const tests=[["EMA trend alignment",35,isLong?signal.ema_9>signal.ema_21:signal.ema_9<signal.ema_21],
    ["Price vs EMA 9",25,isLong?signal.last_close>signal.ema_9:signal.last_close<signal.ema_9],
    ["Last-close momentum",20,isLong?+last.c>+prev.c:+last.c<+prev.c],
    ["Latest candle direction",10,isLong?+last.c>+last.o:+last.c<+last.o],
    ["ATR 14 available",10,signal.atr_14>0]];
  const score=tests.reduce((sum,t)=>sum+(t[2]?t[1]:0),0);
  setText("entry-score",score+"/100");setText("entry-quality-label",score>=85?"STRONG ALIGNMENT":score>=70?"GOOD ALIGNMENT":score>=50?"MIXED ALIGNMENT":"WEAK ALIGNMENT");
  setText("entry-quality-detail",(isLong?"LONG":"SHORT")+" rule-alignment score · heuristic, not a win probability or entry instruction.");
  if(byId("entry-quality-checks"))byId("entry-quality-checks").innerHTML=tests.map(t=>'<div class="check-row"><span>'+t[0]+' · '+t[1]+' pts</span><strong class="'+(t[2]?"check-pass":"check-fail")+'">'+(t[2]?"PASS":"NO POINTS")+'</strong></div>').join("");
}
async function refresh(){
  setConnection("Connecting to API…");
  const results=await Promise.allSettled([
    get("/account"),get("/positions"),get("/market/btc"),
    get("/market/bars?timeframe="+selectedTimeframe+"&limit=100"),
    get("/market/bars?timeframe=15Min&limit=100")
  ]);
  const account=results[0];
  if(account.status==="fulfilled"){
    const a=account.value;setText("equity",money(a.equity));setText("cash",money(a.cash));
    setText("buying",money(a.buying_power));setText("account-status",a.status||"Connected");
  }
  const pos=results[1];
  if(pos.status==="fulfilled"){
    setText("position-count",String(pos.value.length));
    setText("positions-list",pos.value.length?pos.value.map(p=>p.symbol+" · "+p.qty+" · P/L "+money(p.unrealized_pl)).join(" | "):"No open paper positions.");
  }else setText("positions-list","Positions unavailable: "+pos.reason.message);
  const market=results[2];
  if(market.status==="fulfilled"){
    setText("price",market.value.price==null?"—":money(market.value.price));
    setText("updated",market.value.timestamp?"Last trade "+new Date(market.value.timestamp).toLocaleString():"Market data unavailable");
  }else setText("updated","Market error: "+market.reason.message);
  let bars=[];
  if(results[3].status==="fulfilled"){
    bars=results[3].value.bars||[];renderChart(bars);
  }else setText("chart-meta","Chart error: "+results[3].reason.message);
  const signal=signalFromBars(bars);
  if(signal){
    const names={LONG_SETUP:"LONG SETUP",SHORT_SETUP:"SHORT SETUP",WAIT:"WAIT"};
    setText("signal-value",names[signal.signal]);setText("signal-mini",names[signal.signal]);
    setText("trend-value",signal.ema_9>signal.ema_21?"Bullish":signal.ema_9<signal.ema_21?"Bearish":"Neutral");
    setText("signal-detail","EMA 9: "+money(signal.ema_9)+" · EMA 21: "+money(signal.ema_21)+" · ATR 14: "+money(signal.atr_14));
    setText("signal-time",signal.last_bar_time?"Last candle "+new Date(signal.last_bar_time).toLocaleString():"");
  }else{
    setText("signal-value","INSUFFICIENT DATA");setText("signal-mini","WAIT");
    setText("signal-detail","Waiting for at least 30 valid candles.");setText("trend-value","—");
  }
  renderChecks(signal,bars);renderQuality(signal,bars);
  if(results[4].status==="fulfilled"){
    const higher=signalFromBars(results[4].value.bars||[]);
    setText("mtf-summary",higher?"15-minute context: "+higher.signal.replace("_SETUP",""):"15-minute data is not sufficient.");
    if(byId("mtf-checks"))byId("mtf-checks").innerHTML=higher?'<div class="mtf-row"><div><strong>15 MIN</strong><small>EMA 9 '+money(higher.ema_9)+' · EMA 21 '+money(higher.ema_21)+'</small></div><strong>' + higher.signal.replace("_SETUP","")+'</strong></div>':"";
  }else setText("mtf-summary","Higher timeframe data unavailable.");
  const failed=results.filter(r=>r.status==="rejected");
  if(failed.length===0)setConnection("ACCOUNT CONNECTED · PAPER",true);
  else setConnection((account.status==="fulfilled"?"PARTIAL DATA · ":"API ERROR · ")+failed.map(r=>r.reason.message).join(" | "));
}
const timeframeControl=byId("timeframe");
if(timeframeControl)timeframeControl.addEventListener("change",()=>{selectedTimeframe=timeframeControl.value;refresh().catch(e=>setConnection("Dashboard error: "+e.message));});
if("serviceWorker" in navigator){addEventListener("load",()=>navigator.serviceWorker.register("./sw.js").catch(e=>console.warn("Service worker:",e)));}
refresh().catch(error=>setConnection("Dashboard error: "+error.message));
setInterval(()=>refresh().catch(error=>setConnection("Dashboard error: "+error.message)),30000);

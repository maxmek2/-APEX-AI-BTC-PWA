const API=window.APEX_API_BASE||"https://apex-ai-btc-pwa.onrender.com/api";
let selectedTimeframe="5Min",monitorPaused=false,monitorStopped=false,refreshTimer=null;
const labels={"1Min":"1m","5Min":"5m","15Min":"15m","1Hour":"1h"};
const $=id=>document.getElementById(id);
const money=v=>Number.isFinite(Number(v))?new Intl.NumberFormat("en-US",{style:"currency",currency:"USD",maximumFractionDigits:2}).format(Number(v)):"—";
const num=v=>Number.isFinite(Number(v))?Number(v):null;
function text(id,value){const e=$(id);if(e)e.textContent=value;}
function paperHeaders(path,extra={}){const headers={Accept:"application/json",...extra};if(path.includes("/paper/")){const token=sessionStorage.getItem("apexPaperToken")||"";if(token)headers.Authorization="Bearer "+token;}return headers;}
async function get(path){const r=await fetch(API+path,{headers:paperHeaders(path),cache:"no-store"});if(!r.ok)throw new Error("HTTP "+r.status+" "+path);return r.json();}
function setStatus(message,ok=false){text("connection",message);const e=$("connection");if(e)e.style.color=ok?"var(--green)":"#ffb17e";text("cloud-title",ok?"Robot Monitor Online":"Market Monitor");}
function ema(values,p){if(values.length<p)return values.map(()=>null);const out=Array(values.length).fill(null);let v=values.slice(0,p).reduce((a,b)=>a+b,0)/p;out[p-1]=v;const alpha=2/(p+1);for(let i=p;i<values.length;i++){v=alpha*values[i]+(1-alpha)*v;out[i]=v;}return out;}
function atr(bars,p=14){if(bars.length<=p)return null;const trs=[];for(let i=1;i<bars.length;i++){const b=bars[i],prev=bars[i-1].c;trs.push(Math.max(b.h-b.l,Math.abs(b.h-prev),Math.abs(b.l-prev)));}let v=trs.slice(0,p).reduce((a,b)=>a+b,0)/p;for(let i=p;i<trs.length;i++)v=(v*(p-1)+trs[i])/p;return v;}
function validBars(raw){return(raw||[]).map(b=>({t:b.t,o:num(b.o),h:num(b.h),l:num(b.l),c:num(b.c),v:num(b.v)||0})).filter(b=>[b.o,b.h,b.l,b.c].every(Number.isFinite)).sort((a,b)=>Date.parse(a.t)-Date.parse(b.t));}
function calcSignal(bars){if(bars.length<30)return null;const closes=bars.map(b=>b.c),e9=ema(closes,9).at(-1),e21=ema(closes,21).at(-1),last=closes.at(-1),vol=atr(bars);let signal="WAIT";if(e9>e21&&last>e9)signal="LONG_SETUP";else if(e9<e21&&last<e9)signal="SHORT_SETUP";return{signal,ema_9:e9,ema_21:e21,last_close:last,atr_14:vol,last_bar_time:bars.at(-1).t};}
function renderChart(bars){
 const svg=$("price-chart");if(!svg)return;if(!bars.length){svg.innerHTML="";text("chart-meta","No valid OHLC candles");return;}
 const closes=bars.map(b=>b.c),e9=ema(closes,9),e21=ema(closes,21),vol=atr(bars),left=34,right=875,top=44,bottom=305,vTop=332,vBottom=402;
 const lo=Math.min(...bars.map(b=>b.l),...e9.filter(Number.isFinite),...e21.filter(Number.isFinite)),hi=Math.max(...bars.map(b=>b.h),...e9.filter(Number.isFinite),...e21.filter(Number.isFinite));
 const pad=(hi-lo)*.1||1,min=lo-pad,max=hi+pad,y=v=>bottom-(v-min)/(max-min)*(bottom-top),step=(right-left)/bars.length,w=Math.max(2,Math.min(10,step*.62));
 const maxVol=Math.max(1,...bars.map(b=>b.v)),volHeight=b=>Math.max(1,(b.v/maxVol)*(vBottom-vTop));
 const grid=[top,(top+bottom)/2,bottom].map(yy=>'<line x1="24" y1="'+yy+'" x2="970" y2="'+yy+'" stroke="#23374d"/><text x="980" y="'+(yy+4)+'" fill="#9bacc0" font-size="11" text-anchor="end">'+(max-(yy-top)/(bottom-top)*(max-min)).toFixed(0)+'</text>').join("");
 const candles=bars.map((b,i)=>{const x=left+step*(i+.5),col=b.c>=b.o?"#35d49a":"#ff6878",by=Math.min(y(b.o),y(b.c)),bh=Math.max(1.5,Math.abs(y(b.o)-y(b.c)));return '<g stroke="'+col+'" fill="'+col+'"><line x1="'+x+'" y1="'+y(b.h)+'" x2="'+x+'" y2="'+y(b.l)+'" stroke-width="1.3"/><rect x="'+(x-w/2)+'" y="'+by+'" width="'+w+'" height="'+bh+'" rx="0.7"/></g>';}).join("");
 const line=arr=>arr.map((v,i)=>v==null?"":(i?"L ":"M ")+(left+step*(i+.5)).toFixed(1)+" "+y(v).toFixed(1)).filter(Boolean).join(" ");
 const volumes=bars.map((b,i)=>{const x=left+step*(i+.5),col=b.c>=b.o?"#238c78":"#9b4a61";return '<rect x="'+(x-w/2)+'" y="'+(vBottom-volHeight(b))+'" width="'+w+'" height="'+volHeight(b)+'" fill="'+col+'" opacity=".8"/>';}).join("");
 let markers="";
 for(let i=1;i<bars.length;i++){if(e9[i-1]==null||e21[i-1]==null||e9[i]==null||e21[i]==null)continue;const crossUp=e9[i-1]<=e21[i-1]&&e9[i]>e21[i],crossDown=e9[i-1]>=e21[i-1]&&e9[i]<e21[i];if(crossUp||crossDown){const x=left+step*(i+.5),yy=crossUp?y(bars[i].l)+15:y(bars[i].h)-15,col=crossUp?"#20d995":"#ff6878",label=crossUp?"BUY SETUP":"SELL WATCH";markers+='<g><rect x="'+(x-29)+'" y="'+(yy-10)+'" width="58" height="17" rx="5" fill="'+col+'"/><text x="'+x+'" y="'+(yy+2)+'" text-anchor="middle" font-size="9" font-weight="700" fill="#07111c">'+label+'</text></g>';}}
 svg.innerHTML='<g>'+grid+'</g>'+volumes+candles+'<path d="'+line(e9)+'" fill="none" stroke="#f5b84d" stroke-width="2.4"/><path d="'+line(e21)+'" fill="none" stroke="#368fff" stroke-width="2.4"/>'+markers+'<g fill="#9bacc0" font-size="11"><text x="25" y="20">BTC/USD · '+(labels[selectedTimeframe]||"5m")+'</text><text x="25" y="425">TICK VOLUME · NOT EXCHANGE VOLUME</text></g>';
 text("chart-time-label",labels[selectedTimeframe]||"5m");text("chart-meta",bars.length+" candles · Last "+new Date(bars.at(-1).t).toLocaleTimeString()+" · ATR 14 "+(vol==null?"—":money(vol)));
 text("atr-mini",vol==null?"—":money(vol));
}
function renderPositions(positions){
 text("position-count",String(positions.length));
 const el=$("positions-list");if(!el)return;
 if(!positions.length){el.innerHTML='<div class="empty-state">No open paper positions.</div>';return;}
 el.innerHTML=positions.map(p=>{const pl=num(p.unrealized_pl)||0,positive=pl>=0;return '<article class="position-row"><div class="position-main"><strong><i class="position-dot"></i>'+p.symbol+' <span class="side-tag">'+String(p.side||"position").toUpperCase()+'</span></strong><small>Qty: '+p.qty+' · Market value: '+money(p.market_value)+'</small><small>Entry: '+money(p.avg_entry_price)+'</small></div><div class="position-right"><strong class="'+(positive?"check-pass":"check-fail")+'">'+(positive?"+":"")+money(pl)+'</strong><small>Unrealized P&amp;L</small></div></article>';}).join("");
}
function renderQuality(signal,bars){if(!signal||bars.length<2){text("entry-score","—");text("entry-quality-label","WAITING FOR DATA");return;}const a=bars.at(-1),p=bars.at(-2),long=signal.signal==="LONG_SETUP",short=signal.signal==="SHORT_SETUP";const tests=[["EMA trend alignment",35,long?signal.ema_9>signal.ema_21:short&&signal.ema_9<signal.ema_21],["Price vs EMA 9",25,long?signal.last_close>signal.ema_9:short&&signal.last_close<signal.ema_9],["Last-close momentum",20,long?a.c>p.c:short&&a.c<p.c],["Latest candle direction",10,long?a.c>a.o:short&&a.c<a.o],["ATR 14 available",10,signal.atr_14>0]];const score=tests.reduce((s,t)=>s+(t[2]?t[1]:0),0);text("entry-score",score+"/100");text("entry-quality-label",score>=85?"STRONG ALIGNMENT":score>=70?"GOOD ALIGNMENT":score>=50?"MIXED ALIGNMENT":"WEAK ALIGNMENT");text("entry-quality-detail","Rule-alignment heuristic only; not a win probability or entry instruction.");$("entry-quality-checks").innerHTML=tests.map(t=>'<div class="check-row"><span>'+t[0]+' · '+t[1]+' pts</span><strong class="'+(t[2]?"check-pass":"check-fail")+'">'+(t[2]?"PASS":"NO POINTS")+'</strong></div>').join("");}
function aggregate4h(hourly){const grouped=new Map();for(const b of hourly){const d=new Date(b.t),bucket=Math.floor(d.getTime()/(4*3600000))*4*3600000,key=new Date(bucket).toISOString();if(!grouped.has(key))grouped.set(key,[]);grouped.get(key).push(b);}return [...grouped.entries()].map(([t,a])=>({t,o:a[0].o,h:Math.max(...a.map(x=>x.h)),l:Math.min(...a.map(x=>x.l)),c:a.at(-1).c,v:a.reduce((s,x)=>s+x.v,0)})).filter(x=>{const a=grouped.get(x.t);return a.length===4;});}
async function refresh(){
 if(monitorStopped||monitorPaused)return;
 setStatus("Refreshing market and paper account…");
 const results=await Promise.allSettled([get("/account"),get("/positions"),get("/market/btc"),get("/market/bars?timeframe="+selectedTimeframe+"&limit=100"),get("/market/bars?timeframe=15Min&limit=100"),get("/market/bars?timeframe=1Hour&limit=500")]);
 const acc=results[0];if(acc.status==="fulfilled"){const a=acc.value;text("equity",money(a.equity));text("cash",money(a.cash));text("buying",money(a.buying_power));text("account-status",String(a.status||"ACTIVE").toUpperCase());text("portfolio-value",money(a.portfolio_value));}
 else text("account-status","ERROR");
 if(results[1].status==="fulfilled")renderPositions(results[1].value);else $("positions-list").textContent="Position data unavailable: "+results[1].reason.message;
 if(results[2].status==="fulfilled"){const m=results[2].value;text("price",m.price==null?"—":money(m.price));text("updated",m.timestamp?"Last trade "+new Date(m.timestamp).toLocaleString():"Latest trade unavailable");}else text("updated","Market error: "+results[2].reason.message);
 let bars=[];if(results[3].status==="fulfilled"){bars=validBars(results[3].value.bars);renderChart(bars);if(bars.length>1){const diff=bars.at(-1).c-bars[0].c,pct=diff/bars[0].c*100;text("price-change",(diff>=0?"+":"")+money(diff)+" ("+(pct>=0?"+":"")+pct.toFixed(2)+"% over displayed candles)");}}else text("chart-meta","Chart error: "+results[3].reason.message);
 const sig=calcSignal(bars);if(sig){const names={LONG_SETUP:"LONG SETUP",SHORT_SETUP:"SHORT SETUP",WAIT:"WAIT"};text("signal-value",names[sig.signal]);text("signal-mini",names[sig.signal]);text("trend-value",sig.ema_9>sig.ema_21?"Bullish":sig.ema_9<sig.ema_21?"Bearish":"Neutral");text("signal-detail","EMA 9: "+money(sig.ema_9)+" · EMA 21: "+money(sig.ema_21)+" · ATR 14: "+money(sig.atr_14));text("signal-time","Last candle "+new Date(sig.last_bar_time).toLocaleString());}else{text("signal-value","INSUFFICIENT DATA");text("signal-mini","WAIT");text("signal-detail","At least 30 valid candles are required.");text("trend-value","—");text("signal-time","");}renderQuality(sig,bars);
 const mtf=[];for(const [idx,label] of [[4,"15 MIN"],[5,"1 HOUR"]]){if(results[idx].status==="fulfilled"){const h=calcSignal(validBars(results[idx].value.bars));mtf.push({label,signal:h});}}
 if(results[5].status==="fulfilled"){const h4=calcSignal(aggregate4h(validBars(results[5].value.bars)));mtf.push({label:"4 HOUR",signal:h4});}
 text("mtf-summary",mtf.filter(x=>x.signal&&x.signal.signal===sig?.signal).length+" higher timeframes align with current "+(sig?.signal||"WAIT")+" direction.");
 $("mtf-checks").innerHTML=mtf.map(x=>'<div class="mtf-row"><div><strong>'+x.label+'</strong><small>'+(x.signal?"EMA 9 "+money(x.signal.ema_9)+" · EMA 21 "+money(x.signal.ema_21):"Not enough complete candles")+'</small></div><strong class="'+(x.signal&&x.signal.signal!=="WAIT"?"check-pass":"muted")+'">'+(x.signal?x.signal.signal.replace("_SETUP",""):"NOT ENOUGH DATA")+'</strong></div>').join("");
 const failures=results.filter(x=>x.status==="rejected");setStatus(failures.length?"PARTIAL DATA · "+failures.map(x=>x.reason.message).join(" · "):"ACCOUNT CONNECTED · PAPER",failures.length===0);
}
async function runBacktest(){const out=$("backtest-result");out.textContent="Running read-only historical simulation…";try{const r=await get("/backtest?timeframe="+selectedTimeframe+"&limit=10000&starting_equity=100&notional_usd=10"),m=r.metrics;if(!m){out.textContent="Backtest status: "+r.status+" · Bars: "+r.bars_used;return;}out.innerHTML='<div class="backtest-grid"><div><small>Ending equity</small><b>'+money(m.ending_equity_usd)+'</b></div><div><small>Net P&amp;L</small><b class="'+(m.net_pnl_usd>=0?"check-pass":"check-fail")+'">'+money(m.net_pnl_usd)+'</b></div><div><small>Trades</small><b>'+m.trades+'</b></div><div><small>Win rate</small><b>'+m.win_rate_percent+'%</b></div><div><small>Gross PF</small><b>'+(m.gross_profit_factor??"—")+'</b></div><div><small>Net PF</small><b>'+(m.net_profit_factor??"—")+'</b></div><div><small>Max drawdown</small><b>'+m.max_drawdown_percent+'%</b></div></div><small class="muted">Historical simulation · '+r.bars_used+' / '+r.requested_bars+' requested candles · '+(r.history_complete_for_request?"requested sample complete":"partial history")+(r.has_more_data?" · older data available":"")+(r.period?" · "+r.period.from+" to "+r.period.to:"")+'</small>'; }catch(e){out.textContent="Backtest unavailable: "+e.message;}}
function setupControls(){
 const tokenInput=$("paper-api-token");
 if(tokenInput){tokenInput.value=sessionStorage.getItem("apexPaperToken")||"";tokenInput.addEventListener("change",()=>{sessionStorage.setItem("apexPaperToken",tokenInput.value.trim());loadPaperEngineStatus();});}
 const tf=$("timeframe");tf.addEventListener("change",()=>{selectedTimeframe=tf.value;text("signal-timeframe",labels[selectedTimeframe].toUpperCase());refresh().catch(e=>setStatus(e.message));});
 $("run-backtest").addEventListener("click",runBacktest);
 $("pause-monitor").addEventListener("click",()=>{monitorPaused=!monitorPaused;$("pause-monitor").textContent=monitorPaused?"▶ Resume Monitor":"Ⅱ Pause Monitor";if(!monitorPaused)refresh().catch(e=>setStatus(e.message));});
 $("stop-monitor").addEventListener("click",()=>{monitorStopped=true;monitorPaused=false;if(refreshTimer)clearInterval(refreshTimer);$("stop-monitor").textContent="■ Monitoring Stopped";$("pause-monitor").disabled=true;setStatus("MONITORING STOPPED");});
 $("view-report").addEventListener("click",()=>{location.hash="backtest-panel";runBacktest();});
 document.querySelectorAll(".tabs a").forEach(a=>a.addEventListener("click",()=>{document.querySelectorAll(".tabs a").forEach(x=>x.classList.remove("active"));a.classList.add("active");}));
}
setupControls();if("serviceWorker"in navigator)addEventListener("load",()=>navigator.serviceWorker.register("./sw.js").catch(()=>{}));
refresh().catch(e=>setStatus("Dashboard error: "+e.message));refreshTimer=setInterval(()=>refresh().catch(e=>setStatus(e.message)),30000);


async function loadPaperEngineStatus(){
 const state=$("paper-engine-state"),note=$("paper-engine-note");
 if(!state)return;
 try{
  const s=await get("/paper/status");
  state.textContent=s.order_submission_enabled?"EXECUTION AVAILABLE":"PREVIEW ONLY · LOCKED";
  if(note)note.textContent=s.reason||"Paper-only execution safety status.";
 }catch(e){state.textContent="STATUS UNAVAILABLE";if(note)note.textContent=e.message;}
}
async function previewPaperTrade(){
 const out=$("paper-preview-result"),btn=$("paper-preview");
 if(!out||!btn)return;
 btn.disabled=true;out.textContent="Checking paper account, open positions, signal and risk limits…";
 try{
  const response=await fetch(API+"/paper/preview",{method:"POST",headers:paperHeaders("/paper/preview",{"Content-Type":"application/json"}),body:JSON.stringify({timeframe:selectedTimeframe,risk_percent:0.5,max_notional_usd:10,stop_atr_multiple:1.5,reward_risk:2})});
  const data=await response.json();
  if(!response.ok)throw new Error(data.detail||"HTTP "+response.status);
  if(!data.approved){out.textContent="NO TRADE · "+data.signal+" · "+data.reason;return;}
  out.innerHTML='<div class="backtest-grid"><div><small>Reference entry</small><b>'+money(data.reference_entry_price)+'</b></div><div><small>Proposed size</small><b>'+money(data.proposed_notional_usd)+'</b></div><div><small>Risk budget</small><b>'+money(data.risk_budget_usd)+'</b></div><div><small>ATR stop</small><b>'+money(data.proposed_stop_price)+'</b></div><div><small>Target reference</small><b>'+money(data.proposed_take_profit_price)+'</b></div><div><small>Execution</small><b>NOT SENT</b></div></div><small class="muted">Preview only · '+data.timeframe+' · '+data.signal+' · '+data.warning+'</small>';
 }catch(e){out.textContent="Preview unavailable: "+e.message;}
 finally{btn.disabled=false;}
}
const paperPreviewButton=$("paper-preview");
if(paperPreviewButton)paperPreviewButton.addEventListener("click",previewPaperTrade);
loadPaperEngineStatus();

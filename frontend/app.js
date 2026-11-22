const API=window.APEX_API_BASE||"https://apex-ai-btc-pwa.onrender.com/api";
let selectedTimeframe="5Min",monitorPaused=false,monitorStopped=false,refreshTimer=null;
const labels={"1Min":"1m","5Min":"5m","15Min":"15m","1Hour":"1h"};
const $=id=>document.getElementById(id);
const money=v=>Number.isFinite(Number(v))?new Intl.NumberFormat("en-US",{style:"currency",currency:"USD",maximumFractionDigits:2}).format(Number(v)):"—";
const num=v=>Number.isFinite(Number(v))?Number(v):null;
function text(id,value){const e=$(id);if(e)e.textContent=value;}
function getPaperToken(){return localStorage.getItem("apexPaperToken")||sessionStorage.getItem("apexPaperToken")||"";}
function savePaperToken(value,remember){const token=String(value||"").trim();if(token){sessionStorage.setItem("apexPaperToken",token);if(remember)localStorage.setItem("apexPaperToken",token);else localStorage.removeItem("apexPaperToken");}else{sessionStorage.removeItem("apexPaperToken");localStorage.removeItem("apexPaperToken");}}
function paperHeaders(path,extra={}){const headers={Accept:"application/json",...extra};if(path.includes("/paper/")||path==="/account"||path==="/positions"){const token=getPaperToken();if(token)headers.Authorization="Bearer "+token;}return headers;}
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
function escapeLedger(value){return String(value??"—").replace(/[&<>"']/g,ch=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));}
function ledgerTime(value){if(!value)return "—";const d=new Date(value);return Number.isNaN(d.getTime())?escapeLedger(value):escapeLedger(d.toLocaleString());}
function ledgerMetric(label,value,positive){const cls=positive==null?"":(positive?"check-pass":"check-fail");return '<div><small>'+escapeLedger(label)+'</small><b class="'+cls+'">'+escapeLedger(value)+'</b></div>';}
function ledgerTable(rows,label){
 const items=Array.isArray(rows)?rows:[],shown=items.slice(-12);
 if(!items.length)return '<p class="muted">'+escapeLedger(label)+': no closed simulated trades in this segment.</p>';
 const body=shown.map(t=>{const pnl=Number(t.net_pnl_usd);return '<tr><td>'+ledgerTime(t.entry_time)+'</td><td>'+ledgerTime(t.exit_time)+'</td><td>'+money(t.entry_price)+'</td><td>'+money(t.exit_price)+'</td><td>'+escapeLedger(t.exit_reason)+'</td><td>'+money(t.estimated_fees_usd)+'</td><td>'+money(t.estimated_slippage_usd)+'</td><td class="'+(Number.isFinite(pnl)&&pnl>=0?"check-pass":"check-fail")+'">'+money(t.net_pnl_usd)+'</td></tr>';}).join("");
 return '<details class="ledger-details"><summary>'+escapeLedger(label)+' · '+items.length+' trades'+(items.length>shown.length?' · showing latest '+shown.length:'')+'</summary><div class="ledger-table-wrap"><table class="ledger-table"><thead><tr><th>Entry time</th><th>Exit time</th><th>Entry</th><th>Exit</th><th>Reason</th><th>Fees</th><th>Slippage</th><th>Net P&amp;L</th></tr></thead><tbody>'+body+'</tbody></table></div></details>';
}
async function runStage51Ledger(){
 const out=$("stage51-ledger-result"),btn=$("run-stage51");if(!out||!btn)return;
 btn.disabled=true;out.textContent="Fetching BTC/USD history and replaying frozen research variants… This is read-only.";
 try{
  const data=await get("/research/stage5-1/run?timeframe=5Min&limit=10000&train_fraction=0.60&starting_equity=100&notional_usd=10&fee_rate=0.0025&slippage_bps=5&minimum_trades=30");
  if(!data.variants){out.textContent="Research status: "+escapeLedger(data.result||data.status||"UNAVAILABLE")+" · Bars: "+escapeLedger(data.bars_used??"—");return;}
  const cards=Object.entries(data.variants).map(([name,item])=>{
   const tr=item.training_metrics||{},ho=item.holdout_metrics||{};
   const status=item.validated?"VALIDATED":"NOT VALIDATED";
   const cardsHtml='<div class="backtest-grid">'+
    ledgerMetric("Training trades",tr.trades??0)+ledgerMetric("Training net P&L",money(tr.net_pnl_usd),Number(tr.net_pnl_usd)>=0)+ledgerMetric("Training net PF",tr.net_profit_factor??tr.profit_factor??"—")+
    ledgerMetric("Holdout trades",ho.trades??0)+ledgerMetric("Holdout net P&L",money(ho.net_pnl_usd),Number(ho.net_pnl_usd)>=0)+ledgerMetric("Holdout net PF",ho.net_profit_factor??ho.profit_factor??"—")+
    ledgerMetric("Holdout win rate",Number.isFinite(Number(ho.win_rate_percent))?Number(ho.win_rate_percent).toFixed(2)+"%":"—")+
    '</div>';
   return '<article class="ledger-variant"><div class="between"><strong>'+escapeLedger(name.replaceAll("_"," "))+'</strong><span class="tag '+(item.validated?"check-pass":"neutral")+'">'+status+'</span></div>'+cardsHtml+
    '<small class="muted">Training gate: '+(item.training_gate_passed?"PASS":"FAIL")+' · Holdout gate: '+(item.holdout_gate_passed?"PASS":"FAIL")+' · Holdout entries after split: '+(item.holdout_entries_after_split?"YES":"NO")+'</small>'+
    ledgerTable(item.training_trades,"Training ledger")+ledgerTable(item.holdout_trades,"Holdout ledger")+'</article>';
  }).join("");
  const meta='<strong class="'+(data.result==="RESEARCH_GATE_PASSED"?"check-pass":"check-fail")+'">'+escapeLedger(data.result)+'</strong><p>'+escapeLedger(data.symbol)+' · '+escapeLedger(data.timeframe)+' · '+escapeLedger(data.bars_used)+'/'+escapeLedger(data.requested_bars)+' candles · '+escapeLedger(data.validated_variant_count)+'/4 variants validated</p><small class="muted">'+ledgerTime(data.period?.from)+' → '+ledgerTime(data.period?.to)+' · Train '+Math.round(Number(data.train_fraction)*100)+'% / holdout '+Math.round((1-Number(data.train_fraction))*100)+'% · $100 start · $10 notional · 0.25% fee/side · 5 bps slippage/side</small>';
  out.innerHTML=meta+cards+'<small class="muted">Read-only Alpaca historical market-data GET. No account/order/position API calls; no order submitted; no execution state changed. Simulated OHLC trades are not actual broker fills.</small>';
 }catch(e){out.textContent="Stage 5.2 ledger unavailable: "+e.message;}
 finally{btn.disabled=false;}
}

async function runStage53(){
 const out=$("stage53-result"),btn=$("run-stage53");if(!out||!btn)return;
 btn.disabled=true;out.textContent="Fetching BTC/USD history, diagnosing baseline trades and evaluating the training-only grid…";
 try{
  const data=await get("/research/stage5-3/run?timeframe=5Min&limit=10000&train_fraction=0.60&starting_equity=100&notional_usd=10&fee_rate=0.0025&slippage_bps=5&minimum_training_trades=30&max_training_drawdown_percent=5");
  if(data.result==="INSUFFICIENT_DATA"){out.textContent="Insufficient data: "+escapeLedger(data.bars_used)+" / 3000 minimum candles.";return;}
  const opt=data.optimization||{},base=data.baseline_diagnostics||{},train=base.training_metrics||{},hold=base.holdout_metrics||{};
  const reasonRows=(diag)=>Object.entries(diag?.exit_reason_breakdown||{}).map(([name,v])=>'<tr><td>'+escapeLedger(name)+'</td><td>'+escapeLedger(v.trades)+'</td><td>'+escapeLedger(v.win_rate_percent)+'%</td><td>'+money(v.net_pnl_usd)+'</td></tr>').join("");
  const candidateRows=(opt.top_training_candidates||[]).map((c,i)=>{const p=c.parameters||{},m=c.training_metrics||{};return '<tr><td>'+(i+1)+'</td><td>'+escapeLedger(p.relative_volume_threshold)+' / '+escapeLedger(p.pullback_atr)+' / '+escapeLedger(p.pullback_bars)+'</td><td>'+escapeLedger(p.stop_atr_multiple)+' / '+escapeLedger(p.reward_risk)+'</td><td>'+escapeLedger(m.trades)+'</td><td>'+money(m.net_pnl_usd)+'</td><td>'+escapeLedger(m.net_profit_factor??"—")+'</td><td>'+escapeLedger(m.max_drawdown_percent)+'%</td><td class="'+(c.training_gate_passed?"check-pass":"check-fail")+'">'+(c.training_gate_passed?"PASS":"FAIL")+'</td></tr>';}).join("");
  const selected=opt.selected_parameters?'<p><strong>Selected training candidate:</strong> '+escapeLedger(JSON.stringify(opt.selected_parameters))+'</p>':'<p class="check-fail"><strong>No candidate passed all training gates.</strong> Holdout was not used to select or rescue a candidate.</p>';
  const holdout=opt.holdout?'<h4>One-time untouched holdout check</h4><div class="backtest-grid">'+ledgerMetric("Holdout trades",opt.holdout.metrics?.trades??0)+ledgerMetric("Holdout net P&L",money(opt.holdout.metrics?.net_pnl_usd),Number(opt.holdout.metrics?.net_pnl_usd)>0)+ledgerMetric("Holdout net PF",opt.holdout.metrics?.net_profit_factor??"—")+ledgerMetric("Holdout max drawdown",String(opt.holdout.metrics?.max_drawdown_percent??"—")+"%")+ledgerMetric("Boundary valid",opt.holdout.entries_after_split?"YES":"NO",!!opt.holdout.entries_after_split)+ledgerMetric("Holdout gate",opt.holdout.gate_passed?"PASS":"FAIL",!!opt.holdout.gate_passed)+'</div>'+ledgerTable(opt.holdout.trades,"Selected candidate holdout ledger"):'<p class="muted">Holdout not evaluated because no training-qualified candidate exists.</p>';
  const diag=(label,metrics,d)=>'<h4>'+label+'</h4><div class="backtest-grid">'+ledgerMetric("Trades",metrics.trades??0)+ledgerMetric("Net P&L",money(metrics.net_pnl_usd),Number(metrics.net_pnl_usd)>0)+ledgerMetric("Net PF",metrics.net_profit_factor??"—")+ledgerMetric("Win rate",String(metrics.win_rate_percent??0)+"%")+ledgerMetric("Max drawdown",String(metrics.max_drawdown_percent??0)+"%")+ledgerMetric("Stop-loss exits",Object.entries(d?.exit_reason_breakdown||{}).filter(([k])=>k.startsWith("STOP_LOSS")).reduce((n,[,v])=>n+Number(v.trades||0),0))+'</div><div class="ledger-table-wrap"><table class="ledger-table"><thead><tr><th>Exit reason</th><th>Trades</th><th>Win rate</th><th>Net P&amp;L</th></tr></thead><tbody>'+reasonRows(d)+'</tbody></table></div>';
  const meta='<strong class="'+(opt.qualified_training_candidates>0?"check-pass":"check-fail")+'">'+escapeLedger(data.result)+'</strong><p>'+escapeLedger(data.symbol)+' · '+escapeLedger(data.bars_used)+'/'+escapeLedger(data.requested_bars)+' candles · '+escapeLedger(opt.grid_size)+' candidates · '+escapeLedger(opt.qualified_training_candidates)+' training-qualified</p><small class="muted">'+ledgerTime(data.period?.from)+' → '+ledgerTime(data.period?.to)+' · Train '+Math.round(Number(data.split?.train_fraction)*100)+'% / untouched holdout '+Math.round((1-Number(data.split?.train_fraction))*100)+'%</small>';
  const table='<h4>Top training-only candidates</h4><div class="ledger-table-wrap"><table class="ledger-table"><thead><tr><th>#</th><th>Volume / pullback ATR / bars</th><th>Stop ATR / R:R</th><th>Trades</th><th>Net P&amp;L</th><th>Net PF</th><th>Max DD</th><th>Gate</th></tr></thead><tbody>'+candidateRows+'</tbody></table></div>';
  out.innerHTML=meta+diag("Baseline training diagnostics",train,base.training)+diag("Baseline holdout diagnostics",hold,base.holdout)+table+selected+holdout+'<small class="muted">Selection uses training data only. Holdout is evaluated at most once. Fees/slippage are assumptions, not actual fills. Read-only market-data GET; no account/order/position calls; no order submitted; automated execution remains disabled.</small>';
 }catch(e){out.textContent="Stage 5.3 unavailable: "+e.message;}
 finally{btn.disabled=false;}
}




async function runStage56(){
 const out=$("stage56-result"),btn=$("run-stage56");if(!out||!btn)return;
 btn.disabled=true;out.textContent="Fetching BTC/USD M5 history and analyzing only the chronological training segment…";
 try{
  const data=await get("/research/stage5-6/run?timeframe=5Min&limit=30000&starting_equity=100&notional_usd=10&fee_rate=0.0025&slippage_bps=5&train_fraction=0.60");
  if(data.status==="INSUFFICIENT_DATA"){out.textContent="Insufficient history: "+escapeLedger(data.bars_used)+" / "+escapeLedger(data.minimum_bars)+" minimum bars.";return;}
  const m=data.training?.metrics||{},d=data.training?.diagnostics||{};
  const metricGrid='<div class="backtest-grid">'+ledgerMetric("Training bars",data.training_bars??0)+ledgerMetric("Trades",m.trades??0)+ledgerMetric("Gross P&L",money(m.gross_pnl_usd),Number(m.gross_pnl_usd)>0)+ledgerMetric("Fees",money(m.estimated_fees_usd))+ledgerMetric("Slippage",money(m.estimated_slippage_usd))+ledgerMetric("Net P&L",money(m.net_pnl_usd),Number(m.net_pnl_usd)>0)+ledgerMetric("Net profit factor",m.net_profit_factor??"—")+ledgerMetric("Win rate",String(m.win_rate_percent??0)+"%")+ledgerMetric("Max closed DD",String(m.max_drawdown_percent??0)+"%")+ledgerMetric("Longest losing streak",d.longest_consecutive_losing_trades??0)+ledgerMetric("Average hold",d.average_holding_minutes==null?"—":String(d.average_holding_minutes)+" min")+ledgerMetric("Fee burden",d.fee_burden_percent_of_absolute_gross_pnl==null?"—":String(d.fee_burden_percent_of_absolute_gross_pnl)+"%")+'</div>';
  const groups=(title,obj)=>'<h4>'+title+'</h4><div class="ledger-table-wrap"><table class="ledger-table"><thead><tr><th>Group</th><th>Trades</th><th>Win %</th><th>Net P&L</th><th>Net PF</th></tr></thead><tbody>'+Object.entries(obj||{}).map(([key,v])=>'<tr><td>'+escapeLedger(key)+'</td><td>'+escapeLedger(v.trades)+'</td><td>'+escapeLedger(v.win_rate_percent)+'%</td><td>'+money(v.net_pnl_usd)+'</td><td>'+escapeLedger(v.net_profit_factor??"—")+'</td></tr>').join("")+'</tbody></table></div>';
  const hypotheses=(data.failure_hypotheses||[]).map(x=>'<li>'+escapeLedger(x)+'</li>').join("");
  const trades=(data.training?.trade_ledger||[]).map(t=>'<tr><td>'+ledgerTime(t.entry_time)+'</td><td>'+ledgerTime(t.exit_time)+'</td><td>'+escapeLedger(t.exit_reason)+'</td><td>'+escapeLedger(t.entry_regime)+'</td><td>'+escapeLedger(t.holding_minutes??"—")+'</td><td>'+money(t.net_pnl_usd)+'</td></tr>').join("");
  out.innerHTML='<strong class="check-fail">'+escapeLedger(data.status)+'</strong><p>BTC/USD · '+escapeLedger(data.bars_received)+' bars received · '+escapeLedger(data.training_bars)+' training bars · Holdout: SEALED</p><small class="muted">'+ledgerTime(data.training_period?.from)+' → '+ledgerTime(data.training_period?.to)+' · Fixed Stage 4.4 baseline; no optimization</small>'+metricGrid+groups("Exit reason attribution",d.exit_reason_attribution)+groups("Entry regime attribution",d.entry_regime_attribution)+'<h4>Failure hypotheses to investigate</h4><ul>'+hypotheses+'</ul><h4>Training ledger · latest '+(data.training?.trade_ledger||[]).length+' trades</h4><div class="ledger-table-wrap"><table class="ledger-table"><thead><tr><th>Entry</th><th>Exit</th><th>Reason</th><th>Regime</th><th>Hold min</th><th>Net</th></tr></thead><tbody>'+trades+'</tbody></table></div><small class="muted">Holdout status: '+escapeLedger(data.holdout?.status)+' · Holdout accessed: NO · Strategy selection: NO · No account/order/position API calls · No order submitted · Auto Entry remains OFF. Findings are descriptive hypotheses, not proof of causation or profitability.</small>';
 }catch(e){out.textContent="Stage 5.6 analysis unavailable: "+e.message;}
 finally{btn.disabled=false;}
}

async function runStage511(){
 const out=$("stage511-result"),btn=$("run-stage511");if(!out||!btn)return;
 btn.disabled=true;out.textContent="Inspecting stop-loss excursions and pre-entry market context on training data only…";
 try{
  const data=await get("/research/stage5-11/run?timeframe=5Min&limit=30000&starting_equity=100&notional_usd=10&fee_rate=0.0025&slippage_bps=5&train_fraction=0.60");
  if(data.status==="INSUFFICIENT_DATA"){out.textContent="Insufficient history: "+escapeLedger(data.bars_used)+" / "+escapeLedger(data.minimum_bars)+" minimum bars.";return;}
  if(data.status==="DATA_INTEGRITY_FAILED"){out.textContent="Data integrity failed. Stop-loss diagnostics were not run.";return;}
  const c=data.candidate||{},b=data.baseline||{},d=c.diagnostics||{},s=d.summary||{},bs=(b.diagnostics||{}).summary||{};
  const grid='<div class="backtest-grid">'+
   ledgerMetric("Training bars",data.training_bars??0)+
   ledgerMetric("Candidate trades",s.trades??0)+
   ledgerMetric("Stop-loss trades",s.stop_loss_trades??0)+
   ledgerMetric("Stop-loss share",String(s.stop_loss_share_percent??0)+"%")+
   ledgerMetric("Early adverse stops (≤3 bars)",s.early_adverse_stop_loss_within_3_bars??0)+
   ledgerMetric("Stops later recovering above entry",s.stop_loss_recovered_above_entry_within_3_6_or_12_bars??0)+
   ledgerMetric("Median stop-loss MAE",s.median_stop_loss_mae_r==null?"—":String(s.median_stop_loss_mae_r)+" R")+
   ledgerMetric("Median MFE",s.median_mfe_r==null?"—":String(s.median_mfe_r)+" R")+
   ledgerMetric("Median MAE",s.median_mae_r==null?"—":String(s.median_mae_r)+" R")+
   ledgerMetric("Candidate net P&L",money(c.metrics?.net_pnl_usd),Number(c.metrics?.net_pnl_usd)>0)+
   ledgerMetric("Baseline stop-loss share",String(bs.stop_loss_share_percent??0)+"%")+
   ledgerMetric("Baseline net P&L",money(b.metrics?.net_pnl_usd),Number(b.metrics?.net_pnl_usd)>0)+'</div>';
  const groupTable=(title,obj)=>'<h4>'+title+'</h4><div class="ledger-table-wrap"><table class="ledger-table"><thead><tr><th>Pre-entry regime</th><th>Trades</th><th>Stops</th><th>Win %</th><th>Net P&amp;L</th><th>Median MFE R</th><th>Median MAE R</th></tr></thead><tbody>'+
   Object.entries(obj||{}).map(([k,v])=>'<tr><td>'+escapeLedger(k)+'</td><td>'+escapeLedger(v.trades)+'</td><td>'+escapeLedger(v.stop_loss_trades)+'</td><td>'+escapeLedger(v.win_rate_percent)+'%</td><td>'+money(v.net_pnl_usd)+'</td><td>'+escapeLedger(v.median_mfe_r??"—")+'</td><td>'+escapeLedger(v.median_mae_r??"—")+'</td></tr>').join("")+
   '</tbody></table></div>';
  const reasons='<h4>Candidate exit reasons</h4><div class="ledger-table-wrap"><table class="ledger-table"><thead><tr><th>Exit</th><th>Trades</th><th>Net P&amp;L</th><th>Median MFE R</th><th>Median MAE R</th><th>Median bars</th></tr></thead><tbody>'+
   Object.entries(d.exit_reason_attribution||{}).map(([k,v])=>'<tr><td>'+escapeLedger(k)+'</td><td>'+escapeLedger(v.trades)+'</td><td>'+money(v.net_pnl_usd)+'</td><td>'+escapeLedger(v.median_mfe_r??"—")+'</td><td>'+escapeLedger(v.median_mae_r??"—")+'</td><td>'+escapeLedger(v.median_bars_held??"—")+'</td></tr>').join("")+
   '</tbody></table></div>';
  const ledger=(d.trade_ledger||[]).slice(-30).reverse().map(x=>'<tr><td>'+escapeLedger(x.entry_time)+'</td><td>'+escapeLedger(x.exit_reason)+'</td><td>'+escapeLedger(x.hourly_trend_before_entry)+' / '+escapeLedger(x.volatility_before_entry)+'</td><td>'+escapeLedger(x.momentum_bucket_before_entry)+'</td><td>'+escapeLedger(x.bars_held)+'</td><td>'+escapeLedger(x.mfe_r??"—")+'</td><td>'+escapeLedger(x.mae_r??"—")+'</td><td>'+money(x.net_pnl_usd)+'</td></tr>').join("");
  const diagnosis='<h4>Findings to investigate</h4><ul>'+((data.diagnosis||[]).map(x=>'<li>'+escapeLedger(x)+'</li>').join(""))+'</ul>';
  out.innerHTML='<strong>'+escapeLedger(data.status)+'</strong>'+grid+
   groupTable("Candidate · pre-entry hourly trend / volatility",d.entry_regime_attribution)+
   reasons+
   groupTable("Baseline · pre-entry hourly trend / volatility",b.diagnostics?.entry_regime_attribution)+
   diagnosis+
   '<h4>Latest candidate trade diagnostics</h4><div class="ledger-table-wrap"><table class="ledger-table"><thead><tr><th>Entry</th><th>Exit</th><th>Trend / vol</th><th>Momentum</th><th>Bars</th><th>MFE R</th><th>MAE R</th><th>Net</th></tr></thead><tbody>'+ledger+'</tbody></table></div>'+
   '<small class="muted">Holdout: '+escapeLedger(data.holdout?.status||"SEALED_NOT_ACCESSED")+'. Entry features use completed pre-entry bars. MFE/MAE and post-stop recovery are descriptive outcomes, not causal proof. Stop/target settings remain frozen. No optimization, broker API calls, order submission or automated execution.</small>';
 }catch(e){out.textContent="Stage 5.11 diagnostics unavailable: "+e.message;}
 finally{btn.disabled=false;}
}

async function runStage510(){
 const out=$("stage510-result"),btn=$("run-stage510");if(!out||!btn)return;
 btn.disabled=true;out.textContent="Measuring candidate gross edge, round-trip fee burden and break-even price movement on training data only…";
 try{
  const data=await get("/research/stage5-10/run?timeframe=5Min&limit=30000&starting_equity=100&notional_usd=10&fee_rate=0.0025&slippage_bps=5&train_fraction=0.60");
  if(data.status==="INSUFFICIENT_DATA"){out.textContent="Insufficient history: "+escapeLedger(data.bars_used)+" / "+escapeLedger(data.minimum_bars)+" minimum bars.";return;}
  if(data.status==="DATA_INTEGRITY_FAILED"){out.textContent="Data integrity failed. Cost/edge diagnostics were not run.";return;}
  const c=data.candidate||{},b=data.baseline||{},p=c.cost_edge||{},s=p.summary||{},bs=(b.cost_edge||{}).summary||{};
  const grid='<div class="backtest-grid">'+
   ledgerMetric("Training bars",data.training_bars??0)+
   ledgerMetric("Candidate trades",s.trades??0)+
   ledgerMetric("Candidate gross P&L",money(s.gross_pnl_usd),Number(s.gross_pnl_usd)>0)+
   ledgerMetric("Candidate net P&L",money(s.net_pnl_usd),Number(s.net_pnl_usd)>0)+
   ledgerMetric("Candidate net PF",s.net_profit_factor??"—")+
   ledgerMetric("Gross winners",s.gross_winning_trades??0)+
   ledgerMetric("Winners erased by fees",String(s.gross_winners_erased_by_fees??0)+" ("+String(s.gross_winners_erased_share_percent??0)+"%)")+
   ledgerMetric("Median break-even move",s.median_break_even_price_move_bps==null?"—":String(s.median_break_even_price_move_bps)+" bps")+
   ledgerMetric("Median fee burden",s.median_fee_cost_r==null?"—":String(s.median_fee_cost_r)+" R")+
   ledgerMetric("Fee / positive gross",s.fee_to_gross_positive_pnl_percent==null?"—":String(s.fee_to_gross_positive_pnl_percent)+"%")+
   ledgerMetric("Baseline net P&L",money(bs.net_pnl_usd),Number(bs.net_pnl_usd)>0)+
   ledgerMetric("Candidate vs baseline",money(data.candidate_vs_baseline_net_pnl_usd),Number(data.candidate_vs_baseline_net_pnl_usd)>0)+'</div>';
  const groupTable=(title,obj)=>'<h4>'+title+'</h4><div class="ledger-table-wrap"><table class="ledger-table"><thead><tr><th>Group</th><th>Trades</th><th>Gross P&amp;L</th><th>Fees</th><th>Net P&amp;L</th><th>Net PF</th></tr></thead><tbody>'+
   Object.entries(obj||{}).map(([k,v])=>'<tr><td>'+escapeLedger(k)+'</td><td>'+escapeLedger(v.trades)+'</td><td>'+money(v.gross_pnl_usd)+'</td><td>'+money(v.fees_usd)+'</td><td>'+money(v.net_pnl_usd)+'</td><td>'+escapeLedger(v.net_profit_factor??"—")+'</td></tr>').join("")+
   '</tbody></table></div>';
  const diagnosis='<h4>What the sample indicates</h4><ul>'+((data.diagnosis||[]).map(x=>'<li>'+escapeLedger(x)+'</li>').join(""))+'</ul>';
  const ledger=(p.trade_ledger||[]).slice(-25).reverse().map(x=>'<tr><td>'+escapeLedger(x.entry_time)+'</td><td>'+escapeLedger(x.exit_reason)+'</td><td>'+money(x.gross_pnl_usd)+'</td><td>'+money(x.fees_usd)+'</td><td>'+money(x.net_pnl_usd)+'</td><td>'+escapeLedger(x.break_even_price_move_bps??"—")+'</td><td>'+escapeLedger(x.gross_outcome_class)+'</td></tr>').join("");
  out.innerHTML='<strong>'+escapeLedger(data.status)+'</strong>'+grid+
   groupTable("Candidate · gross outcome classes",p.gross_outcome_attribution)+
   groupTable("Candidate · exit reasons",p.exit_reason_attribution)+
   groupTable("Baseline · gross outcome classes",b.cost_edge?.gross_outcome_attribution)+
   diagnosis+
   '<h4>Latest candidate trades</h4><div class="ledger-table-wrap"><table class="ledger-table"><thead><tr><th>Entry</th><th>Exit</th><th>Gross</th><th>Fees</th><th>Net</th><th>Break-even bps</th><th>Gross class</th></tr></thead><tbody>'+ledger+'</tbody></table></div>'+
   '<small class="muted">Holdout: '+escapeLedger(data.holdout?.status||"SEALED_NOT_ACCESSED")+'. Break-even move covers estimated round-trip fees only; slippage is already embedded in fills and is not deducted twice. Fixed candidate/baseline only; no parameter search, broker API calls, order submission or automated execution.</small>';
 }catch(e){out.textContent="Stage 5.10 diagnostics unavailable: "+e.message;}
 finally{btn.disabled=false;}
}

async function runStage59(){
 const out=$("stage59-result"),btn=$("run-stage59");if(!out||!btn)return;
 btn.disabled=true;out.textContent="Recomputing every training trade's fills, gross P&L, fees, embedded slippage and R multiples…";
 try{
  const data=await get("/research/stage5-9/run?timeframe=5Min&limit=30000&starting_equity=100&notional_usd=10&fee_rate=0.0025&slippage_bps=5&train_fraction=0.60");
  if(data.status==="INSUFFICIENT_DATA"){out.textContent="Insufficient history: "+escapeLedger(data.bars_used)+" / "+escapeLedger(data.minimum_bars)+" minimum bars.";return;}
  if(data.status==="DATA_INTEGRITY_FAILED"){out.textContent="Data integrity failed. Accounting audit was not run.";return;}
  const a=data.accounting_audit||{},s=a.summary||{},m=data.reported_backtest_metrics||{};
  const grid='<div class="backtest-grid">'+
   ledgerMetric("Training bars",data.training_bars??0)+
   ledgerMetric("Trades audited",s.trades_audited??0)+
   ledgerMetric("Accounting checks",a.status||"—",a.status==="PASS")+
   ledgerMetric("Discrepancies",a.discrepancy_count??0,Number(a.discrepancy_count)===0)+
   ledgerMetric("Recomputed gross P&L",money(s.gross_pnl_recomputed_usd),Number(s.gross_pnl_recomputed_usd)>0)+
   ledgerMetric("Recomputed fees",money(s.fees_recomputed_usd))+
   ledgerMetric("Recomputed net P&L",money(s.net_pnl_recomputed_usd),Number(s.net_pnl_recomputed_usd)>0)+
   ledgerMetric("Embedded slippage",money(s.embedded_slippage_recomputed_usd))+
   ledgerMetric("Backtest totals match",data.aggregate_totals_match_backtest?"YES":"NO",data.aggregate_totals_match_backtest)+
   ledgerMetric("TP trades net-negative",s.take_profit_net_negative_count??0)+
   ledgerMetric("TP gross non-positive",s.take_profit_gross_nonpositive_count??0)+
   ledgerMetric("Median gross R",s.gross_r_median??"—")+
   ledgerMetric("Median net R",s.net_r_median??"—")+'</div>';
  const issues=(a.discrepancies||[]).slice(0,25).map(x=>'<tr><td>'+escapeLedger(x.trade)+'</td><td>'+escapeLedger(x.field)+'</td><td>'+escapeLedger(x.recomputed??x.detail??"—")+'</td><td>'+escapeLedger(x.reported??"—")+'</td></tr>').join("");
  const trades=(a.trade_ledger||[]).slice(-25).reverse().map(x=>'<tr><td>'+escapeLedger(x.entry_time)+'</td><td>'+escapeLedger(x.exit_reason)+'</td><td>'+money(x.recomputed_gross_pnl_usd)+'</td><td>'+money(x.recomputed_fees_usd)+'</td><td>'+money(x.recomputed_net_pnl_usd)+'</td><td>'+escapeLedger(x.gross_r_multiple??"—")+'</td><td>'+escapeLedger(x.net_r_multiple??"—")+'</td></tr>').join("");
  out.innerHTML='<strong>'+escapeLedger(data.status)+' · '+escapeLedger(a.status||"AUDIT UNAVAILABLE")+'</strong>'+grid+
   '<p>'+escapeLedger(a.interpretation||"")+'</p>'+
   (a.discrepancies?.length?'<h4>Accounting discrepancies</h4><div class="ledger-table-wrap"><table class="ledger-table"><thead><tr><th>Trade</th><th>Field</th><th>Recomputed</th><th>Reported</th></tr></thead><tbody>'+issues+'</tbody></table></div>':'<p>No trade-level accounting discrepancy found within rounding tolerance.</p>')+
   '<h4>Latest audited trades</h4><div class="ledger-table-wrap"><table class="ledger-table"><thead><tr><th>Entry</th><th>Exit</th><th>Gross</th><th>Fees</th><th>Net</th><th>Gross R</th><th>Net R</th></tr></thead><tbody>'+trades+'</tbody></table></div>'+
   '<small class="muted">Holdout: '+escapeLedger(data.holdout?.status||"SEALED_NOT_ACCESSED")+'. Slippage is already embedded in executed fills and is not deducted twice. Simulator accounting audit only; not broker-fill verification. No parameter search, broker writes, order submission or automated execution.</small>';
 }catch(e){out.textContent="Stage 5.9 audit unavailable: "+e.message;}
 finally{btn.disabled=false;}
}

async function runStage58(){
 const out=$("stage58-result"),btn=$("run-stage58");if(!out||!btn)return;
 btn.disabled=true;out.textContent="Fetching BTC/USD M5 history and diagnosing the fixed Stage 5.7 candidate on training data only…";
 try{
  const data=await get("/research/stage5-8/run?timeframe=5Min&limit=30000&starting_equity=100&notional_usd=10&fee_rate=0.0025&slippage_bps=5&train_fraction=0.60");
  if(data.status==="INSUFFICIENT_DATA"){out.textContent="Insufficient history: "+escapeLedger(data.bars_used)+" / "+escapeLedger(data.minimum_bars)+" minimum bars.";return;}
  if(data.status==="DATA_INTEGRITY_FAILED"){out.textContent="Data integrity failed. No attribution was run.";return;}
  const t=data.training||{},m=t.metrics||{},r=t.risk_diagnostics||{},c=data.candidate||{};
  const base=c.baseline_training_metrics||{},cand=c.candidate_training_metrics||{};
  const grid='<div class="backtest-grid">'+
   ledgerMetric("Training bars",data.training_bars??0)+
   ledgerMetric("Candidate trades",m.trades??0)+
   ledgerMetric("Candidate net P&L",money(m.net_pnl_usd),Number(m.net_pnl_usd)>0)+
   ledgerMetric("Candidate net PF",m.net_profit_factor??"—")+
   ledgerMetric("Win rate",String(m.win_rate_percent??0)+"%")+
   ledgerMetric("Stop-loss share",String(r.stop_loss_share_percent??0)+"%")+
   ledgerMetric("Longest losing streak",r.longest_losing_streak??0)+
   ledgerMetric("Median realized R",r.realized_net_r_median??"—")+
   ledgerMetric("Median hold",r.median_holding_minutes==null?"—":String(r.median_holding_minutes)+" min")+
   ledgerMetric("Average entry gap (ATR)",r.average_entry_gap_atr??"—")+
   ledgerMetric("Baseline net P&L",money(base.net_pnl_usd),Number(base.net_pnl_usd)>0)+
   ledgerMetric("Candidate vs baseline",money(Number(cand.net_pnl_usd||0)-Number(base.net_pnl_usd||0)),Number(cand.net_pnl_usd)>Number(base.net_pnl_usd))+'</div>';
  const groupTable=(title,obj)=>'<h4>'+title+'</h4><div class="ledger-table-wrap"><table class="ledger-table"><thead><tr><th>Group</th><th>Trades</th><th>Win %</th><th>Net P&amp;L</th><th>Net PF</th></tr></thead><tbody>'+
   Object.entries(obj||{}).map(([k,v])=>'<tr><td>'+escapeLedger(k)+'</td><td>'+escapeLedger(v.trades)+'</td><td>'+escapeLedger(v.win_rate_percent)+'%</td><td>'+money(v.net_pnl_usd)+'</td><td>'+escapeLedger(v.net_profit_factor??"—")+'</td></tr>').join("")+
   '</tbody></table></div>';
  const findings='<h4>Findings to investigate</h4><ul>'+((t.findings||[]).map(x=>'<li>'+escapeLedger(x)+'</li>').join(""))+'</ul>';
  const trades=(t.trade_ledger||[]).slice(-25).reverse().map(x=>'<tr><td>'+escapeLedger(x.entry_time)+'</td><td>'+escapeLedger(x.exit_reason)+'</td><td>'+escapeLedger(x.entry_session_utc)+'</td><td>'+escapeLedger(x.entry_regime)+'</td><td>'+escapeLedger(x.realized_net_r_multiple??"—")+'</td><td>'+money(x.net_pnl_usd)+'</td></tr>').join("");
  out.innerHTML='<strong>'+escapeLedger(data.status)+'</strong>'+grid+
   groupTable("Exit reason attribution",t.exit_reason_attribution)+
   groupTable("Entry session · UTC",t.entry_session_attribution_utc)+
   groupTable("Entry market regime",t.entry_regime_attribution)+
   groupTable("Holding duration",t.holding_duration_attribution)+
   groupTable("Next-bar entry gap",t.entry_gap_attribution)+findings+
   '<h4>Latest training trades</h4><div class="ledger-table-wrap"><table class="ledger-table"><thead><tr><th>Entry</th><th>Exit</th><th>Session</th><th>Regime</th><th>Net R</th><th>Net P&amp;L</th></tr></thead><tbody>'+trades+'</tbody></table></div>'+
   '<small class="muted">Holdout: '+escapeLedger(data.holdout?.status||"SEALED_NOT_ACCESSED")+'. No holdout outcomes, parameter search, broker API calls, order submission, or automated execution. Session labels are UTC. Realized R is model-derived from the fixed 1.5 ATR stop and configured notional.</small>';
 }catch(e){out.textContent="Stage 5.8 diagnostics unavailable: "+e.message;}
 finally{btn.disabled=false;}
}

async function runStage57(){
 const out=$("stage57-result"),btn=$("run-stage57");if(!out||!btn)return;
 btn.disabled=true;out.textContent="Fetching BTC/USD M5 history; testing one fixed trend-gated candidate on training data only…";
 try{
  const data=await get("/research/stage5-7/run?timeframe=5Min&limit=30000&starting_equity=100&notional_usd=10&fee_rate=0.0025&slippage_bps=5&train_fraction=0.60&minimum_training_trades=30");
  if(data.status==="INSUFFICIENT_DATA"){out.textContent="Insufficient history: "+escapeLedger(data.bars_used)+" / "+escapeLedger(data.minimum_bars)+" minimum bars.";return;}
  if(data.status==="DATA_INTEGRITY_FAILED"){out.textContent="Data integrity failed. Candidate analysis was not run.";return;}
  const c=data.candidate||{},base=c.baseline_training_metrics||{},m=c.candidate_training_metrics||{},d=c.diagnostics||{};
  const grid='<div class="backtest-grid">'+
   ledgerMetric("Training bars",data.training_bars??0)+
   ledgerMetric("Baseline trades",base.trades??0)+
   ledgerMetric("Candidate trades",m.trades??0)+
   ledgerMetric("Candidate signals",d.candidate_signals??0)+
   ledgerMetric("Baseline net P&L",money(base.net_pnl_usd),Number(base.net_pnl_usd)>0)+
   ledgerMetric("Candidate net P&L",money(m.net_pnl_usd),Number(m.net_pnl_usd)>0)+
   ledgerMetric("Candidate net PF",m.net_profit_factor??"—")+
   ledgerMetric("Win rate",String(m.win_rate_percent??0)+"%")+
   ledgerMetric("Trade count change",c.trade_count_change??0)+
   ledgerMetric("Training gate",c.training_gate_passed?"PASS":"FAIL")+'</div>';
  out.innerHTML='<strong>'+escapeLedger(data.status)+'</strong>'+grid+
   '<p>'+escapeLedger(data.next_step||"")+'</p>'+
   '<small class="muted">Filter: latest completed 1h EMA50 &gt; EMA200 and close &gt; EMA50. Holdout: '+escapeLedger(data.holdout?.status||"SEALED")+'. No holdout outcome evaluation, parameter search, account/order/position calls, order submission, or automated execution.</small>';
 }catch(e){out.textContent="Stage 5.7 candidate test unavailable: "+e.message;}
 finally{btn.disabled=false;}
}

async function runStage55(){
 const out=$("stage55-result"),btn=$("run-stage55");if(!out||!btn)return;
 btn.disabled=true;out.textContent="Fetching up to 30,000 BTC/USD M5 candles and auditing data integrity and simulated costs…";
 try{
  const data=await get("/research/stage5-5/run?timeframe=5Min&limit=30000&starting_equity=100&notional_usd=10&fee_rate=0.0025&slippage_bps=5&train_fraction=0.60");
  if(data.status==="INSUFFICIENT_DATA"){out.textContent="Insufficient history: "+escapeLedger(data.bars_used)+" / "+escapeLedger(data.minimum_bars)+" minimum bars.";return;}
  const audit=data.data_audit||{},checks=audit.checks||{},g=data.audit_gates||{};
  const checkRows=Object.entries(checks).map(([name,pass])=>'<div class="check-row"><span>'+escapeLedger(name.replaceAll("_"," "))+'</span><strong class="'+(pass?"check-pass":"check-fail")+'">'+(pass?"PASS":"FAIL")+'</strong></div>').join("");
  const gateRows=Object.entries(g).map(([name,pass])=>'<div class="check-row"><span>'+escapeLedger(name.replaceAll("_"," "))+'</span><strong class="'+(pass?"check-pass":"check-fail")+'">'+(pass?"PASS":"FAIL")+'</strong></div>').join("");
  const dataGrid='<div class="backtest-grid">'+ledgerMetric("Bars received",audit.bars_received??data.bars_used)+ledgerMetric("Unique timestamps",audit.unique_timestamp_count??"—")+ledgerMetric("5m coverage",String(audit.observed_5m_coverage_percent??0)+"%")+ledgerMetric("Missing 5m intervals",audit.estimated_missing_5m_intervals??0)+ledgerMetric("Largest gap",String(audit.largest_gap_minutes??0)+" min")+ledgerMetric("Duplicate timestamps",audit.duplicate_timestamps??0)+ledgerMetric("Invalid OHLC",audit.invalid_ohlc_bars??0)+ledgerMetric("Invalid volume",audit.invalid_volume_bars??0)+'</div>';
  const costs=(label,part)=>{const m=part?.metrics||{},c=part?.cost_reconciliation||{};return '<h4>'+label+'</h4><div class="backtest-grid">'+ledgerMetric("Trades",m.trades??0)+ledgerMetric("Gross P&L",money(m.gross_pnl_usd),Number(m.gross_pnl_usd)>0)+ledgerMetric("Fees",money(c.estimated_fees_usd))+ledgerMetric("Slippage",money(c.estimated_slippage_usd))+ledgerMetric("Net P&L",money(m.net_pnl_usd),Number(m.net_pnl_usd)>0)+ledgerMetric("Cost reconciliation",c.reconciliation_passed?"PASS":"FAIL",!!c.reconciliation_passed)+'</div><small class="muted">'+escapeLedger(c.slippage_treatment||"")+'</small>';};
  const ledger=(label,part)=>{const rows=(part?.trade_ledger||[]).map(t=>'<tr><td>'+ledgerTime(t.entry_time)+'</td><td>'+ledgerTime(t.exit_time)+'</td><td>'+money(t.gross_pnl_usd)+'</td><td>'+money(t.estimated_fees_usd)+'</td><td>'+money(t.estimated_slippage_usd)+'</td><td>'+money(t.net_pnl_usd)+'</td></tr>').join("");return '<h4>'+label+' · latest '+(part?.trade_ledger||[]).length+' trades</h4><div class="ledger-table-wrap"><table class="ledger-table"><thead><tr><th>Entry</th><th>Exit</th><th>Gross</th><th>Fees</th><th>Slippage</th><th>Net</th></tr></thead><tbody>'+rows+'</tbody></table></div>';};
  const title='<strong class="'+(data.status==="AUDIT_PASS_RESEARCH_ONLY"?"check-pass":"check-fail")+'">'+escapeLedger(data.status)+'</strong><p>BTC/USD · '+escapeLedger(data.bars_used)+'/'+escapeLedger(data.requested_bars)+' bars · '+escapeLedger(data.data_pages_fetched)+' data pages</p><small class="muted">'+ledgerTime(data.period?.from)+' → '+ledgerTime(data.period?.to)+' · Full requested history: '+(data.history_complete_for_request?"YES":"NO")+'</small>';
  out.innerHTML=title+'<h4>Historical data integrity</h4>'+dataGrid+checkRows+'<h4>Audit gates</h4>'+gateRows+costs("Training cost audit",data.training)+ledger("Training ledger",data.training)+costs("Untouched holdout cost audit",data.holdout)+ledger("Holdout ledger",data.holdout)+'<small class="muted">A Stage 5.5 audit pass validates data structure and accounting arithmetic only. It does not mean the strategy is profitable or ready for automation. Costs are estimates, not broker fills. Slippage is embedded in simulated execution prices and gross P&L; it is not deducted twice. No account/order/position APIs called; no orders submitted; Auto Entry remains OFF.</small>';
 }catch(e){out.textContent="Stage 5.5 audit unavailable: "+e.message;}
 finally{btn.disabled=false;}
}

async function runStage54(){
 const out=$("stage54-result"),btn=$("run-stage54");if(!out||!btn)return;
 btn.disabled=true;out.textContent="Fetching BTC/USD history and evaluating fixed-strategy chronological regime/fold robustness…";
 try{
  const data=await get("/research/stage5-4/run?timeframe=5Min&limit=10000&starting_equity=100&notional_usd=10&fee_rate=0.0025&slippage_bps=5&folds=4&minimum_trades_per_fold=10&max_drawdown_percent=5");
  if(data.status==="INSUFFICIENT_DATA"){out.textContent="Insufficient history: "+escapeLedger(data.bars_used)+" / 5000 minimum candles.";return;}
  const metrics=(label,m)=>'<h4>'+label+'</h4><div class="backtest-grid">'+ledgerMetric("Trades",m?.trades??0)+ledgerMetric("Net P&L",money(m?.net_pnl_usd),Number(m?.net_pnl_usd)>0)+ledgerMetric("Net PF",m?.net_profit_factor??"—")+ledgerMetric("Win rate",String(m?.win_rate_percent??0)+"%")+ledgerMetric("Closed-trade max DD",String(m?.max_closed_trade_drawdown_percent??m?.max_drawdown_percent??0)+"%")+ledgerMetric("Fees",money(m?.fees_usd??m?.estimated_fees_usd))+'</div>';
  const regimeTable=(items)=>{const rows=Object.entries(items||{}).map(([name,m])=>'<tr><td>'+escapeLedger(name)+'</td><td>'+escapeLedger(m.trades)+'</td><td>'+escapeLedger(m.win_rate_percent)+'%</td><td>'+money(m.net_pnl_usd)+'</td><td>'+escapeLedger(m.net_profit_factor??"—")+'</td></tr>').join("");return '<div class="ledger-table-wrap"><table class="ledger-table"><thead><tr><th>Regime</th><th>Trades</th><th>Win rate</th><th>Net P&amp;L</th><th>Net PF</th></tr></thead><tbody>'+rows+'</tbody></table></div>';};
  const folds=(data.walk_forward_folds||[]).map(f=>'<tr><td>'+escapeLedger(f.fold)+'</td><td>'+ledgerTime(f.from)+'</td><td>'+ledgerTime(f.to)+'</td><td>'+escapeLedger(f.metrics.trades)+'</td><td>'+money(f.metrics.net_pnl_usd)+'</td><td>'+escapeLedger(f.metrics.net_profit_factor??"—")+'</td><td>'+escapeLedger(f.metrics.max_closed_trade_drawdown_percent)+'%</td><td class="'+(f.entries_after_fold_start?"check-pass":"check-fail")+'">'+(f.entries_after_fold_start?"PASS":"FAIL")+'</td></tr>').join("");
  const g=data.decision_gates||{},fs=data.fold_summary||{};
  const gateRows=[["Training gate",g.training_gate],["Holdout gate",g.holdout_gate],["Walk-forward gate",g.walk_forward_gate],["All gates",g.all_gates_passed]].map(([n,v])=>'<div class="check-row"><span>'+n+'</span><strong class="'+(v?"check-pass":"check-fail")+'">'+(v?"PASS":"FAIL")+'</strong></div>').join("");
  const strategy=data.frozen_strategy||{};
  const summary='<strong class="'+(g.all_gates_passed?"check-pass":"check-fail")+'">'+escapeLedger(data.status)+'</strong><p>'+escapeLedger(data.symbol)+' · '+escapeLedger(data.bars_used)+'/'+escapeLedger(data.requested_bars)+' candles · '+escapeLedger(fs.fold_count)+' holdout folds</p><small class="muted">'+ledgerTime(data.period?.from)+' → '+ledgerTime(data.period?.to)+' · '+escapeLedger(data.split?.method)+'</small>';
  const params='<p><strong>Frozen parameters:</strong> Donchian '+strategy.donchian_lookback+' · RelVol '+strategy.relative_volume_threshold+' · Pullback '+strategy.pullback_atr+' ATR / '+strategy.pullback_bars+' bars · Stop '+strategy.stop_atr_multiple+' ATR · R:R '+strategy.reward_risk+'</p>';
  const foldTable='<h4>Sequential holdout folds</h4><div class="ledger-table-wrap"><table class="ledger-table"><thead><tr><th>Fold</th><th>From</th><th>To</th><th>Trades</th><th>Net P&amp;L</th><th>Net PF</th><th>Max DD</th><th>Boundary</th></tr></thead><tbody>'+folds+'</tbody></table></div>';
  out.innerHTML=summary+params+gateRows+metrics("Training metrics",data.training?.metrics)+regimeTable(data.training?.regime_attribution)+metrics("Untouched holdout metrics",data.holdout?.metrics)+regimeTable(data.holdout?.regime_attribution)+foldTable+'<small class="muted">Regime tables are descriptive and cannot be used to cherry-pick winning regimes. Fixed parameters; no optimization. Cost assumptions are not actual fills. Historical gates are not proof of future profitability. No Paper/order/position endpoints called; no order submitted; Auto Entry remains OFF.</small>';
 }catch(e){out.textContent="Stage 5.4 unavailable: "+e.message;}
 finally{btn.disabled=false;}
}

async function runStage5Validation(){
 const out=$("stage5-result"),btn=$("run-stage5");if(!out||!btn)return;
 btn.disabled=true;out.textContent="Reading Paper account, positions and open orders…";
 try{
  const data=await get("/paper/validation");
  const checks=(data.checks||[]).map(c=>'<div class="check-row"><span>'+c.check.replaceAll("_"," ")+'</span><strong class="'+(c.passed?"check-pass":"check-fail")+'">'+(c.passed?"PASS":"REVIEW")+'</strong></div>').join("");
  out.innerHTML='<strong class="'+(data.result==="CLEAN"?"check-pass":"check-fail")+'">'+data.result+'</strong><p>'+data.checks_passed+'/'+data.checks_total+' checks passed · Equity '+money(data.account?.equity)+' · BTC positions '+data.btc_open_positions+' · BTC open orders '+data.btc_open_orders+'</p>'+checks+'<small class="muted">Read-only snapshot · No order submitted. Clean status is not proof of lifecycle safety or profitability.</small>';
 }catch(e){out.textContent="Stage 5 check unavailable: "+e.message+" · Confirm the Paper API token in Settings and backend deployment.";}
 finally{btn.disabled=false;}
}
async function runStage6Readiness(){
 const out=$("stage6-result"),btn=$("run-stage6");if(!out||!btn)return;
 btn.disabled=true;out.textContent="Evaluating live-trading safety gates…";
 try{
  const data=await get("/live/readiness");
  const gates=(data.gates||[]).map(g=>'<div class="check-row"><span>'+g.gate.replaceAll("_"," ")+'<small>'+g.detail+'</small></span><strong class="'+(g.passed?"check-pass":"check-fail")+'">'+(g.passed?"PASS":"BLOCKED")+'</strong></div>').join("");
  const actions=(data.next_actions||[]).map((item,index)=>'<li>'+item+'</li>').join("");
  out.innerHTML='<strong class="check-fail">'+data.result+' · '+data.gates_passed+'/'+data.gates_total+' gates passed · '+data.readiness_percent+'% </strong>'+gates+'<strong>Next steps</strong><ol>'+actions+'</ol><small class="muted">Assessment only · Live supported: NO · Live orders enabled: NO · Broker API called: NO · No order submitted.</small>';
 }catch(e){out.textContent="Stage 6 assessment unavailable: "+e.message;}
 finally{btn.disabled=false;}
}
function setupControls(){
 const tokenInput=$("paper-api-token");
 const rememberToken=$("remember-paper-token");
 if(tokenInput){const savedToken=getPaperToken();tokenInput.value=savedToken;if(rememberToken){rememberToken.checked=true;if(savedToken)savePaperToken(savedToken,true);rememberToken.addEventListener("change",()=>{savePaperToken(tokenInput.value,rememberToken.checked);});}tokenInput.addEventListener("change",()=>{savePaperToken(tokenInput.value,!!rememberToken?.checked);loadPaperEngineStatus();});}
 const tf=$("timeframe");tf.addEventListener("change",()=>{selectedTimeframe=tf.value;text("signal-timeframe",labels[selectedTimeframe].toUpperCase());refresh().catch(e=>setStatus(e.message));});
 $("run-backtest").addEventListener("click",runBacktest);
 const s51=$("run-stage51");if(s51)s51.addEventListener("click",runStage51Ledger);
 const s53=$("run-stage53");if(s53)s53.addEventListener("click",runStage53);
 const s54=$("run-stage54");if(s54)s54.addEventListener("click",runStage54);
 const s55=$("run-stage55");if(s55)s55.addEventListener("click",runStage55);
 const s56=$("run-stage56");if(s56)s56.addEventListener("click",runStage56);
 const s57=$("run-stage57");if(s57)s57.addEventListener("click",runStage57);
 const s58=$("run-stage58");if(s58)s58.addEventListener("click",runStage58);
 const s59=$("run-stage59");if(s59)s59.addEventListener("click",runStage59);
 const s510=$("run-stage510");if(s510)s510.addEventListener("click",runStage510);
 const s511=$("run-stage511");if(s511)s511.addEventListener("click",runStage511);
 const s5=$("run-stage5");if(s5)s5.addEventListener("click",runStage5Validation);
 const s6=$("run-stage6");if(s6)s6.addEventListener("click",runStage6Readiness);
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
  state.textContent=s.order_submission_enabled?"PAPER AUTO ENTRY ENABLED":"PREVIEW ONLY · AUTO ENTRY OFF";
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


async function loadAutoEntryStatus(){
 const state=$("auto-entry-state"),out=$("auto-entry-status");
 if(!state)return;
 try{
  const data=await get("/paper/auto-entry");
  const enabled=Boolean(data.enabled&&data.order_submission_enabled);
  state.textContent=enabled?"ENABLED · PAPER":"OFF";
  state.className="tag "+(enabled?"check-fail":"neutral");
  text("robot-auto-state",enabled?"ON · PAPER AUTO ENTRY":"OFF · MONITOR ONLY");
  text("robot-execution-state",enabled?"Paper Auto Entry ON":"Paper Auto Entry OFF");
  if(out)out.textContent="Mode: "+data.mode+" · Auto Entry: "+(enabled?"ON":"OFF")+" · Today: "+data.trades_today+"/"+data.daily_trade_count_limit+" entries · Last event: "+(data.last_event||"—");
  const enable=$("auto-entry-enable"),disable=$("auto-entry-disable");
  if(enable)enable.disabled=enabled;
  if(disable)disable.disabled=!enabled;
 }catch(e){
  state.textContent="STATUS UNAVAILABLE";
  if(out)out.textContent="Auto Entry status unavailable: "+e.message+" · Check the dashboard token and backend.";
 }
}
async function runAutoEntryDryRun(){
 const out=$("auto-entry-status"),btn=$("auto-entry-dry-run");
 if(!out||!btn)return;
 btn.disabled=true;out.textContent="Checking Paper account, open BTC positions/orders, completed candle, quote freshness and risk limits…";
 try{
  const data=await get("/paper/auto-entry/dry-run");
  const lines=(data.checks||[]).map(c=>(c.passed?"PASS":"BLOCKED")+" · "+c.check.replaceAll("_"," ")+": "+c.detail);
  out.textContent=data.result+" · Proposed notional "+money(data.proposed_notional_usd)+" · Quantity "+data.proposed_quantity_btc+" BTC\n"+lines.join("\n")+"\nNo order submitted; no execution state changed.";
 }catch(e){out.textContent="Preflight unavailable: "+e.message;}
 finally{btn.disabled=false;}
}
async function setAutoEntry(enabled){
 const out=$("auto-entry-status"),btn=$(enabled?"auto-entry-enable":"auto-entry-disable");
 if(!out||!btn)return;
 if(enabled&&!window.confirm("Enable APEX Paper Auto Entry? This starts a server-side controller that may submit Alpaca PAPER market orders when a valid BTC setup appears. No live-money orders are supported."))return;
 btn.disabled=true;out.textContent=enabled?"Enabling Paper Auto Entry…":"Disabling Paper Auto Entry…";
 try{
  const path=enabled?"/paper/auto-entry/enable":"/paper/auto-entry/disable";
  const response=await fetch(API+path,{method:"POST",headers:paperHeaders(path,{"Content-Type":"application/json"})});
  const data=await response.json();
  if(!response.ok)throw new Error(data.detail||"HTTP "+response.status);
  out.textContent="Mode: "+data.mode+" · Auto Entry: "+(data.enabled?"ON":"OFF")+" · Last event: "+(data.last_event||"—")+" · Daily cap: "+data.trades_today+"/"+data.daily_trade_count_limit;
  await loadAutoEntryStatus();
 }catch(e){out.textContent=(enabled?"Enable":"Disable")+" failed: "+e.message;}
 finally{btn.disabled=false;}
}
const autoDryRunButton=$("auto-entry-dry-run");
if(autoDryRunButton)autoDryRunButton.addEventListener("click",runAutoEntryDryRun);
const autoEnableButton=$("auto-entry-enable");
if(autoEnableButton)autoEnableButton.addEventListener("click",()=>setAutoEntry(true));
const autoDisableButton=$("auto-entry-disable");
if(autoDisableButton)autoDisableButton.addEventListener("click",()=>setAutoEntry(false));
loadAutoEntryStatus();
setInterval(loadAutoEntryStatus,15000);

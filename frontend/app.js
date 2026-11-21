const API=window.APEX_API_BASE||"https://apex-ai-btc-pwa.onrender.com/api";
const money=value=>new Intl.NumberFormat("en-US",{style:"currency",currency:"USD"}).format(Number(value||0));

async function get(path){
  let response;
  try{
    response=await fetch(API+path,{method:"GET",headers:{Accept:"application/json"},cache:"no-store"});
  }catch(error){
    const detail=error?.message||String(error);
    throw new Error("Network/CORS failure at "+path+": "+detail);
  }
  if(!response.ok){
    let detail="";
    try{detail=(await response.text()).slice(0,180)}catch(_){}
    throw new Error("HTTP "+response.status+" at "+path+(detail?": "+detail:""));
  }
  try{return await response.json()}
  catch(_){throw new Error("Invalid JSON response at "+path)}
}

function showConnection(message,ok=false){
  const element=document.getElementById("connection");
  if(!element)return;
  element.textContent=message;
  element.style.color=ok?"var(--green)":"#ffb27d";
  element.title=message;
}

function ema(values,period){
  const k=2/(period+1);
  let previous=values[0];
  return values.map((value,index)=>{
    if(index===0)return previous;
    previous=value*k+previous*(1-k);
    return previous;
  });
}

function calculateATR(candles,period=14){
  const ranges=candles.map((bar,index)=>{
    if(index===0)return bar.h-bar.l;
    const previousClose=candles[index-1].c;
    return Math.max(bar.h-bar.l,Math.abs(bar.h-previousClose),Math.abs(bar.l-previousClose));
  });
  if(ranges.length<period)return null;
  return ranges.slice(-period).reduce((sum,value)=>sum+value,0)/period;
}

function renderChart(bars){
  const svg=document.getElementById("price-chart");
  if(!svg||!bars?.length)return;

  const candles=bars.map(bar=>({
    o:Number(bar.o),h:Number(bar.h),l:Number(bar.l),c:Number(bar.c)
  })).filter(bar=>[bar.o,bar.h,bar.l,bar.c].every(Number.isFinite));
  if(!candles.length)return;

  const closes=candles.map(bar=>bar.c);
  const ema9=ema(closes,9);
  const ema21=ema(closes,21);
  const atr14=calculateATR(candles,14);

  const rawLow=Math.min(...candles.map(bar=>bar.l),...ema9,...ema21);
  const rawHigh=Math.max(...candles.map(bar=>bar.h),...ema9,...ema21);
  const padding=(rawHigh-rawLow)*0.08||1;
  const low=rawLow-padding;
  const high=rawHigh+padding;
  const range=high-low||1;
  const left=10,right=590,top=25,bottom=165;
  const y=value=>bottom-((value-low)/range)*(bottom-top);
  const step=(right-left)/candles.length;
  const bodyWidth=Math.max(2,Math.min(7,step*0.62));

  const shapes=candles.map((bar,index)=>{
    const x=left+step*(index+0.5);
    const rising=bar.c>=bar.o;
    const color=rising?"#35d49a":"#ff6b78";
    const bodyTop=Math.min(y(bar.o),y(bar.c));
    const bodyHeight=Math.max(1.5,Math.abs(y(bar.o)-y(bar.c)));
    return `<g stroke="${color}" fill="${color}">
      <line x1="${x}" y1="${y(bar.h)}" x2="${x}" y2="${y(bar.l)}" stroke-width="1.2"/>
      <rect x="${x-bodyWidth/2}" y="${bodyTop}" width="${bodyWidth}" height="${bodyHeight}" rx="0.7"/>
    </g>`;
  }).join("");

  const linePath=values=>values.map((value,index)=>{
    const x=left+step*(index+0.5);
    return `${index===0?"M":"L"} ${x.toFixed(2)} ${y(value).toFixed(2)}`;
  }).join(" ");
  const overlays=`
    <path d="${linePath(ema9)}" fill="none" stroke="#f5c451" stroke-width="2" stroke-linejoin="round"/>
    <path d="${linePath(ema21)}" fill="none" stroke="#65a9ff" stroke-width="2" stroke-linejoin="round"/>
    <g font-size="11" font-weight="700">
      <text x="12" y="15" fill="#f5c451">EMA 9</text>
      <text x="68" y="15" fill="#65a9ff">EMA 21</text>
      <text x="145" y="15" fill="#c4d0df">ATR 14: ${atr14==null?"—":money(atr14)}</text>
    </g>`;

  svg.innerHTML=shapes+overlays;
  document.getElementById("chart-meta").textContent=
    `${candles.length} recent 5-minute candles · EMA 9 (yellow) · EMA 21 (blue) · ATR 14: ${atr14==null?"need 14 candles":money(atr14)}`;
}

function renderSignalConfirmation(signal,bars){
  const target=document.getElementById("signal-checks");
  if(!target)return;
  const valid=signal&&signal.ema_9!=null&&signal.ema_21!=null&&signal.atr_14!=null;
  if(!valid){
    target.innerHTML="<p class=\"muted\">Not enough data to confirm the current setup.</p>";
    return;
  }
  const emaBull=Number(signal.ema_9)>Number(signal.ema_21);
  const priceAbove=Number(signal.last_close)>Number(signal.ema_9);
  const atrOk=Number(signal.atr_14)>0;
  const latest=bars?.length?Number(bars[bars.length-1].c):Number(signal.last_close);
  const prior=bars?.length>1?Number(bars[bars.length-2].c):null;
  const momentum=prior==null?null:latest>prior?"UP":latest<prior?"DOWN":"FLAT";
  const row=(label,passed,detail)=>`<div class="check-row"><span>${label}</span><strong class="${passed===null?"muted":passed?"check-pass":"check-fail"}">${detail}</strong></div>`;
  target.innerHTML=[
    row("EMA trend · EMA 9 vs EMA 21",emaBull,emaBull?"BULLISH":"NOT BULLISH"),
    row("Price position · close vs EMA 9",priceAbove,priceAbove?"ABOVE":"NOT ABOVE"),
    row("ATR 14 · volatility available",atrOk,atrOk?"VALID":"UNAVAILABLE"),
    row("Last-candle momentum · informational",momentum==="UP"?true:momentum==="DOWN"?false:null,momentum||"UNKNOWN")
  ].join("");
}


function renderMTFConfirmation(baseSignal,timeframeResults){
  const target=document.getElementById("mtf-checks");
  const summary=document.getElementById("mtf-summary");
  if(!target||!summary)return;
  const base=baseSignal?.signal;
  const directional=["LONG_SETUP","SHORT_SETUP"].includes(base);
  const rows=[{label:"5 MIN",data:baseSignal},...timeframeResults];
  if(!directional){
    summary.textContent="The 5-minute engine has no directional setup. Higher timeframes are shown for context only.";
  }else{
    const aligned=rows.filter(item=>item.data?.signal===base).length;
    summary.textContent=aligned+" of 3 timeframes match the 5-minute "+(base==="LONG_SETUP"?"LONG":"SHORT")+" direction.";
  }
  target.innerHTML=rows.map(item=>{
    const status=item.data?.signal;
    const label=status==="LONG_SETUP"?"LONG":status==="SHORT_SETUP"?"SHORT":status==="WAIT"?"WAIT":status==="INSUFFICIENT_DATA"?"NOT ENOUGH DATA":"UNAVAILABLE";
    const same=directional&&status===base;
    const opposite=directional&&["LONG_SETUP","SHORT_SETUP"].includes(status)&&status!==base;
    const cls=same?"check-pass":opposite?"check-fail":"muted";
    const detail=item.data?.ema_9!=null&&item.data?.ema_21!=null
      ?"EMA 9 "+money(item.data.ema_9)+" · EMA 21 "+money(item.data.ema_21)
      :(item.error||"Signal unavailable");
    return `<div class="mtf-row"><div><strong>${item.label}</strong><small>${detail}</small></div><strong class="${cls}">${label}</strong></div>`;
  }).join("");
}


function renderEntryQuality(signal,bars){
  const scoreEl=document.getElementById("entry-score");
  const labelEl=document.getElementById("entry-quality-label");
  const detailEl=document.getElementById("entry-quality-detail");
  const checksEl=document.getElementById("entry-quality-checks");
  if(!scoreEl||!labelEl||!detailEl||!checksEl)return;

  const direction=signal?.signal;
  const candles=(bars||[]).map(bar=>({
    o:Number(bar.o),c:Number(bar.c)
  })).filter(bar=>Number.isFinite(bar.o)&&Number.isFinite(bar.c));
  if(!["LONG_SETUP","SHORT_SETUP"].includes(direction)||candles.length<2||
     signal.ema_9==null||signal.ema_21==null||signal.atr_14==null){
    scoreEl.textContent="—";
    labelEl.textContent="NO CONFIRMED DIRECTION";
    detailEl.textContent="A directional setup and enough candle data are required before a score can be calculated.";
    checksEl.innerHTML="";
    return;
  }

  const isLong=direction==="LONG_SETUP";
  const latest=candles[candles.length-1];
  const previous=candles[candles.length-2];
  const emaAligned=isLong?Number(signal.ema_9)>Number(signal.ema_21):Number(signal.ema_9)<Number(signal.ema_21);
  const priceAligned=isLong?Number(signal.last_close)>Number(signal.ema_9):Number(signal.last_close)<Number(signal.ema_9);
  const momentumAligned=isLong?latest.c>previous.c:latest.c<previous.c;
  const candleAligned=isLong?latest.c>latest.o:latest.c<latest.o;
  const atrValid=Number(signal.atr_14)>0;
  const parts=[
    {name:"EMA trend alignment",points:35,ok:emaAligned},
    {name:"Price vs EMA 9",points:25,ok:priceAligned},
    {name:"Last-close momentum",points:20,ok:momentumAligned},
    {name:"Latest candle direction",points:10,ok:candleAligned},
    {name:"ATR 14 available",points:10,ok:atrValid}
  ];
  const score=parts.reduce((sum,item)=>sum+(item.ok?item.points:0),0);
  const quality=score>=85?"STRONG ALIGNMENT":score>=70?"GOOD ALIGNMENT":score>=50?"MIXED ALIGNMENT":"WEAK ALIGNMENT";
  scoreEl.textContent=String(score)+"/100";
  labelEl.textContent=quality;
  detailEl.textContent=(isLong?"LONG":"SHORT")+" rule-alignment score · heuristic, not a win probability or entry instruction.";
  checksEl.innerHTML=parts.map(item=>
    `<div class="check-row"><span>${item.name} · ${item.points} pts</span><strong class="${item.ok?"check-pass":"check-fail"}">${item.ok?"PASS":"NO POINTS"}</strong></div>`
  ).join("");
}

async function refresh(){
  showConnection("Checking API…");
  let accountConnected=false;

  try{
    const account=await get("/account");
    document.getElementById("equity").textContent=money(account.equity);
    document.getElementById("buying").textContent=money(account.buying_power);
    showConnection("ACCOUNT CONNECTED · PAPER",true);
    accountConnected=true;
  }catch(error){
    showConnection("API ERROR · "+error.message);
  }

  try{
    const market=await get("/market/btc");
    if(market.price!=null)document.getElementById("price").textContent=money(market.price);
    if(market.timestamp)document.getElementById("updated").textContent="Last trade "+new Date(market.timestamp).toLocaleString();
    if(!accountConnected)document.getElementById("updated").textContent+=" · Market API works; account API failed";
  }catch(error){
    document.getElementById("updated").textContent="Market error: "+error.message;
  }

  let chartBars=[];
  try{
    const chart=await get("/market/bars?timeframe=5Min&limit=60");
    chartBars=chart.bars||[];
    renderChart(chartBars);
  }catch(error){
    document.getElementById("chart-meta").textContent="Chart error: "+error.message;
  }

  try{
    const signal=await get("/signal?timeframe=5Min");
    const names={LONG_SETUP:"LONG SETUP",SHORT_SETUP:"SHORT SETUP",WAIT:"WAIT",INSUFFICIENT_DATA:"INSUFFICIENT DATA"};
    document.getElementById("signal-value").textContent=names[signal.signal]||"WAITING";
    document.getElementById("signal-detail").textContent=signal.ema_9!=null?
      "EMA 9: "+money(signal.ema_9)+" · EMA 21: "+money(signal.ema_21)+" · ATR 14: "+money(signal.atr_14):
      "Waiting for at least 30 candles.";
    document.getElementById("signal-time").textContent=signal.last_bar_time?"Last candle "+new Date(signal.last_bar_time).toLocaleString():"";
    renderSignalConfirmation(signal,chartBars);
    const mtfResults=await Promise.all(["15Min","1Hour"].map(async timeframe=>{
      try{
        const data=await get("/signal?timeframe="+timeframe);
        return {label:timeframe==="15Min"?"15 MIN":"1 HOUR",data};
      }catch(error){
        return {label:timeframe==="15Min"?"15 MIN":"1 HOUR",data:null,error:error.message};
      }
    }));
    renderMTFConfirmation(signal,mtfResults);
    renderEntryQuality(signal,chartBars);
  }catch(error){
    document.getElementById("signal-value").textContent="ENGINE OFFLINE";
    document.getElementById("signal-detail").textContent="Signal error: "+error.message;
    renderSignalConfirmation(null,[]);
    renderMTFConfirmation(null,[{label:"15 MIN",data:null},{label:"1 HOUR",data:null}]);
    renderEntryQuality(null,[]);
  }
}

if("serviceWorker"in navigator){
  addEventListener("load",()=>navigator.serviceWorker.register("./sw.js").catch(error=>{
    console.warn("PWA service worker registration failed:",error);
  }));
}
refresh();
setInterval(refresh,30000);

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

  try{
    const chart=await get("/market/bars?timeframe=5Min&limit=60");
    renderChart(chart.bars);
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
  }catch(error){
    document.getElementById("signal-value").textContent="ENGINE OFFLINE";
    document.getElementById("signal-detail").textContent="Signal error: "+error.message;
  }
}

if("serviceWorker"in navigator){
  addEventListener("load",()=>navigator.serviceWorker.register("./sw.js").catch(error=>{
    console.warn("PWA service worker registration failed:",error);
  }));
}
refresh();
setInterval(refresh,30000);

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

function renderChart(bars){
  const svg=document.getElementById("price-chart");
  if(!svg||!bars?.length)return;
  const values=bars.map(b=>Number(b.c)).filter(Number.isFinite);
  if(!values.length)return;
  const low=Math.min(...values),high=Math.max(...values),range=high-low||1;
  const points=values.map((v,i)=>`${(i/(values.length-1||1))*580+10},${165-((v-low)/range)*145}`).join(" ");
  svg.innerHTML=`<polyline points="${points}" fill="none" stroke="#35d49a" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>`;
  document.getElementById("chart-meta").textContent=`${values.length} recent 5-minute candles · range ${money(low)} – ${money(high)}`;
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

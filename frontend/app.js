const API=window.APEX_API_BASE||"/api";
const money=value=>new Intl.NumberFormat("en-US",{style:"currency",currency:"USD"}).format(Number(value||0));
async function get(path){const response=await fetch(API+path);if(!response.ok)throw Error("API "+response.status);return response.json()}
async function refresh(){
  const connection=document.getElementById("connection");
  try{
    const account=await get("/account");
    document.getElementById("equity").textContent=money(account.equity);
    document.getElementById("buying").textContent=money(account.buying_power);
    connection.textContent="ACCOUNT CONNECTED";connection.style.color="var(--green)";
  }catch(error){connection.textContent="API NOT CONNECTED";connection.style.color="#ffb27d"}
  try{
    const market=await get("/market/btc");
    if(market.price!=null)document.getElementById("price").textContent=money(market.price);
    if(market.timestamp)document.getElementById("updated").textContent="Last trade "+new Date(market.timestamp).toLocaleString();
  }catch(error){document.getElementById("updated").textContent="Market data unavailable"}
  try{
    const signal=await get("/signal?timeframe=5Min");
    const names={LONG_SETUP:"LONG SETUP",SHORT_SETUP:"SHORT SETUP",WAIT:"WAIT",INSUFFICIENT_DATA:"INSUFFICIENT DATA"};
    document.getElementById("signal-value").textContent=names[signal.signal]||"WAITING";
    document.getElementById("signal-detail").textContent=signal.ema_9!=null?
      "EMA 9: "+money(signal.ema_9)+" · EMA 21: "+money(signal.ema_21)+" · ATR 14: "+money(signal.atr_14):
      "Waiting for at least 30 candles.";
    document.getElementById("signal-time").textContent=signal.last_bar_time?"Last candle "+new Date(signal.last_bar_time).toLocaleString():"";
  }catch(error){document.getElementById("signal-value").textContent="ENGINE OFFLINE";document.getElementById("signal-detail").textContent="Connect the secure backend to calculate the experimental signal."}
}
if("serviceWorker"in navigator)addEventListener("load",()=>navigator.serviceWorker.register("./sw.js").catch(()=>{}));
refresh();setInterval(refresh,30000);

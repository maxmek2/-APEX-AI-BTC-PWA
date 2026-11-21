const CACHE="apex-btc-shell-v10";
const APP_SHELL=["./","./index.html","./styles.css","./app.js","./manifest.webmanifest"];

self.addEventListener("install",event=>{
  event.waitUntil(
    caches.open(CACHE)
      .then(cache=>cache.addAll(APP_SHELL))
      .then(()=>self.skipWaiting())
  );
});

self.addEventListener("activate",event=>{
  event.waitUntil(
    caches.keys()
      .then(keys=>Promise.all(keys.filter(key=>key!==CACHE).map(key=>caches.delete(key))))
      .then(()=>self.clients.claim())
  );
});

self.addEventListener("fetch",event=>{
  const request=event.request;
  const url=new URL(request.url);
  if(url.pathname.includes("/api/")||request.method!=="GET")return;

  // Always try the network first for HTML and JavaScript so deployed fixes
  // are not hidden by an older installed PWA cache.
  const isAppCode=url.pathname.endsWith(".js")||
    url.pathname.endsWith(".html")||
    url.pathname==="/" ;

  if(isAppCode){
    event.respondWith(
      fetch(request).then(response=>{
        if(response.ok){
          const copy=response.clone();
          caches.open(CACHE).then(cache=>cache.put(request,copy));
        }
        return response;
      }).catch(()=>caches.match(request))
    );
    return;
  }

  event.respondWith(
    caches.match(request).then(cached=>cached||fetch(request))
  );
});

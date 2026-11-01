"use strict";
let connecting=false,retryTimer=null;
async function readJSON(url,timeout=8000){
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),timeout);
 try{const r=await fetch(url,{cache:"no-store",signal:controller.signal});if(!r.ok)throw Error("HTTP "+r.status);return await r.json();}
 finally{clearTimeout(timer);}
}
function studioURL(config){
 const url=new URL(config.url);
 const temporary=/(\.trycloudflare\.com|\.lhr\.life|\.localhost\.run)$/.test(url.hostname);
 const cloud=config.mode==="cloud"&&config.hostname===url.hostname&&/^[a-z0-9][a-z0-9.-]+\.[a-z]{2,}$/.test(url.hostname);
 if(url.protocol!=="https:"||url.username||url.password||(!temporary&&!cloud))throw Error("Invalid address");
 return url.origin+"/";
}
async function connect(){
 if(connecting)return;
 connecting=true;clearTimeout(retryTimer);
 const status=document.getElementById("status"),message=document.getElementById("message"),retry=document.getElementById("retry"),spinner=document.getElementById("spinner"),enter=document.getElementById("enter");
 retry.hidden=true;spinner.hidden=false;enter.hidden=true;status.textContent="正在连接创作工作室";
 message.textContent="正在核对当前地址，请稍候。";
 let configured=false;
 try{
  // Test each source's actual backend: a readable but stale raw file must not suppress Pages.
  const sources=["connection.json?t="+Date.now(),"https://raw.githubusercontent.com/719566486/yingke-aigc-studio/main/docs/connection.json?t="+Date.now()];
  const attempts=sources.map(async source=>{
   const target=studioURL(await readJSON(source));configured=true;
   if(enter.hidden){enter.href=target;enter.textContent="直接尝试进入工作室 →";enter.hidden=false;}
   const ping=await readJSON(target+"api/share/ping");if(!ping.online)throw Error("Backend offline");
   return target;
  });
  const target=await Promise.any(attempts);
  enter.href=target;enter.textContent="开始创作 →";enter.hidden=false;spinner.hidden=true;
  status.textContent="创作服务已就绪";message.textContent="点击开始创作，完成后用手机扫码领取短片。";
 }catch(error){
  status.textContent="欢迎来到映刻工作室";
  message.textContent=configured?"创作服务暂未连接，页面仍可浏览。可能是工作室离线或网络检查超时；可尝试直达入口，15秒后自动重试。":"页面已打开，正在等待创作服务的最新地址，15秒后自动重试。";
  spinner.hidden=true;retry.hidden=false;retryTimer=setTimeout(connect,15000);
 }finally{connecting=false;}
}
document.getElementById("retry").addEventListener("click",connect);connect();

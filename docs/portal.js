"use strict";
async function connect(){
 const status=document.getElementById("status"),message=document.getElementById("message"),retry=document.getElementById("retry"),spinner=document.getElementById("spinner");
 retry.hidden=true;spinner.hidden=false;status.textContent="正在连接创作工作室";
 try{
  let config;
  try{config=await fetch("https://raw.githubusercontent.com/719566486/yingke-aigc-studio/main/docs/connection.json?t="+Date.now(),{cache:"no-store",signal:AbortSignal.timeout(6000)}).then(r=>{if(!r.ok)throw Error();return r.json();});}
  catch(error){config=await fetch("connection.json?t="+Date.now(),{cache:"no-store"}).then(r=>{if(!r.ok)throw Error();return r.json();});}
  const url=new URL(config.url);
  if(url.protocol!=="https:"||!/(\.trycloudflare\.com|\.lhr\.life|\.localhost\.run)$/.test(url.hostname))throw Error();
  const ping=await fetch(url.origin+"/api/share/ping",{cache:"no-store",signal:AbortSignal.timeout(8000)}).then(r=>r.json());
  if(!ping.online)throw Error();
  const target=url.origin+"/#access="+encodeURIComponent(config.access);
  const enter=document.getElementById("enter");enter.href=target;enter.hidden=false;
  status.textContent="工作室已就绪";message.textContent="正在进入创作体验…";location.replace(target);
 }catch(e){status.textContent="主办方暂未开启创作服务";message.textContent="可以稍后再试，或联系主办方开启工作室。";spinner.hidden=true;retry.hidden=false;}
}
document.getElementById("retry").addEventListener("click",connect);connect();

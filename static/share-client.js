"use strict";
window.STUDIO_SHARED=true;
window.studioShareAuthReady=(async()=>{
 const status=await fetch("/api/share/status").then(r=>r.json());
 if(status.authorized)return;
 const code=new URLSearchParams(location.hash.slice(1)).get("access");
 async function login(value){
  const response=await fetch("/api/share/login",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({code:value})});
  const result=await response.json();if(!response.ok)throw new Error(result.detail||"体验码未通过");
 }
 if(code){try{await login(code);history.replaceState(null,"",location.pathname+location.search);return;}catch(e){}}
 const dialog=document.createElement("dialog");dialog.className="share-gate";
 dialog.innerHTML='<div class="eyebrow">YINGKE EXPERIENCE</div><h2>欢迎来到映刻创作体验</h2><p>输入主办方提供的体验码，就能开始你的第一支短片。</p><form><label for="shareCode">体验码</label><input id="shareCode" class="text-input" required autocomplete="off"><p class="share-error" role="alert"></p><button class="primary-button">进入创作工作室 →</button></form><small>每位访客每天可体验一次 AI 视频制作。</small>';
 document.body.append(dialog);dialog.showModal();dialog.addEventListener("cancel",e=>e.preventDefault());
 await new Promise(resolve=>dialog.querySelector("form").addEventListener("submit",async e=>{
  e.preventDefault();const button=dialog.querySelector("button");button.disabled=true;
  try{await login(dialog.querySelector("input").value.trim());dialog.close();dialog.remove();resolve();}
  catch(error){dialog.querySelector(".share-error").textContent=error.message;button.disabled=false;}
 }));
})();

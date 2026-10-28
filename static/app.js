"use strict";
const $=(id)=>document.getElementById(id);
const state={token:"",caps:{},style:"cinema",ratio:"9:16",mode:"preview",reference:null,plan:null,job:null,poll:null,busy:false,creationKey:null,creationPayload:null};
const names={zf_001:"温柔女声 · 001",zf_003:"清新女声 · 003",zm_010:"沉稳男声 · 010",zm_009:"自然男声 · 009"};
const statusNames={queued:"排队中",running:"制作中",completed:"已完成",failed:"未完成",paused:"等待继续",unknown:"待核对",cancelled:"已取消"};
const examples={cat:{brief:"一只小猫误入云端的图书馆，找到一封来自未来的信，决定把它送到星星的家里。",style:"fantasy"},city:{brief:"清晨，年轻的咖啡师推开街角小店的门，阳光洒过咖啡杯，城市在一阵香气里慢慢醒来。",style:"cinema"},ink:{brief:"一叶小舟驶入水墨山水，船上的小旅人放飞一只纸鹤，纸鹤带着晨光飞向远山。",style:"ink"}};
function esc(s){return String(s??"").replace(/[&<>"']/g,(c)=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
function toast(text){$("toast").textContent=text;$("toast").hidden=false;clearTimeout(toast.timer);toast.timer=setTimeout(()=>$("toast").hidden=true,4500);}
function showError(id,text){$(id).textContent=text||"";$(id).hidden=!text;}
async function api(path,options={}){
  const headers={"X-Studio-Token":state.token,...options.headers};
  const requestOptions={...options};delete requestOptions._retried;
  if(options.body && !(options.body instanceof FormData)){
    headers["Content-Type"]="application/json";requestOptions.body=JSON.stringify(options.body);
  }
  let response;
  try{response=await fetch(path,{...requestOptions,headers});}
  catch(e){throw new Error(window.STUDIO_SHARED?"活动工作室暂时无法连接，请稍后重新打开主办方分享的网址。":"本机服务暂时无法连接。请检查启动窗口是否仍在运行。");}
  if(!response.ok){
    let body={};try{body=await response.json();}catch(e){}
    if(response.status===403 && body.detail==="会话已更新，请刷新页面。" && !options._retried){
      const fresh=await fetch("/api/bootstrap");if(!fresh.ok)throw new Error("请刷新页面后重试。");
      state.token=(await fresh.json()).token;
      return api(path,{...options,_retried:true});
    }
    const detail=Array.isArray(body.detail)?body.detail.map(x=>x.msg).join("；"):body.detail;
    throw new Error(detail||"请求未完成，请稍后重试。");
  }
  return response.json();
}
function applyCaps(caps){
  state.caps=caps;
  $("useLlm").disabled=!caps.llm;
  $("llmHint").textContent=caps.llm?"已配置":"需配置文本模型";
  if(!caps.llm){$("useLlm").checked=false;$("llmConsentLine").hidden=true;}
  const old=$("voiceSelect").value;
  $("voiceSelect").innerHTML=(caps.voices||[]).map(v=>'<option value="'+esc(v)+'">'+esc(names[v]||v)+'</option>').join("");
  if((caps.voices||[]).includes(old))$("voiceSelect").value=old;
  $("klingModeBadge").textContent=caps.kling?"已配置 · 按次扣费":"待配置";
  $("configDot").classList.toggle("ready",caps.kling);
  $("serviceSummary").textContent=caps.tts&&caps.ffmpeg?"本地配音与合成已就绪":"本机工具需要检查";
}
function chooseStyle(style){
  state.style=style;document.querySelectorAll("[data-style]").forEach(el=>{const on=el.dataset.style===style;el.classList.toggle("selected",on);el.setAttribute("aria-pressed",on);});
}
const styleReferences={
  cinema:{title:"电影写实",description:"真人质感、自然光影与电影构图。",credit:"Tears of Steel · Blender Foundation / Project Mango",source:"https://commons.wikimedia.org/wiki/File:Tears_of_Steel_frame_00_1c.jpg",license:"CC BY 3.0",licenseUrl:"https://creativecommons.org/licenses/by/3.0/"},
  anime:{title:"清新动画",description:"柔和色彩、可爱的角色与清新的自然场景。",credit:"Spring · Blender Institute",source:"https://commons.wikimedia.org/wiki/File:SpringOpenMovie-final_scene.jpg",license:"CC BY-SA 4.0",licenseUrl:"https://creativecommons.org/licenses/by-sa/4.0/"},
  ink:{title:"东方水墨",description:"墨色层次、山水笔意与留白。",credit:"石涛《山水图》· 大都会艺术博物馆开放藏品",source:"https://www.metmuseum.org/art/collection/search/49175",license:"公有领域 / CC0",licenseUrl:"https://creativecommons.org/publicdomain/zero/1.0/"},
  fantasy:{title:"梦幻童话",description:"奇幻角色、童话世界与富有想象力的氛围。",credit:"Sintel · Blender Foundation",source:"https://commons.wikimedia.org/wiki/File:Sintel-screenshot-4.jpg",license:"CC BY 3.0",licenseUrl:"https://creativecommons.org/licenses/by/3.0/"}
};
$("openStyleReference").addEventListener("click",()=>{
  const ref=styleReferences[state.style];$("styleReferenceTitle").textContent=ref.title+" · 风格参考";
  const picture=$("styleReferenceImage");picture.src="/assets/styles/"+state.style+".jpg";picture.alt=ref.description;
  $("styleReferenceDescription").textContent=ref.description;
  $("styleReferenceCredit").innerHTML='<a href="'+ref.source+'" target="_blank" rel="noopener noreferrer">'+esc(ref.credit)+'</a> · <a href="'+ref.licenseUrl+'" target="_blank" rel="noopener noreferrer">'+esc(ref.license)+'</a> · 缩略图仅作显示裁切';
  $("styleReferenceDialog").showModal();
});
$("closeStyleReference").addEventListener("click",()=>$("styleReferenceDialog").close());
function chooseRatio(ratio){
  state.ratio=ratio;document.querySelectorAll("[data-ratio]").forEach(el=>{const on=el.dataset.ratio===ratio;el.classList.toggle("selected",on);el.setAttribute("aria-pressed",on);});
  $("previewSpec").textContent="15 秒 / "+ratio;$("previewStage").classList.toggle("landscape",ratio==="16:9");
}
function chooseMode(mode){
  if(mode==="kling"&&!state.caps.kling){openSettings();toast("先保存可灵开放平台凭证，再制作 AI 动态短片。");return;}
  state.mode=mode;$("previewMode").classList.toggle("selected",mode==="preview");$("klingMode").classList.toggle("selected",mode==="kling");$("paidConsentLine").hidden=mode!=="kling";
  $("modeHint").textContent=mode==="preview"?"本地预演使用模板画面或你的参考图，画面不由 AI 生成。":"生成会消耗可灵开放平台额度。时长取决于服务排队；若提交结果未知，平台会停止自动重提。";
  $("renderButton").querySelector("span").textContent=mode==="preview"?"生成预演短片":"生成 AI 动态短片";
}
async function uploadFile(file){
  if(!file)return;
  if(file.size>10*1024*1024){toast("图片不能超过 10 MB。");return;}
  $("planButton").disabled=true;
  try{const form=new FormData();form.append("image",file);const result=await api("/api/uploads",{method:"POST",body:form});state.reference=result.id;$("referenceThumb").src=result.url;$("referenceName").textContent=file.name;$("uploadPreview").hidden=false;$("uploadZone").hidden=true;toast("参考图已保存在本机。");}
  catch(e){toast(e.message);}
  finally{$("planButton").disabled=false;}
}
function renderPlan(plan){
  state.plan=plan;$("filmTitle").value=plan.title;$("plannerLabel").textContent=plan.planner_label||"三镜头分镜";
  $("shotList").innerHTML=plan.shots.map((s,i)=>'<article class="shot-card"><div class="shot-head"><span>0'+(i+1)+'</span><strong>'+esc(s.name)+'</strong><span>'+String(i*5).padStart(2,"0")+'—'+String((i+1)*5).padStart(2,"0")+' s</span></div><div class="shot-body"><label for="narration'+i+'">旁白 · 建议 6—18 字，最多 32 字</label><textarea id="narration'+i+'" data-narration="'+i+'" maxlength="32" rows="2">'+esc(s.narration)+'</textarea><details><summary>查看与修改画面描述</summary><label class="sr-only" for="visual'+i+'">镜头画面描述</label><textarea id="visual'+i+'" data-visual="'+i+'" maxlength="650" rows="4">'+esc(s.visual)+'</textarea></details></div></article>').join("");
  $("ideaSheet").hidden=true;$("storyboardSheet").hidden=false;$("posterTitle").textContent=plan.title;chooseRatio(plan.ratio);chooseMode("preview");showError("renderError","");
}
function readPlan(){
  const result={...state.plan,title:$("filmTitle").value.trim(),shots:state.plan.shots.map((s,i)=>({...s,narration:$("narration"+i).value.trim(),visual:$("visual"+i).value.trim()}))};
  if(!result.title)throw new Error("给短片起一个名字吧。");
  for(const s of result.shots){if(!s.narration||!s.visual)throw new Error("每个镜头都需要画面描述和旁白。");}
  return result;
}
async function generatePlan(){
  showError("formError","");const brief=$("brief").value.trim();
  if(brief.length<4){showError("formError","先写下至少 4 个字的创意，或者选择下方的灵感示例。");$("brief").focus();return;}
  if($("useLlm").checked&&!$("llmConsent").checked){showError("formError","使用 AI 编剧前，请确认向文本模型发送这段创意。");return;}
  $("planButton").disabled=true;$("planButton").querySelector("span:not(.button-icon)").textContent="正在整理故事…";
  try{const plan=await api("/api/plan",{method:"POST",body:{brief,style:state.style,ratio:state.ratio,use_llm:$("useLlm").checked,send_consent:$("llmConsent").checked}});renderPlan(plan);$("storyboardSheet").scrollIntoView({behavior:"smooth",block:"start"});}
  catch(e){showError("formError",e.message);}
  finally{$("planButton").disabled=false;$("planButton").querySelector("span:not(.button-icon)").textContent="生成三镜头分镜";}
}
async function submitVideo(){
  if(state.busy)return;showError("renderError","");
  try{
    const plan=readPlan();
    if(state.mode==="kling"&&!$("paidConsent").checked)throw new Error("请先确认本次 AI 生成的费用及素材发送。");
    const body={plan,mode:state.mode,reference_id:state.reference,voice:$("voiceSelect").value,paid_consent:state.mode==="kling"&&$("paidConsent").checked};
    const fingerprint=JSON.stringify(body);
    if(state.creationPayload!==fingerprint){state.creationKey=crypto.randomUUID();state.creationPayload=fingerprint;}
    body.idempotency=state.creationKey;state.busy=true;$("renderButton").disabled=true;
    const job=await api("/api/jobs",{method:"POST",body});state.plan=plan;showJob(job);startPolling(job.id);refreshHistory();
    document.querySelector(".preview-column").scrollIntoView({behavior:"smooth",block:"start"});
  }catch(e){showError("renderError",e.message);}
  finally{state.busy=false;$("renderButton").disabled=false;}
}
function elapsed(job){
  const end=["completed","failed","unknown","paused"].includes(job.status)?job.updated:Date.now()/1000;
  const sec=Math.max(0,Math.round(end-job.created));return Math.floor(sec/60)+" 分 "+sec%60+" 秒";
}
function showJob(job){
  state.job=job;localStorage.setItem("yingke.lastJob",job.id);
  document.querySelector(".preview-column").classList.add("show-task");
  chooseRatio(job.ratio);$("taskPanel").hidden=false;$("previewCaption").hidden=true;$("taskMode").textContent=job.mode_label;$("taskTitle").textContent=job.title;$("taskMessage").textContent=job.message;$("taskElapsed").textContent=elapsed(job);
  $("taskIdLabel").textContent="本机任务："+job.id+(job.provider_id?" · 可灵任务："+job.provider_id:"");
  const phases=["generating","voice","composing","verifying"];const current=job.status==="completed"?4:phases.indexOf(job.phase);
  document.querySelectorAll("#taskSteps li").forEach((el,i)=>{el.classList.toggle("done",i<current);el.classList.toggle("running",i===current&&job.status==="running");el.querySelector("span").textContent=i<current?"✓":String(i+1);});
  const retry=["failed","paused","unknown"].includes(job.status);$("resumeArea").hidden=!retry;$("providerTaskId").hidden=job.status!=="unknown";
  $("resumeButton").hidden=job.mode==="kling"&&job.status==="failed"&&!job.provider_id;
  $("downloadPanel").hidden=job.status!=="completed";
  if(job.status==="completed"){
    $("poster").hidden=true;const video=$("resultVideo");video.hidden=false;
    if(video.dataset.job!==job.id){video.poster=job.cover_url||"";video.src=job.video_url;video.dataset.job=job.id;video.load();}
    const base="/api/jobs/"+job.id+"/file/";
    $("downloadVideo").href=base+"video?download=true";$("downloadSrt").href=base+"subtitles?download=true";$("downloadPlan").href=base+"storyboard?download=true";$("downloadCover").href=base+"cover?download=true";
  }else{
    $("resultVideo").pause();$("resultVideo").hidden=true;$("poster").hidden=false;
    if(job.cover_url){$("posterImage").src=job.cover_url;$("posterTitle").textContent="";document.querySelector(".poster-title").hidden=true;$("posterImage").alt="当前作品分镜预演封面";}
    else{$("posterImage").src="/assets/landscape.svg";$("posterTitle").textContent=job.title;document.querySelector(".poster-title").hidden=false;}
  }
}
function stopPolling(){if(state.poll)clearInterval(state.poll);state.poll=null;}
function startPolling(id){
  stopPolling();let refreshing=false;
  const poll=async()=>{if(refreshing)return;refreshing=true;try{const job=await api("/api/jobs/"+id);showJob(job);if(["completed","failed","unknown","paused","cancelled"].includes(job.status)){stopPolling();refreshHistory();if(job.status==="completed")toast("短片已完成，可以预览和下载了。");}}catch(e){stopPolling();toast(e.message);}finally{refreshing=false;}};
  state.poll=setInterval(poll,2200);poll();
}
async function resumeJob(){
  if(!state.job)return;
  $("resumeButton").disabled=true;
  try{await api("/api/jobs/"+state.job.id+"/resume",{method:"POST",body:{provider_id:$("providerTaskId").value.trim()||null}});startPolling(state.job.id);toast("正在继续处理已有任务。");}
  catch(e){toast(e.message);}finally{$("resumeButton").disabled=false;}
}
function startNewStory(){
  stopPolling();state.plan=null;state.job=null;state.reference=null;state.creationKey=null;state.creationPayload=null;
  localStorage.removeItem("yingke.lastJob");
  $("brief").value="";$("brief").dispatchEvent(new Event("input"));$("referenceInput").value="";
  $("uploadPreview").hidden=true;$("uploadZone").hidden=false;$("ideaSheet").hidden=false;$("storyboardSheet").hidden=true;
  $("taskPanel").hidden=true;$("downloadPanel").hidden=true;$("previewCaption").hidden=false;
  $("resultVideo").pause();$("resultVideo").hidden=true;$("resultVideo").removeAttribute("src");delete $("resultVideo").dataset.job;
  $("poster").hidden=false;$("posterImage").src="/assets/landscape.svg";document.querySelector(".poster-title").hidden=false;
  $("posterTitle").textContent="山海之间，遇见故事";document.querySelector(".preview-column").classList.remove("show-task");
  $("paidConsent").checked=false;chooseMode("preview");showView("create");$("brief").focus();
}
$("newStory").addEventListener("click",startNewStory);
function showView(view){
  $("createView").hidden=view!=="create";$("historyView").hidden=view!=="history";
  $("navCreate").classList.toggle("active",view==="create");$("navHistory").classList.toggle("active",view==="history");$("breadcrumb").textContent=view==="create"?"创作工作台":"我的作品";window.scrollTo({top:0,behavior:"smooth"});
}
async function refreshHistory(){
  try{const data=await api("/api/jobs");$("historyCount").textContent=data.jobs.length;$("librarySummary").textContent=data.jobs.length+" 个故事 · "+data.jobs.filter(j=>j.status==="completed").length+" 支已完成";
    $("historyGrid").innerHTML=data.jobs.length?data.jobs.map(job=>'<article class="history-card"><img class="history-cover" data-open="'+job.id+'" src="'+esc(job.cover_url||"/assets/landscape.svg")+'" alt="'+esc(job.title)+'"><div class="history-body"><span class="status-badge '+esc(job.status)+'">'+esc(statusNames[job.status]||job.status)+'</span><h3>'+esc(job.title)+'</h3><div class="history-meta">'+esc(job.mode_label)+' · 15 秒 · '+esc(job.ratio)+'</div><div class="history-bottom"><button class="text-button" data-open="'+job.id+'">查看作品 →</button><button class="text-button danger" data-delete="'+job.id+'">删除</button></div></div></article>').join(""):'<div class="empty-state"><strong>第一支短片，等你开始</strong><p>写下一个灵感，让它拥有画面和声音。</p><button class="secondary-button" data-start>开始创作 →</button></div>';
  }catch(e){$("librarySummary").textContent=e.message;}
}
async function loadJob(id){
  try{const job=await api("/api/jobs/"+id);showView("create");if(job.payload){state.reference=job.payload.reference_id;$("voiceSelect").value=job.payload.voice;renderPlan(job.payload.plan);chooseMode(job.mode);}showJob(job);
    if(!["completed","failed","unknown","paused","cancelled"].includes(job.status))startPolling(id);
    else stopPolling();document.querySelector(".preview-column").scrollIntoView({behavior:"smooth",block:"start"});
  }catch(e){toast(e.message);}
}
async function openSettings(){
  if(window.STUDIO_SHARED){toast("服务配置由活动主办方管理。请联系主办方检查生成服务。");return;}
  showError("settingsError","");$("settingsMessage").textContent="";$("settingsDialog").showModal();
  try{const data=await api("/api/settings");applyCaps(data.capabilities);const form=$("settingsForm");
    Object.entries(data.settings).forEach(([k,v])=>{if(form.elements.namedItem(k))form.elements.namedItem(k).value=v;});
    ["kling_api_key","kling_access_key","kling_secret_key","llm_key"].forEach(k=>{form.elements.namedItem(k).value="";form.elements.namedItem(k).placeholder=data.settings[k+"_configured"]?"已保存；留空保留原值":"尚未配置";});
    $("diagnostics").innerHTML=[["ffmpeg","视频合成"],["tts","本地配音"],["kling","可灵凭证"]].map(([key,label])=>'<div class="diagnostic '+(data.capabilities[key]?"ready":"")+'"><i></i>'+label+' · '+(data.capabilities[key]?"已就绪":"待配置")+'</div>').join("");
    $("storageLocation").textContent="文件保存在："+data.capabilities.data_directory+"。配音复用现有 D 盘 Kokoro 环境。";
  }catch(e){showError("settingsError",e.message);}
}
async function saveSettings(event,clear=false){
  if(event)event.preventDefault();showError("settingsError","");$("settingsMessage").textContent="";$("saveSettings").disabled=true;
  try{const body=Object.fromEntries(new FormData($("settingsForm")).entries());["daily_limit","retention_hours"].forEach(k=>body[k]=Number(body[k]));
    if(clear)["kling_api_key","kling_access_key","kling_secret_key","llm_key"].forEach(k=>body[k]="__DELETE__");
    const data=await api("/api/settings",{method:"PUT",body});applyCaps(data.capabilities);
    ["kling_api_key","kling_access_key","kling_secret_key","llm_key"].forEach(k=>$("settingsForm").elements.namedItem(k).value="");
    $("settingsMessage").textContent=clear?"本机已存凭证已清除。":"配置已保存。可先检查可灵认证，再提交 AI 视频。";toast("服务配置已保存。");
    if(!state.caps.kling)chooseMode("preview");
  }catch(e){showError("settingsError",e.message);}finally{$("saveSettings").disabled=false;}
}
$("brief").addEventListener("input",()=>{$("briefCount").textContent=$("brief").value.length+" / 300";});
document.querySelectorAll("[data-style]").forEach(el=>el.addEventListener("click",()=>chooseStyle(el.dataset.style)));
document.querySelectorAll("[data-ratio]").forEach(el=>el.addEventListener("click",()=>chooseRatio(el.dataset.ratio)));
document.querySelectorAll("[data-example]").forEach(el=>el.addEventListener("click",()=>{const ex=examples[el.dataset.example];$("brief").value=ex.brief;$("brief").dispatchEvent(new Event("input"));chooseStyle(ex.style);$("ideaSheet").hidden=false;$("storyboardSheet").hidden=true;$("brief").focus();$("ideaSheet").scrollIntoView({behavior:"smooth",block:"start"});toast("灵感已填入，试着加一点自己的想法。");}));
$("referenceInput").addEventListener("change",e=>uploadFile(e.target.files[0]));
$("uploadZone").addEventListener("dragover",e=>{e.preventDefault();$("uploadZone").classList.add("dragging");});
$("uploadZone").addEventListener("dragleave",()=>$("uploadZone").classList.remove("dragging"));
$("uploadZone").addEventListener("drop",e=>{e.preventDefault();$("uploadZone").classList.remove("dragging");uploadFile(e.dataTransfer.files[0]);});
$("removeReference").addEventListener("click",()=>{state.reference=null;$("referenceInput").value="";$("uploadPreview").hidden=true;$("uploadZone").hidden=false;});
$("useLlm").addEventListener("change",()=>$("llmConsentLine").hidden=!$("useLlm").checked);
$("planButton").addEventListener("click",generatePlan);$("renderButton").addEventListener("click",submitVideo);
$("previewMode").addEventListener("click",()=>chooseMode("preview"));$("klingMode").addEventListener("click",()=>chooseMode("kling"));
$("editIdea").addEventListener("click",()=>{$("ideaSheet").hidden=false;$("storyboardSheet").hidden=true;$("ideaSheet").scrollIntoView({behavior:"smooth"});});
$("navCreate").addEventListener("click",()=>showView("create"));$("navHistory").addEventListener("click",()=>{showView("history");refreshHistory();});
$("navSettings").addEventListener("click",openSettings);$("closeSettings").addEventListener("click",()=>$("settingsDialog").close());
$("helpButton").addEventListener("click",()=>$("helpDialog").showModal());$("closeHelp").addEventListener("click",()=>$("helpDialog").close());
$("settingsForm").addEventListener("submit",saveSettings);
$("clearKeys").addEventListener("click",()=>{if(confirm("清除本机保存的可灵及文本模型凭证？"))saveSettings(null,true);});
$("testKling").addEventListener("click",async()=>{showError("settingsError","");$("settingsMessage").textContent="正在检查已保存的凭证…";$("testKling").disabled=true;try{const r=await api("/api/settings/check-kling",{method:"POST"});$("settingsMessage").textContent=r.message;}catch(e){$("settingsMessage").textContent="";showError("settingsError",e.message);}finally{$("testKling").disabled=false;}});
$("resumeButton").addEventListener("click",resumeJob);$("refreshHistory").addEventListener("click",refreshHistory);
$("historyGrid").addEventListener("click",async e=>{const open=e.target.closest("[data-open]");if(open){loadJob(open.dataset.open);return;}if(e.target.closest("[data-start]")){startNewStory();return;}const remove=e.target.closest("[data-delete]");if(remove&&confirm("删除这个任务和本机成片？")){try{await api("/api/jobs/"+remove.dataset.delete,{method:"DELETE"});refreshHistory();}catch(error){toast(error.message);}}});
async function init(){try{const data=await api("/api/bootstrap");state.token=data.token;applyCaps(data.capabilities);await refreshHistory();const linked=new URLSearchParams(location.search).get("job");if(linked&&/^[a-f0-9]{32}$/.test(linked)){await loadJob(linked);return;}const last=localStorage.getItem("yingke.lastJob");if(last){try{const job=await api("/api/jobs/"+last);if(["queued","running","paused"].includes(job.status)){showJob(job);if(job.status!=="paused")startPolling(job.id);}}catch(e){localStorage.removeItem("yingke.lastJob");}}}catch(e){showError("formError",e.message);$("serviceSummary").textContent="本机服务未连接";}}
async function startStudio(){if(window.studioShareAuthReady)await window.studioShareAuthReady;await init();}
startStudio().catch(e=>showError("formError",e.message));

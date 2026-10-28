"use strict";
window.STUDIO_SHARED=true;
window.studioShareAuthReady=(async()=>{
 const response=await fetch("/api/share/start",{method:"POST",credentials:"same-origin"});
 const result=await response.json();
 if(!response.ok)throw new Error(result.detail||"工作室暂时无法连接，请稍后刷新页面。");
 // Old shared links may still carry an access fragment; it is no longer needed.
 if(new URLSearchParams(location.hash.slice(1)).has("access")){
  history.replaceState(null,"",location.pathname+location.search);
 }
})();

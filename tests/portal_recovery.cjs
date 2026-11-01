const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict');
const source=fs.readFileSync('docs/portal.js','utf8');
async function run(mode){
 const nodes=Object.fromEntries(['status','message','retry','spinner','enter'].map(k=>[k,{hidden:true,addEventListener(){}}]));
 let redirected=null;
 const context={URL,AbortController,Promise,Date,Error,setTimeout:()=>1,clearTimeout(){},
  document:{getElementById:k=>nodes[k]},location:{replace:u=>redirected=u},
  fetch:async u=>{
   if(u.includes('connection.json'))return {ok:true,json:async()=>({url:mode==='invalid'?'https://attacker.example/':u.startsWith('https:')?'https://old.lhr.life':'https://current.lhr.life'})};
   if(mode==='blocked')throw Error('CORS/network');
   return {ok:true,json:async()=>({online:mode==='healthy'&&u.includes('current.lhr.life')})};
  }};
 vm.runInNewContext(source,context);
 for(let i=0;i<10;i++)await new Promise(resolve=>setImmediate(resolve));
 return {nodes,redirected};
}
(async()=>{
 let v=await run('healthy');assert.equal(v.redirected,null);assert.equal(v.nodes.enter.href,'https://current.lhr.life/');assert.match(v.nodes.enter.textContent,/开始创作/);
 v=await run('blocked');assert.equal(v.redirected,null);assert.equal(v.nodes.enter.hidden,false);assert.match(v.nodes.message.textContent,/页面仍可浏览/);
 v=await run('invalid');assert.equal(v.redirected,null);assert.equal(v.nodes.enter.hidden,true);
 v=await run('offline');assert.equal(v.redirected,null);assert.match(v.nodes.message.textContent,/工作室离线/);
 console.log('4 portal recovery checks passed');
})().catch(e=>{console.error(e);process.exitCode=1});

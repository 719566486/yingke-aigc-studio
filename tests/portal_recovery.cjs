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
 let v=await run('healthy');assert.equal(v.redirected,'https://current.lhr.life/');
 v=await run('blocked');assert.equal(v.redirected,null);assert.equal(v.nodes.enter.hidden,false);assert.match(v.nodes.status.textContent,/无法连接/);
 v=await run('invalid');assert.equal(v.redirected,null);assert.equal(v.nodes.enter.hidden,true);
 v=await run('offline');assert.equal(v.redirected,null);assert.match(v.nodes.message.textContent,/后台可能离线/);
 console.log('4 portal recovery checks passed');
})().catch(e=>{console.error(e);process.exitCode=1});

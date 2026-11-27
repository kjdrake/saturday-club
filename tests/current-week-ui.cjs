const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict');
const elements=new Map(),storage=new Map(),calls=[];const el=s=>{if(!elements.has(s))elements.set(s,{innerHTML:'',textContent:'',style:{},value:'',hidden:false,disabled:false,addEventListener(type,fn){this[type]=fn},setAttribute(){},removeAttribute(){},showModal(){this.open=true},close(){this.open=false},focus(){},querySelectorAll:()=>[]});return elements.get(s)};
let handler=async()=>({ok:false,status:401,json:async()=>({error:'Sign in required'})});
const location={href:'https://4thandsoul.com/#picks',search:'',hash:'#picks'};
const listeners={};
const context={document:{documentElement:{dataset:{serverBacked:'true'}},querySelector:el,querySelectorAll:()=>[]},location,window:{addEventListener:(type,fn)=>listeners[type]=fn,history:{replaceState(_s,_t,path){const u=new URL(path,location.href);Object.assign(location,{href:u.href,search:u.search,hash:u.hash})}}},sessionStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},localStorage:{getItem:()=>null},AbortController,setTimeout:()=>1,clearTimeout(){},setInterval(){},URL,Blob,console,fetch:async(url,options)=>{if(url==='/api/auth/providers')return response(200,{providers:[]});calls.push({url,options});if(url==='/api/current-period')return response(200,{season:2028,week:7});return handler(url,options)}};
const response=(status,data)=>({ok:status>=200&&status<300,status,json:async()=>JSON.parse(JSON.stringify(data))});
vm.createContext(context);vm.runInContext(fs.readFileSync('dist/app.js','utf8'),context);const run=code=>vm.runInContext(code,context);

(async()=>{
 await new Promise(setImmediate);
 assert.equal(run('season'),2028);assert.equal(run('week'),7);
 assert.equal(calls[0].url,'/api/current-period');
 assert(calls.some(call=>call.url.includes('state?season=2028&week=7')));
 for(const [date,expected] of [
   ['2026-08-31T18:00:00Z',{season:2026,week:1}],
   ['2026-09-01T18:00:00Z',{season:2026,week:2}],
   ['2026-11-24T05:59:00Z',{season:2026,week:13}],
   ['2026-11-24T06:00:00Z',{season:2026,week:14}],
   ['2027-01-10T18:00:00Z',{season:2026,week:18}],
   ['2027-03-01T18:00:00Z',{season:2027,week:1}]]){
   assert.deepEqual(JSON.parse(run('JSON.stringify(calendarPeriod(new Date('+JSON.stringify(date)+')))')),expected);
 }
 calls.length=0;
 Object.assign(location,{href:'https://4thandsoul.com/?season=2025&week=4#picks',search:'?season=2025&week=4'});
 await run('initializePeriod()');
 assert.equal(run('season'),2025);assert.equal(run('week'),4);
 assert(!calls.some(call=>call.url==='/api/current-period'));
 assert(calls.some(call=>call.url.includes('state?season=2025&week=4')));
 storage.set('sc-return-week',JSON.stringify({season:2025,week:6}));
 Object.assign(location,{href:'https://4thandsoul.com/?auth_success=1',search:'?auth_success=1'});
 assert.equal(run('readWeekLink()'),true);assert.equal(run('week'),6);
 calls.length=0;
 Object.assign(location,{href:'https://4thandsoul.com/',search:''});
 await run('initializePeriod()');
 assert.equal(run('season'),2028);assert.equal(run('week'),7);
 assert(calls.some(call=>call.url==='/api/current-period'));
 console.log('Current week startup, Central-time rollover, links and sign-in return passed');
})().catch(error=>{console.error(error);process.exitCode=1});

// Run the real sign-in submit handler against controlled API responses.
const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict');
function harness(){
  const elements=new Map(),calls=[];
  const el=selector=>{
    if(!elements.has(selector))elements.set(selector,{
      innerHTML:'',textContent:'',style:{},value:'2026 season',hidden:true,disabled:false,
      addEventListener(type,handler){this[type]=handler},setAttribute(key,value){this[key]=value},removeAttribute(key){delete this[key]},
      showModal(){this.open=true},close(){this.open=false},focus(){this.focused=true}
    });
    return elements.get(selector);
  };
  const form=el('#loginForm');form.elements={email:{value:' admin@example.com '},password:{value:'test-password-123'},code:{value:'',addEventListener(){}}};
  let handler=async()=>({ok:false,status:401,json:async()=>({error:'Sign in required'})});
  const context={document:{querySelector:el,querySelectorAll:()=>[]},localStorage:{getItem:()=>null},location:{hash:''},window:{},AbortController,
    FormData:class {constructor(form){this.form=form}*[Symbol.iterator](){for(const[key,input]of Object.entries(this.form.elements))yield[key,input.value]}},
    setTimeout:()=>1,clearTimeout(){},setInterval(){},URL,Blob,crypto:require('node:crypto').webcrypto,
    fetch:async(url,options)=>{calls.push({url,options});return handler(url,options)},console};
  vm.createContext(context);vm.runInContext(fs.readFileSync('dist/app.js','utf8'),context);
  return {el,form,calls,run:code=>vm.runInContext(code,context),setHandler:next=>handler=next};
}
const response=(status,data)=>({ok:status>=200&&status<300,status,json:async()=>data});
const state={user:{id:'admin',name:'Test Admin',role:'admin'},games:[],picks:{},standings:[],members:[],seasons:[2026]};
async function ready(){const h=harness();await new Promise(setImmediate);h.run('demo=false;user=null;accountModal()');h.calls.length=0;return h}
const submit=h=>h.form.submit({preventDefault(){}});
(async()=>{
  {
    const h=await ready();h.setHandler(async()=>response(401,{error:'Incorrect email or password'}));await submit(h);
    assert.equal(h.el('#modal').open,true);assert.equal(h.el('#loginError').hidden,false);
    assert.equal(h.el('#loginError').textContent,'Incorrect email or password');assert(h.el('#loginError').focused);
    assert.equal(h.el('#loginSubmit').disabled,false);assert.equal(h.calls.length,1);
    assert(h.el('#modalBody').innerHTML.includes('role="alert"'));assert(h.el('#modalBody').innerHTML.includes('id="loginError"'));
  }
  {
    const h=await ready();let finish;h.setHandler((url)=>url==='/api/login'?new Promise(resolve=>finish=resolve):Promise.resolve(response(200,state)));
    const pending=submit(h);assert.equal(h.el('#loginSubmit').disabled,true);assert.equal(h.el('#loginStatus').textContent,'Signing in…');
    await submit(h);assert.equal(h.calls.length,1,'Duplicate submit sent multiple logins');
    finish(response(200,{ok:true}));await pending;
    assert.equal(h.el('#modal').open,false);assert.equal(h.el('#loginSubmit').disabled,false);
    assert(h.el('#profileName').innerHTML.includes('Test Admin'));
    assert.equal(JSON.parse(h.calls[0].options.body).email,'admin@example.com');
  }
  {
    const h=await ready();h.setHandler(async url=>url==='/api/login'?response(200,{ok:true}):response(401,{error:'Sign in required'}));await submit(h);
    assert.equal(h.el('#modal').open,true);assert.match(h.el('#loginError').textContent,/allow cookies/);
  }
  for(const [error,message]of [[new TypeError('Failed to fetch'),/Check your connection/],[Object.assign(new Error('aborted'),{name:'AbortError'}),/timed out/]]){
    const h=await ready();h.setHandler(async()=>{throw error});await submit(h);
    assert.equal(h.el('#loginError').hidden,false);assert.match(h.el('#loginError').textContent,message);assert.equal(h.el('#loginSubmit').disabled,false);
  }
  {
    const h=await ready();h.setHandler(async()=>({ok:false,status:502,json:async()=>{throw SyntaxError('HTML response')}}));await submit(h);
    assert.match(h.el('#loginError').textContent,/unexpected response/);assert.equal(h.el('#modal').open,true);
  }
  {
    const h=await ready();h.form.elements.code.value=' invite-code ';h.setHandler(async url=>url==='/api/register'?response(200,{ok:true}):response(200,state));await submit(h);
    assert.equal(h.calls[0].url,'/api/register');assert.equal(JSON.parse(h.calls[0].options.body).code,'invite-code');assert.equal(h.el('#modal').open,false);
  }
  console.log('Sign-in regression checks passed: visible errors, pending state, duplicate prevention, success, cookie failure, network failure, timeout, invalid response, and registration.');
})().catch(error=>{console.error(error);process.exitCode=1});

// Exercise actual render and action handlers without requiring a browser.
const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict');
const elements=new Map();const el=s=>{if(!elements.has(s))elements.set(s,{innerHTML:'',textContent:'',style:{},value:'2026 season',addEventListener(type,fn){this[type]=fn},showModal(){this.open=true},close(){this.open=false}});return elements.get(s)};
const store=new Map();const context={document:{querySelector:el,querySelectorAll:()=>[],createElement:()=>({click(){}})},localStorage:{getItem:k=>store.get(k)||null,setItem:(k,v)=>store.set(k,v)},location:{hash:''},window:{},setTimeout:()=>1,clearTimeout(){},setInterval(){},fetch:async()=>{throw Error('Static demo')},URL,Blob,crypto:require('node:crypto').webcrypto,console};
vm.createContext(context);vm.runInContext(fs.readFileSync('dist/teams.js','utf8'),context);vm.runInContext(fs.readFileSync('dist/app.js','utf8'),context);
const run=s=>vm.runInContext(s,context);
assert(el('#app').innerHTML.includes('Every pick. Every Saturday.'));
run("picks['1']='away';render()");assert(el('#app').innerHTML.includes('Unsaved selection'));assert(el('#app').innerHTML.includes('data-pick="1:away"'));
el('#savePicks').click();assert.equal(JSON.parse(store.get('sc-picks'))['1'],'away');
for(const [hash,text] of [['scores','Saturday, in motion.'],['standings','The bragging rights board.'],['history','Seasons end. Stories don’t.'],['admin','Behind the Saturday magic.']]){context.location.hash="#"+hash;run('render()');assert(el('#app').innerHTML.includes(text))}
run('demo=false;user=null;render()');assert(el('#app').innerHTML.includes('Sign in / Join the league'));
console.log('UI render, pick save, navigation, and sign-in checks passed.');

assert(run("teamBadge({awayId:251,away:'Texas'},'away')").includes('assets/team-logos/251.png'));
assert(run("teamBadge({away:'Texas A&M'},'away')").includes('assets/team-logos/245.png'));
assert(run("teamBadge({away:'Unknown College'},'away')").includes('logo-missing'));
assert(!run("teamBadge({away:'Unknown College'},'away')").includes('undefined.png'));
console.log('Team logos resolve feed IDs, manual school names, and missing-team fallbacks.');

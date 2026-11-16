const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict');
const elements=new Map();const el=s=>{if(!elements.has(s))elements.set(s,{innerHTML:'',textContent:'',style:{},value:'2026 season',addEventListener(type,fn){this[type]=fn},showModal(){this.open=true},close(){this.open=false},focus(){},setSelectionRange(){}});return elements.get(s)};
const context={document:{querySelector:el,querySelectorAll:()=>[]},localStorage:{getItem:()=>null,setItem(){}},location:{hash:'#admin'},window:{},AbortController,setTimeout:()=>1,clearTimeout(){},setInterval(){},fetch:async()=>{throw Error('Preview')},URL,Blob,crypto:require('node:crypto').webcrypto,console};
vm.createContext(context);vm.runInContext(fs.readFileSync('dist/teams.js','utf8'),context);vm.runInContext(fs.readFileSync('dist/app.js','utf8'),context);
const run=s=>vm.runInContext(s,context),ids=()=>JSON.parse(run('JSON.stringify(filteredSlateGames().map(g=>g.id))'));
const fixture=[
 ['sec','Texas','Georgia','SEC','SEC',3,5,-3.5,false,false,'scheduled'],
 ['bigten','Michigan','Ohio State','Big Ten','Big Ten',18,2,-10.5,false,false,'scheduled'],
 ['cross','Clemson','Alabama','ACC','SEC',null,8,6.5,false,false,'scheduled'],
 ['one-ranked','Oregon','Wisconsin','Big Ten','Big Ten',1,99,14.5,false,false,'scheduled'],
 ['no-line','Other Team','Another Team',null,null,null,null,null,false,false,'scheduled'],
 ['protected','Florida','Tennessee','SEC','SEC',null,null,7.5,true,true,'scheduled'],
 ['started','LSU','Arkansas','SEC','SEC',null,null,3.5,false,false,'live']
].map(([id,away,home,awayConference,homeConference,awayRank,homeRank,spread,included,hasPicks,status],i)=>({id,away,home,awayConference,homeConference,awayRank,homeRank,spread,included,hasPicks,status,kickoff:new Date(Date.now()+86400000+i*1000).toISOString()}));
(async()=>{
 await new Promise(setImmediate);
 run(`demo=true;user={id:'admin',role:'admin'};games=${JSON.stringify(fixture)};slateDraft=null;render()`);
 run("slateFilters.conference='SEC'");assert.deepEqual(ids(),['sec','cross','protected','started']);
 run('slateFilters.conferenceOnly=true');assert.deepEqual(ids(),['sec','protected','started']);
 run("slateFilters.ranking='both'");assert.deepEqual(ids(),['sec']);
 assert.equal(run('isRanked(99)'),false);assert.equal(run('isRanked(null)'),false);
 run('setSlateSelection(filteredSlateGames().map(g=>g.id),true)');assert.equal(run('slateDraft.items.sec.included'),true);
 run("slateFilters.conference='Big Ten';slateFilters.ranking='all'");assert.deepEqual(ids(),['bigten','one-ranked']);
 run('setSlateSelection(filteredSlateGames().map(g=>g.id),true)');assert.equal(run('slateDraft.items.sec.included'),true,'Filtering lost a hidden selection');
 assert.equal(run('slateDraft.items.bigten.included'),true);assert.equal(run('slateDraft.items.cross.included'),false);
 assert.equal(run("setSlateSelection(['protected'],false)"),0);assert.equal(run('slateDraft.items.protected.included'),true);
 assert.equal(run("setSlateSelection(['started'],true)"),0);assert.equal(run("setSlateSelection(['no-line'],true)"),0);
 run("slateDraft.items['no-line'].spread=1000");assert.equal(run('slateHasInvalidSpread()'),true);
 run("slateDraft.items['no-line'].spread=4.5");assert.equal(run('slateHasInvalidSpread()'),false);assert.equal(run("setSlateSelection(['no-line'],true)"),1);
 run("slateFilters={search:'Georgia',conference:'all',ranking:'all',conferenceOnly:false,view:'selected'}");assert.deepEqual(ids(),['sec']);
 assert.equal(run('slateChanges().length'),4);
 run("slateFilters={search:'',conference:'all',ranking:'both',conferenceOnly:false,view:'all'}");assert.deepEqual(ids(),['sec','bigten']);
 run("slateFilters.ranking='ranked'");assert.deepEqual(ids(),['sec','bigten','cross','one-ranked']);
 run("games.push({id:'fresh',away:'New',home:'Game',spread:3,included:false,status:'scheduled',kickoff:new Date(Date.now()+86400000).toISOString()});ensureSlateDraft()");
 assert.equal(run('slateDraft.items.sec.included'),true,'Feed refresh lost draft');assert.equal(run('slateDraft.items.fresh.included'),false);
 run('week=13;ensureSlateDraft()');assert.equal(run('slateHasChanges()'),false);assert.equal(run('slateFilters.ranking'),'all');
 console.log('Slate UI checks passed: conference/ranking filters, bulk selection, hidden drafts, missing lines, protected games, refresh and week isolation.');
})().catch(e=>{console.error(e);process.exitCode=1});

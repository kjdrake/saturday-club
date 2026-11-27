// Real browser regression: records and projected totals must fit on phones.
const assert=require('node:assert/strict');
const http=require('node:http'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright');
(async()=>{
 const root=path.resolve('dist');
 const server=http.createServer((req,res)=>{
  const file=path.resolve(root,'.'+new URL(req.url,'http://localhost').pathname.replace(/\/$/,'/index.html'));
  if(!file.startsWith(root+path.sep)||!fs.existsSync(file)){res.writeHead(404);return res.end()}
  res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':file.endsWith('.html')?'text/html':'application/octet-stream');res.end(fs.readFileSync(file));
 });
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 let browser;
 try{
  browser=await chromium.launch({headless:true});const page=await browser.newPage({isMobile:true,hasTouch:true,deviceScaleFactor:2,userAgent:'Mozilla/5.0 (Linux; Android 16) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Mobile Safari/537.36'});
  // Geometry fixtures are static: background polling would replace them with the mocked 401.
  await page.addInitScript(()=>{window.setInterval=()=>0});
  await page.route('**/api/**',route=>route.fulfill({status:401,contentType:'application/json',body:'{"error":"Sign in required"}'}));
  await page.goto(`http://127.0.0.1:${server.address().port}/#standings`);
  await page.waitForFunction(()=>!demo&&!user);
  await page.evaluate(()=>{
   demo=false;user={id:'5',name:'Longi',role:'admin'};week=13;season=2026;
   standings=['Buck','Cordie','DeMarko','Kahlin','Kevin','Longi','Mario','A very long member nickname that should wrap without overflow'].map((name,i)=>({id:String(i),name,rank:1,wins:3,losses:1,pushes:1,points:3.5}));
   weeklyStandings=standings.map(row=>({...row,wins:0,losses:0,pushes:0,points:0}));
   weeklyLiveBoard={rows:weeklyStandings.map(row=>({...row,projectedPoints:1,livePoints:1,livePicks:2,liveWins:1})),activeGames:2};
   const base={away:'Minnesota Golden Gophers',home:'Wisconsin Badgers',awayAbbr:'MINN',homeAbbr:'WIS',awayId:135,homeId:275,awayRecord:'6–5',homeRecord:'7–4',spread:-7.5,included:true,network:'ESPN / ABC College Football',bookmaker:'DraftKings',venue:'Camp Randall Stadium',venueCity:'Madison, WI',kickoff:new Date(Date.now()+86400000).toISOString()};
   games=[{...base,id:'open',status:'scheduled'},{...base,id:'live',status:'live',kickoff:new Date(Date.now()-3600000).toISOString(),away:'Nebraska Cornhuskers',home:'Iowa Hawkeyes',awayAbbr:'NEB',homeAbbr:'IOWA',awayScore:7,homeScore:31,homeId:2294,awayId:158,period:'Q4 · 0:24',possessionId:2294,downDistance:'4th & 12',fieldPosition:'IOWA 13',lastPlay:'(01:00) #26 X. Williams rush middle for 1 yard loss to the IOWA13 (#42 D. Wacker).',homeTimeouts:0,awayTimeouts:0},{...base,id:'final',status:'final',homeScore:21,awayScore:24}];
   picks={open:'home',live:'home',final:'away'};saved={...picks};members=standings.map(row=>({...row,active:true,role:row.id===user.id?'admin':'member'}));
   lockedPicks={live:{home:members.map(m=>({id:m.id,name:m.name})),away:[],none:[]}};
   pickSubmissions={gameCount:3,firstKickoff:Date.now()/1000-3600,firstGameStarted:true,members:members.map(m=>({...m,savedCount:3,lastSavedAt:Date.now()/1000-86400}))};
   liveBoard={rows:standings.map(row=>({...row,projectedPoints:4.5,livePoints:1,livePicks:2,liveWins:1})),activeGames:2,updatedAt:new Date().toISOString()};render();
  });
  fs.mkdirSync('layout-screenshots',{recursive:true});
  for(const width of [320,360,393,430,768,1024,1440]){
   await page.setViewportSize({width,height:900});
   for(const mode of ['live','final']){
    await page.evaluate(mode=>{leaderboardMode=mode;render()},mode);
    const geometry=await page.evaluate(()=>({width:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth,cards:getComputedStyle(document.querySelector('.standings-mobile-list')).display,table:getComputedStyle(document.querySelector('.leaderboard-table-wrap')).display,overflows:[...document.querySelectorAll('.standings-mobile-row')].filter(el=>el.scrollWidth>el.clientWidth).length}));
    assert(geometry.scroll<=geometry.width,`Page overflow at ${width} (${mode}): ${JSON.stringify(geometry)}`);
    assert.equal(geometry.overflows,0,`Card overflow at ${width}`);
    assert.equal(geometry.cards,width<=1100?'block':'none');
    assert.equal(geometry.table,width<=1100?'none':'block');
    if(width<=1100){
     const card=page.locator('.standings-mobile-row').first();
     await assert.doesNotReject(()=>card.getByText('0–0–0',{exact:true}).waitFor({state:'visible'}));
     await card.locator('.standings-mobile-points strong').scrollIntoViewIfNeeded();
     assert(await card.locator('.standings-mobile-points strong').isVisible());
    }
    if(width===393||width===1440)await page.screenshot({path:`layout-screenshots/standings-${width}-${mode}.png`,fullPage:true});
   }
  }
  for(const width of [320,360,393,430,580,581,768,1024,1440]){
   await page.setViewportSize({width,height:900});
   for(const tab of ['picks','scores','standings','history','admin']){
    await page.evaluate(tab=>{location.hash='#'+tab;pickSaveError='';savingPicks=false;picks={...saved};render()},tab);
    const inspect=()=>page.evaluate(()=>{
     const w=document.documentElement.clientWidth;
     const bad=[...document.querySelectorAll('header,footer,nav,main,.heading,.admin-panel,.game-body,.game-meta,.game-note,.game-pick-summary,.team,.pick,.savebar,.standings-mobile-row')].filter(el=>el.getClientRects().length&&el.scrollWidth>el.clientWidth+1).map(el=>({element:el.className||el.tagName,width:el.clientWidth,scroll:el.scrollWidth}));
     return {width:w,scroll:document.documentElement.scrollWidth,bad};
    });
    let geometry=await inspect();
    assert(geometry.scroll<=geometry.width+1,`Page overflow at ${width} on ${tab}: ${JSON.stringify(geometry)}`);
    assert.deepEqual(geometry.bad,[],`Content clipped at ${width} on ${tab}: ${JSON.stringify(geometry.bad)}`);
    assert.equal(await page.locator('.savebar').count(),0,'Saved picks must not leave an overlay');
    if(width===393){await page.evaluate(()=>scrollTo(0,0));await page.screenshot({path:`layout-screenshots/mobile-${tab}.png`,fullPage:true})}
    if(tab==='picks'){
     await page.evaluate(()=>{picks.open='away';render()});
     assert.equal(await page.locator('.savebar').count(),1,'Unsaved picks still need Save picks');
     geometry=await inspect();assert.deepEqual(geometry.bad,[],`Save bar clips at ${width}: ${JSON.stringify(geometry.bad)}`);
     assert(geometry.scroll<=geometry.width+1);
    }
   }
  }
  console.log('Standings layout fits 320–1440px in live and final modes, including long names.');
 }finally{if(browser)await browser.close();await new Promise(resolve=>server.close(resolve))}
})().catch(error=>{console.error(error);process.exitCode=1});

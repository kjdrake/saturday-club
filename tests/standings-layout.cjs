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
  browser=await chromium.launch({headless:true});const page=await browser.newPage();
  await page.route('**/api/**',route=>route.fulfill({status:401,contentType:'application/json',body:'{"error":"Sign in required"}'}));
  await page.goto(`http://127.0.0.1:${server.address().port}/#standings`);
  await page.waitForFunction(()=>!demo&&!user);
  await page.evaluate(()=>{
   demo=false;user={id:'5',name:'Longi',role:'admin'};week=13;season=2026;
   standings=['Buck','Cordie','DeMarko','Kahlin','Kevin','Longi','Mario','A very long member nickname that should wrap without overflow'].map((name,i)=>({id:String(i),name,rank:1,wins:3,losses:1,pushes:1,points:3.5}));
   weeklyStandings=standings.map(row=>({...row,wins:0,losses:0,pushes:0,points:0}));
   weeklyLiveBoard={rows:weeklyStandings.map(row=>({...row,projectedPoints:1,livePoints:1,livePicks:2,liveWins:1})),activeGames:2};
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
  console.log('Standings layout fits 320–1440px in live and final modes, including long names.');
 }finally{if(browser)await browser.close();await new Promise(resolve=>server.close(resolve))}
})().catch(error=>{console.error(error);process.exitCode=1});

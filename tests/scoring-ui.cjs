// Exercise real score-change detection, rendering and expiry with a controlled clock.
const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict');
let now=Date.now();const elements=new Map(),timers=new Map();let timerId=0;
const el=selector=>{if(!elements.has(selector))elements.set(selector,{innerHTML:'',textContent:'',style:{},value:'2026 season',addEventListener(){},showModal(){},close(){}});return elements.get(selector)};
const context={document:{querySelector:el,querySelectorAll:()=>[]},localStorage:{getItem:()=>null},location:{hash:'#scores'},window:{},Date:class extends Date{static now(){return now}},AbortController,URL,Blob,
 setTimeout(callback,delay){const id=++timerId;timers.set(id,{callback,delay});return id},clearTimeout(id){timers.delete(id)},setInterval(){},fetch:async()=>{throw Error('Offline fixture')},console};
vm.createContext(context);vm.runInContext(fs.readFileSync('dist/app.js','utf8'),context);
const run=code=>vm.runInContext(code,context),snapshot=value=>JSON.stringify(value);
const base={id:'score',away:'Texas',home:'Georgia',awayAbbr:'TEX',homeAbbr:'UGA',status:'live',included:true,spread:-3.5,awayScore:14,homeScore:21,kickoff:new Date(now-3600000).toISOString()};
function baseline(game=base){run(`clearScoringEvents();demo=false;games=[${snapshot(game)}];liveBoard={rows:[],activeGames:1};saved={score:'away'};picks={score:'away'}`)}
function receive(game){run(`markLiveChanges({rows:[],activeGames:1},[${snapshot(game)}]);games=[${snapshot(game)}]`)}
(async()=>{
 await new Promise(setImmediate);
 baseline();assert.equal(run('scoringNotice(games[0])'),'','Initial scores generated an event');
 receive({...base,awayScore:21});let card=run('gameCard(games[0],true)');
 assert(card.includes('Score update'));assert(card.includes('Texas +7'));assert(card.includes('team-just-scored'));assert(card.includes('scoring-flash'));assert(!card.includes('Touchdown'),'A score delta invented a play type');
 const firstAnnouncement=el('#scoreAnnouncements').textContent,firstExpiry=run("activeScoringEvent('score').expiresAt");
 assert(firstAnnouncement.includes('Score update: Texas +7'));assert(firstAnnouncement.includes('Score 21 to 21'));
 now+=5000;receive({...base,awayScore:21});card=run('gameCard(games[0],true)');
 assert(card.includes('Texas +7'));assert(!card.includes('scoring-flash'),'Unchanged polls restarted the animation');assert.equal(run("activeScoringEvent('score').expiresAt"),firstExpiry);assert.equal(el('#scoreAnnouncements').textContent,firstAnnouncement);
 now+=25001;run('expireScoringEvents()');assert.equal(run("activeScoringEvent('score')"),null);assert.equal(run('scoringNotice(games[0])'),'');
 baseline();receive({...base,homeScore:24});assert(run('gameCard(games[0],true)').includes('Georgia +3'));
 baseline();receive({...base,awayScore:21,homeScore:24});assert(run('scoringNotice(games[0])').includes('Texas +7 · Georgia +3'));
 baseline();receive({...base,homeScore:20});card=run('gameCard(games[0],true)');assert(card.includes('Score correction'));assert(card.includes('Georgia -1'));assert(!card.includes('team-just-scored'));assert(!card.includes('scoring-flash'));
 baseline({...base,awayScore:null});receive(base);assert.equal(run('scoringNotice(games[0])'),'','Unknown scores were treated as zero');
 baseline();receive({...base,status:'final'});assert.equal(run('scoringNotice(games[0])'),'','Final status alone generated a scoring event');
 baseline();receive({...base,status:'final',homeScore:28});assert(run('scoringNotice(games[0])').includes('Georgia +7'));
 baseline({...base,status:'final'});receive({...base,status:'final',homeScore:28});assert.equal(run('scoringNotice(games[0])'),'','Old final results generated a live event');
 baseline();receive({...base,lastPlayId:'td',lastPlayScoring:true,lastPlay:'Texas touchdown reported by the feed.'});card=run('gameCard(games[0],true)');assert(card.includes('Scoring play'));assert(card.includes('is-scoring-play'));assert.equal(run("activeScoringEvent('score').kind"),'play');
 const playExpiry=run("activeScoringEvent('score').expiresAt");now+=5000;receive({...base,lastPlayId:'td',lastPlayScoring:true,lastPlay:'Texas touchdown reported by the feed.'});assert.equal(run("activeScoringEvent('score').expiresAt"),playExpiry);
 baseline();receive({...base,lastPlayId:'unsafe',lastPlayScoring:true,lastPlay:'<script>bad</script>'});card=run('scoringNotice(games[0])');assert(card.includes('&lt;script&gt;'));assert(!card.includes('<script>'));
 baseline();receive({...base,awayScore:21});run('clearScoringEvents()');assert.equal(run('scoringEvents.size'),0);assert.equal(el('#scoreAnnouncements').textContent,'');
 run(`games=[${snapshot(base)}];loadedPeriod='2026:12';season=2025;week=12;user={id:'me',name:'Me',role:'member'}`);
 context.fetch=async()=>({ok:true,status:200,json:async()=>({user:{id:'me',name:'Me',role:'member'},games:[{...base,awayScore:35}],picks:{},standings:[],members:[],seasons:[2025],liveStandings:{rows:[],activeGames:1}})});
 await run('load()');assert.equal(run('scoringEvents.size'),0,'Switching seasons compared unrelated scores');
 console.log('Scoring UI checks passed: team/delta notices, stable 30-second expiry, no repeat announcements or animation, both teams, corrections, missing scores, final transitions, explicit scoring plays, escaping and period isolation.');
})().catch(error=>{console.error(error);process.exitCode=1});

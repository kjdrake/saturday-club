const $=s=>document.querySelector(s), esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
document.addEventListener?.('error',event=>{if(event.target?.matches?.('.team-logo')){event.target.parentElement.classList.add('logo-missing');event.target.remove()}},true);
const seedGames=[
{id:'1',away:'Texas',home:'Georgia',awayAbbr:'TEX',homeAbbr:'UGA',awayId:251,homeId:61,awayRank:3,homeRank:5,awayRecord:'8–1',homeRecord:'8–1',spread:-3.5,kickoff:'2026-11-14T20:30:00Z',status:'scheduled',network:'ABC',included:true},
{id:'2',away:'Alabama',home:'Oklahoma',awayAbbr:'ALA',homeAbbr:'OU',awayId:333,homeId:201,awayRank:8,homeRank:12,awayRecord:'7–2',homeRecord:'7–2',spread:6.5,kickoff:'2026-11-14T20:30:00Z',status:'scheduled',network:'ESPN',included:true},
{id:'3',away:'Oregon',home:'Wisconsin',awayAbbr:'ORE',homeAbbr:'WIS',awayId:2483,homeId:275,awayRank:1,homeRank:null,awayRecord:'9–0',homeRecord:'5–4',spread:14.5,kickoff:'2026-11-15T00:30:00Z',status:'scheduled',network:'NBC',included:true},
{id:'4',away:'Tennessee',home:'Arkansas',awayAbbr:'TENN',homeAbbr:'ARK',awayId:2633,homeId:8,awayRank:7,homeRank:null,awayRecord:'7–2',homeRecord:'5–4',spread:7.5,kickoff:'2026-11-14T17:00:00Z',status:'scheduled',network:'ESPN',included:true},
{id:'5',away:'Michigan',home:'Ohio State',awayAbbr:'MICH',homeAbbr:'OSU',awayId:130,homeId:194,awayRank:18,homeRank:2,awayRecord:'6–3',homeRecord:'8–1',spread:-10.5,kickoff:'2026-11-14T17:00:00Z',status:'live',period:'Q3 · 08:42',awayScore:14,homeScore:21,network:'FOX',included:true},
{id:'6',away:'LSU',home:'Florida',awayAbbr:'LSU',homeAbbr:'FLA',awayId:99,homeId:57,awayRank:16,homeRank:null,awayRecord:'6–3',homeRecord:'5–4',spread:4.5,kickoff:'2026-11-14T17:00:00Z',status:'final',awayScore:24,homeScore:27,network:'ABC',included:true}];
const names=[['jd','Jamie Davis','JD'],['mc','Matt Carter','MC'],['sw','Sarah Wilson','SW'],['aj','Alex Johnson','AJ'],['er','Emma Reed','ER'],['cb','Chris Brooks','CB']];
const serverBacked=document.documentElement?.dataset?.serverBacked==='true';
let demo=!serverBacked, user=serverBacked?null:{id:'jd',name:'Jamie Davis',role:'admin'},games=serverBacked?[]:JSON.parse(localStorage.getItem('sc-games')||'null')||seedGames,picks=serverBacked?{}:JSON.parse(localStorage.getItem('sc-picks')||'{}'),saved={...picks},members=serverBacked?[]:JSON.parse(localStorage.getItem('sc-members')||'null')||names.map(([id,name,initials])=>({id,name,initials,active:true,role:id==='jd'?'admin':'member'})),tab='all',season=2026,week=12,view='picks',standings=[],lastSync=null,allSeasons=[2026,2025,2024];
let pendingInviteCode='',passwordResetToken='';
let liveBoard={rows:[],activeGames:0,updatedAt:null,stale:false};
let leaderboardMode='live',changedStandingIds=new Set(),changedScoreIds=new Set(),changedPlayIds=new Set();
let stateRequestId=0,stateInFlight=false,pendingMutations=0,loadedPeriod=null,refreshFailed=false;
function mergeDraftPicks(local,baseline,server,receivedGames){
  const byId=new Map(receivedGames.map(game=>[game.id,game])),merged={};
  for(const id of new Set([...Object.keys(local),...Object.keys(server)])){
    const game=byId.get(id);
    const side=!game||!game.included||locked(game)||local[id]===baseline[id]?server[id]:local[id];
    if(side)merged[id]=side;
  }
  return merged;
}
function markLiveChanges(nextBoard,nextGames){
  const previous=new Map(liveBoard.rows.map(row=>[row.id,row]));
  changedStandingIds=new Set(nextBoard.rows.filter(row=>previous.has(row.id)&&(previous.get(row.id).projectedPoints!==row.projectedPoints||previous.get(row.id).rank!==row.rank)).map(row=>row.id));
  const previousGames=new Map(games.map(game=>[game.id,game]));
  changedPlayIds=new Set(nextGames.filter(game=>{const old=previousGames.get(game.id);return old&&['possessionId','downDistance','fieldPosition','lastPlayId','lastPlay'].some(key=>old[key]!==game[key])}).map(game=>game.id));
  changedScoreIds=new Set(nextGames.filter(game=>{const old=previousGames.get(game.id);return old&&(old.homeScore!==game.homeScore||old.awayScore!==game.awayScore||old.status!==game.status)}).map(game=>game.id));
}
function liveStatus(){
  if(demo)return 'Sample league · Scores and projections are examples';
  const time=liveBoard.updatedAt?new Date(liveBoard.updatedAt).toLocaleTimeString([],{hour:'numeric',minute:'2-digit',second:'2-digit'}):null;
  if(refreshFailed)return 'Connection interrupted · Showing the last received scores';
  if(!liveBoard.activeGames)return 'No games in progress · Final season points';
  if(liveBoard.incompleteGames)return 'Some live scores unavailable · Projections incomplete';
  if(liveBoard.stale)return `Feed delayed${time?' · Last successful check '+time:' · Waiting for a score update'}`;
  return `${liveBoard.activeGames} game${liveBoard.activeGames===1?'':'s'} live${time?' · Feed checked '+time:''}`;
}
function movementLabel(row){
  if(leaderboardMode!=='live'||!row.movement)return '<span class="rank-steady" aria-label="No change from final rank">—</span>';
  return `<span class="rank-movement ${row.movement>0?'up':'down'}" aria-label="${row.movement>0?'Up':'Down'} ${Math.abs(row.movement)} from final rank">${row.movement>0?'↑':'↓'}${Math.abs(row.movement)}</span>`;
}
function leaderboardRailContent(){return `<div class="rail-title"><h2>${leaderboardMode==='live'?'Live leaderboard':'Final leaderboard'}</h2><a href="#standings">View all ↗</a></div><div class="live-feed-status ${liveBoard.stale||refreshFailed?'delayed':''}" data-live-status>${esc(liveStatus())}</div>${leaders()}<div class="rail-foot">${leaderboardMode==='live'?'Final points + how locked picks are doing now. Projections can change until the final whistle.':'Only completed games count toward final points.'}</div>`}
function standingsPanel(){
  const live=leaderboardMode==='live';
  return `<div class="sectionbar"><h2>${season} season standings</h2><div class="tabs" aria-label="Standings view"><button id="showLiveStandings" data-leader-mode="live" class="${live?'active':''}">Live projections</button><button id="showFinalStandings" data-leader-mode="final" class="${!live?'active':''}">Final results</button></div></div><section class="live-board-note"><div class="live-feed-status ${liveBoard.stale||refreshFailed?'delayed':''}" data-live-status>${esc(liveStatus())}</div><p>${live?'If every in-progress game ended at its current score, these would be the standings. Only saved picks on started games affect projections.':'These standings include completed games only. Switch to live projections to follow the race during play.'}</p></section><div class="leaderboard-table-wrap"><table class="live-standings-table"><thead><tr><th>Rank</th><th>Member</th>${live?'<th>Final pts</th><th>Live pts</th><th>Projected</th>':'<th>W–L–P</th><th>Cover %</th><th>Points</th>'}</tr></thead><tbody>${rankRows().map((row,index)=>`<tr data-standing-id="${esc(row.id)}" class="${row.id===user?.id?'me ':''}${changedStandingIds.has(row.id)?'standing-changed':''}"><td><strong>${row.rank||rankRows().findIndex(other=>other.points===row.points)+1}</strong>${movementLabel(row)}</td><td><div class="standing-member"><span class="avatar">${esc(initials(row.name))}</span><span>${esc(row.name)}${row.id===user?.id?' <span class="you-tag">YOU</span>':''}${live?`<small>${row.livePicks||0} live picks · ${row.liveWins||0} covering</small>`:''}</span></div></td>${live?`<td>${row.finalPoints??row.points}</td><td class="live-points">${row.livePoints?'+':''}${row.livePoints||0}</td><td class="projected-points"><b>${row.points}</b></td>`:`<td>${row.wins}–${row.losses}–${row.pushes}</td><td>${row.wins+row.losses?Math.round(row.wins/(row.wins+row.losses)*100):0}%</td><td><b>${row.points}</b></td>`}</tr>`).join('')||'<tr><td colspan="5">No league members yet.</td></tr>'}</tbody></table></div><p class="demo-note">${live?'Arrows compare the projected rank with final-results rank. A live cover earns a projected 1 point; a live push earns 0.5. These points settle only when the game is final.':'Tied points share a rank. Pushes count as half a point; postponed or canceled games are void.'} Scores are checked about every 15 seconds; the leaderboard refreshes every 5 seconds. Public feed delays may apply.</p>`;
}
function standingsCsv(){
  const live=leaderboardMode==='live',rows=rankRows();
  return [live?'Rank,Name,Final points,Live points,Projected points':'Rank,Name,Wins,Losses,Pushes,Final points',...rows.map((row,index)=>{
    const name='"'+row.name.replace(/"/g,'""')+'"',rank=row.rank||rows.findIndex(other=>other.points===row.points)+1;
    return live?`${rank},${name},${row.finalPoints??row.points},${row.livePoints||0},${row.points}`:`${rank},${name},${row.wins},${row.losses},${row.pushes},${row.points}`;
  })].join('\n');
}
function liveGamesPanel(){const liveGames=activeGames().filter(game=>game.status==='live');return liveGames.length?`<section class="standings-live-games"><div class="sectionbar"><h2>Games moving the board</h2><a href="#scores">Full scoreboard ↗</a></div><p class="sub">Live games in Week ${week} of your published slate.</p><div class="watch-game-grid">${liveGames.map(game=>gameCard(game,true)).join('')}</div></section>`:''}
function refreshLiveRegions(){
  const rail=document.querySelector('#liveLeaderboardRail');if(rail)rail.innerHTML=leaderboardRailContent();
  document.querySelectorAll('[data-live-status]').forEach(element=>element.textContent=liveStatus());
}
async function refreshLive(){
  if(demo||(!user&&!refreshFailed)||stateInFlight||pendingMutations||document.visibilityState==='hidden')return;
  await load({background:true});
}
function toast(t){$('#toast').textContent=t;$('#toast').style.display='block';clearTimeout(window.tt);window.tt=setTimeout(()=>$('#toast').style.display='none',3500)}
function modal(html){$('#modalBody').innerHTML=html;$('#modal').showModal()}$('#closeModal').onclick=()=>$('#modal').close();
async function api(path,body,{timeoutMs=45000}={}){
  if(body){pendingMutations++;stateRequestId++}
  const controller=new AbortController();
  const timeout=setTimeout(()=>controller.abort(),timeoutMs);
  try{
    let r;
    try{r=await fetch('/api/'+path,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined,signal:controller.signal})}
    catch(e){if(e.name==='AbortError')throw Error('The request timed out. Please try again.');throw Error('Could not reach the server. Check your connection and try again.')}
    let d;
    try{d=await r.json()}catch(e){if(e.name==='AbortError')throw Error('The request timed out. Please try again.');throw Error('The server returned an unexpected response. Please try again.')}
    if(!r.ok){const e=Error(d.error||'Request failed. Please try again.');e.status=r.status;throw e}
    return d;
  }finally{clearTimeout(timeout);if(body){pendingMutations--;stateRequestId++;stateInFlight=false}}
}
async function load({requireUser=false,background=false}={}){
  if(background&&(stateInFlight||pendingMutations))return;
  const requestId=++stateRequestId,period=`${season}:${week}`;let lockedDraftChanges=0;stateInFlight=true;
  try{
    const d=await api(`state?season=${season}&week=${week}`,undefined,{timeoutMs:requireUser?15000:20000});
    if(requestId!==stateRequestId||period!==`${season}:${week}`)return;
    if(requireUser&&!d.user)throw Error('Your sign-in could not be confirmed. Please allow cookies for this site and try again.');
    const nextBoard=d.liveStandings||{rows:[],activeGames:0,updatedAt:null,stale:false};
    markLiveChanges(nextBoard,d.games);
    if(loadedPeriod===period&&user?.id===d.user?.id)lockedDraftChanges=d.games.filter(game=>locked(game)&&picks[game.id]!==saved[game.id]&&picks[game.id]!==d.picks[game.id]).length;
    const nextPicks=loadedPeriod===period&&user?.id===d.user?.id?mergeDraftPicks(picks,saved,d.picks,d.games):d.picks;
    demo=false;user=d.user;games=d.games;picks=nextPicks;saved={...d.picks};members=d.members||[];standings=d.standings;liveBoard=nextBoard;lastSync=d.lastSync;loadedPeriod=period;refreshFailed=false;
    allSeasons=[...new Set([season,new Date().getFullYear(),...(d.seasons||[])])].sort((a,b)=>b-a);$('#season').innerHTML=allSeasons.map(y=>`<option ${y===season?'selected':''}>${y} season</option>`).join('');
    $('#connection').textContent=liveBoard.activeGames?(liveBoard.incompleteGames?'● SCORES PENDING':liveBoard.stale?'● FEED DELAYED':'● LIVE UPDATES'):'● CONNECTED';$('#connection').style.color='var(--status-connected, #50815b)';
    $('#profileName').innerHTML=user?`${esc(user.name)}<small>${user.role==='admin'?'League commissioner':'League member'}</small>`:'Sign in<small>Join your friends</small>';document.querySelector('.profile .avatar').textContent=user?initials(user.name):'→';
  }catch(error){
    if(requestId!==stateRequestId)return;
    if(requireUser){if(error.status===401)throw Error('Your sign-in could not be confirmed. Please allow cookies for this site and try again.');throw error}
    if(error.status===401){demo=false;user=null;games=[];picks={};saved={};members=[];standings=[];liveBoard={rows:[],activeGames:0,updatedAt:null,stale:false};loadedPeriod=null;refreshFailed=false;$('#connection').textContent='● SIGN IN TO PLAY';$('#profileName').innerHTML='Sign in<small>Join your friends</small>'}
    else if(!demo){refreshFailed=true;changedStandingIds=new Set();changedScoreIds=new Set();changedPlayIds=new Set();$('#connection').textContent='● RECONNECTING';if(!background)toast('Could not refresh. Showing last received data.')}
  }finally{if(requestId===stateRequestId)stateInFlight=false}
  if(background&&view==='admin'){refreshLiveRegions();return}
  render();
  if(lockedDraftChanges)toast('A game locked before your unsaved change could be submitted. Its saved pick is shown.');
}

function initials(n){return n.split(' ').map(x=>x[0]).slice(0,2).join('')}
function activeGames(){return games.filter(g=>g.included)}
function count(){return activeGames().filter(g=>picks[g.id]).length}
function locked(g){return g.status!=='scheduled'||(!demo&&Date.now()>=new Date(g.kickoff).getTime())||(!demo&&new Date(g.kickoff).getFullYear()<new Date().getFullYear())}
function signed(n){return n>0?'+'+n:String(n)}
function heading(title,desc,action=''){return `<div class="heading"><div><div class="eyebrow">COLLEGE FOOTBALL · ${season} SEASON</div><h1>${title}</h1><p class="sub">${desc}</p></div>${action}</div>`}
function rankRows(){if(!demo){if(leaderboardMode==='live'&&liveBoard.rows.length)return liveBoard.rows.map(row=>({...row,finalPoints:row.points,points:row.projectedPoints}));return standings;}return members.filter(m=>m.active).map((m,i)=>({...m,wins:[48,52,50,46,44,42][i]||0,losses:[24,20,22,26,28,30][i]||0,pushes:0,points:[48,52,50,46,44,42][i]||0})).sort((a,b)=>b.points-a.points)}
function leaders(){return rankRows().slice(0,5).map((row,index)=>`<div class="leader ${changedStandingIds.has(row.id)?'standing-changed':''}" data-standing-id="${esc(row.id)}"><span class="rank">${row.rank||rankRows().findIndex(other=>other.points===row.points)+1}${movementLabel(row)}</span><span class="avatar" style="background:${['#eae7da','#e2e9df','#eadfd5','#e5e6eb','#e8e3dc'][index]}">${esc(initials(row.name))}</span><span class="person">${esc(row.name)}${row.id===user?.id?'<span class="you-tag">YOU</span>':''}<small>${leaderboardMode==='live'&&row.livePicks?`${row.liveWins} covering · ${row.livePushes} pushing`:`${row.wins}–${row.losses}–${row.pushes} final record`}</small></span><strong>${row.points}${leaderboardMode==='live'&&row.livePoints?`<small>+${row.livePoints} live</small>`:''}</strong></div>`).join('')||'<p class="sub">No graded picks yet.</p>'}

function rail(){return `<div class="rail"><section class="rail-card" id="liveLeaderboardRail">${leaderboardRailContent()}</section><section class="rail-card"><div class="rail-title"><h2>How we play</h2><span>⚑</span></div><div class="rule-line"><span>Cover the spread</span><b>+1 point</b></div><div class="rule-line"><span>Push (a tie)</span><b>+0.5 points</b></div><div class="rule-line"><span>Miss or no pick</span><b>0 points</b></div><div class="rail-foot">Picks lock at each game’s kickoff.<br>Published lines stay fixed unless corrected before kickoff.<br>Play any number of games; skipped games earn 0.</div></section><section class="note-card"><div class="eyebrow">COMMISSIONER’S CORNER</div><h3>Good friends. Bad takes.</h3><p>Get your picks in before kickoff. The group chat is a lot more fun when you have a side.</p><a href="#admin">Manage this week ↗</a></section></div>`}
// ESPN team directory resolves both feed IDs and manually entered school names.
const teamDirectory=window.COLLEGE_TEAMS||[];
const teamById=new Map(teamDirectory.map(team=>[String(team.id),team]));
const normalizeTeam=name=>String(name||'').toLowerCase().replace(/[^a-z0-9]/g,'');
const teamByName=new Map();
for(const team of teamDirectory)for(const alias of team.aliases){const key=normalizeTeam(alias);if(!teamByName.has(key))teamByName.set(key,team);else if(teamByName.get(key)?.id!==team.id)teamByName.set(key,null)}
function teamBadge(game,side){
  const id=game[side+'Id'];
  const team=(id&&teamById.get(String(id)))||teamByName.get(normalizeTeam(game[side]));
  const logo=team?.logo||(id?'https://a.espncdn.com/i/teamlogos/ncaa/500/'+encodeURIComponent(id)+'.png':null);
  const abbreviation=game[side+'Abbr']||initials(game[side]||'?');
  return `<span class="team-badge ${logo?'':'logo-missing'}">${logo?`<img class="team-logo" src="${esc(logo)}" alt="" loading="lazy" decoding="async">`:''}<span class="team-fallback" aria-hidden="true">${esc(abbreviation.slice(0,4))}</span></span>`;
}
let slateDraft=null;
let slateFilters={search:'',conference:'all',ranking:'all',conferenceOnly:false,view:'all'};
function slateHasChanges(){return !!slateDraft&&Object.keys(slateDraft.items).some(id=>JSON.stringify(slateDraft.items[id])!==JSON.stringify(slateDraft.base[id]))}
function ensureSlateDraft(){
  const key=`${user?.id||'demo'}:${season}:${week}`;
  if(slateDraft&&slateDraft.key!==key)slateFilters={search:'',conference:'all',ranking:'all',conferenceOnly:false,view:'all'};
  if(!slateDraft||slateDraft.key!==key||!slateHasChanges()){
    const items=Object.fromEntries(games.map(game=>[game.id,{included:!!game.included,spread:game.spread??null}]));
    slateDraft={key,items,base:JSON.parse(JSON.stringify(items))};
  }else for(const game of games)if(!slateDraft.items[game.id]||JSON.stringify(slateDraft.items[game.id])===JSON.stringify(slateDraft.base[game.id])){
    const item={included:!!game.included,spread:game.spread??null};slateDraft.items[game.id]={...item};slateDraft.base[game.id]={...item};
  }
  return slateDraft;
}
function teamConference(game,side){
  const stored=game[side+'Conference'];
  if(stored&&stored!=='Other / unknown')return stored;
  const school=teamById.get(String(game[side+'Id']))||teamByName.get(normalizeTeam(game[side]));
  return school?.conference?.name||'Other / unknown';
}
function isRanked(rank){return Number.isInteger(+rank)&&+rank>=1&&+rank<=25}
function isConferenceMatchup(game){const away=teamConference(game,'away');return away===teamConference(game,'home')&&!['Other / unknown','FBS Independents'].includes(away)}
function filteredSlateGames(){
  ensureSlateDraft();
  const search=slateFilters.search.trim().toLowerCase();
  return games.filter(game=>{
    if(search&&!`${game.away} ${game.home} ${game.awayAbbr||''} ${game.homeAbbr||''}`.toLowerCase().includes(search))return false;
    if(slateFilters.conference!=='all'&&![teamConference(game,'away'),teamConference(game,'home')].includes(slateFilters.conference))return false;
    if(slateFilters.conferenceOnly&&!isConferenceMatchup(game))return false;
    if(slateFilters.ranking==='ranked'&&!isRanked(game.awayRank)&&!isRanked(game.homeRank))return false;
    if(slateFilters.ranking==='both'&&!(isRanked(game.awayRank)&&isRanked(game.homeRank)))return false;
    return slateFilters.view!=='selected'||slateDraft.items[game.id].included;
  }).sort((a,b)=>new Date(a.kickoff)-new Date(b.kickoff)||String(a.id).localeCompare(String(b.id)));
}
function canSelectSlateGame(game){const line=slateDraft.items[game.id].spread;return !locked(game)&&line!==null&&Number.isFinite(line)&&Math.abs(line)<=100}
function canRemoveSlateGame(game){return !locked(game)&&!game.hasPicks}
function setSlateSelection(ids,included){
  ensureSlateDraft();let changed=0;
  for(const game of games)if(ids.includes(game.id)&&(included?canSelectSlateGame(game):canRemoveSlateGame(game))){
    if(slateDraft.items[game.id].included!==included)changed++;
    slateDraft.items[game.id].included=included;
  }
  return changed;
}
function slateHasInvalidSpread(){return !!slateDraft&&Object.values(slateDraft.items).some(item=>item.spread!==null&&(!Number.isFinite(item.spread)||Math.abs(item.spread)>100))}
function slateChanges(){return Object.entries(slateDraft.items).filter(([id,item])=>JSON.stringify(item)!==JSON.stringify(slateDraft.base[id])).map(([id,item])=>({id,...item}))}
function slateBuilder(){
  ensureSlateDraft();
  const visible=filteredSlateGames(),selected=games.filter(g=>slateDraft.items[g.id].included),published=games.filter(g=>g.included);
  const conferences=[...new Set(games.flatMap(g=>[teamConference(g,'away'),teamConference(g,'home')]))].sort();
  const addable=visible.filter(g=>!slateDraft.items[g.id].included&&canSelectSlateGame(g)).length;
  const removable=visible.filter(g=>slateDraft.items[g.id].included&&canRemoveSlateGame(g)).length;
  return `<div class="admin-panel slate-builder"><div class="sectionbar"><h2>Week ${week} · Build the slate</h2><button class="button" id="sync">↻ Refresh games</button></div><p>Choose the matchups your crew will play. Start with a conference or ranked games, then mix in any other favorites. Only published games appear on players’ pick sheets.</p><div class="slate-summary"><div><strong id="slateSelectedCount">${selected.length}</strong><span>games in your slate</span></div><div><strong>${published.length}</strong><span>currently published</span></div><span id="slateDraftStatus" class="draft-status ${slateHasChanges()?'pending':''}">${slateHasChanges()?'● Unpublished changes':'✓ Slate is up to date'}</span></div><div class="slate-filters"><label class="field">Find a team<input id="slateSearch" type="search" value="${esc(slateFilters.search)}" placeholder="Search teams or matchups"></label><label class="field">Conference<select id="slateConference"><option value="all">All conferences</option>${conferences.map(name=>`<option ${slateFilters.conference===name?'selected':''} value="${esc(name)}">${esc(name)}</option>`).join('')}</select></label><label class="field">Rankings<select id="slateRanking"><option value="all">All games</option><option value="ranked" ${slateFilters.ranking==='ranked'?'selected':''}>Any Top 25 team</option><option value="both" ${slateFilters.ranking==='both'?'selected':''}>Top 25 vs. Top 25</option></select></label></div><div class="slate-filter-options"><label><input type="checkbox" id="slateConferenceOnly" ${slateFilters.conferenceOnly?'checked':''}> Conference matchups only</label><button class="button quiet" id="clearSlateFilters">Clear filters</button></div><div class="slate-actions"><div class="tabs"><button data-slate-view="all" class="${slateFilters.view==='all'?'active':''}">All games (${games.length})</button><button data-slate-view="selected" class="${slateFilters.view==='selected'?'active':''}">Your slate (${selected.length})</button></div><div><button class="button" id="addVisible" ${addable?'':'disabled'}>Add visible (${addable})</button><button class="button" id="removeVisible" ${removable?'':'disabled'}>Remove visible (${removable})</button></div></div><p class="slate-helper">${visible.length} of ${games.length} games shown. Filters never remove your selections. “Top 25 vs. Top 25” requires both teams to be ranked.</p><div class="slate-table"><div class="slate-header" aria-hidden="true"><span>Pick</span><span>Matchup</span><span>Result</span><span>Home spread</span></div>${visible.map(slateRow).join('')||`<div class="slate-empty">${games.length?'No games match these filters. Clear filters to see the full week.':'No games loaded yet. Refresh games to get this week’s schedule, or add a matchup manually below.'}</div>`}</div><div class="slate-publish"><div><strong id="slateSelectedFooter">${selected.length} games selected</strong><p>Players may pick any of these games. Skipped games earn 0 points.</p></div><div><button class="button" id="discardSlate" ${slateHasChanges()?'':'disabled'}>Discard changes</button><button class="button primary" id="saveSlate" ${slateHasChanges()&&!slateHasInvalidSpread()?'':'disabled'}>Publish weekly slate</button></div></div><p class="slate-helper">Feed lines stay fixed after publication; use Edit for a pre-kickoff correction. Started games and games with submitted picks cannot be removed. Add a missing spread before selecting a game.</p></div>`;
}
function slateRow(game){
  const matchup=game.away+' at '+game.home,item=slateDraft.items[game.id];
  const protectedSelection=locked(game)||(game.included&&game.hasPicks);
  const disabled=protectedSelection||(!item.included&&!canSelectSlateGame(game));
  const badge=game.hasPicks?'Picks submitted':locked(game)?'Locked':game.included?'Published':item.included?'Draft selection':'';
  return `<div class="slate-row ${item.included?'in-slate':''}"><input class="slate-checkbox" type="checkbox" aria-label="Include ${esc(matchup)}" data-include="${game.id}" ${item.included?'checked':''} ${disabled?'disabled':''}><div class="slate-matchup"><div class="slate-team">${teamBadge(game,'away')}<span>${isRanked(game.awayRank)?`<sup>#${game.awayRank}</sup> `:''}${esc(game.away)}<small>${esc(teamConference(game,'away'))}</small></span></div><span class="slate-at">at</span><div class="slate-team">${teamBadge(game,'home')}<span>${isRanked(game.homeRank)?`<sup>#${game.homeRank}</sup> `:''}${esc(game.home)}<small>${esc(teamConference(game,'home'))}</small></span></div><div class="slate-game-detail">${new Date(game.kickoff).toLocaleString('en-US',{weekday:'short',month:'short',day:'numeric',hour:'numeric',minute:'2-digit',timeZoneName:'short'})}${badge?' · '+badge:''}${item.spread===null?' · Spread needed':''}</div></div><button class="button result-button" aria-label="Set result for ${esc(matchup)}" data-result="${game.id}">Set result</button><div class="slate-line"><span>Home spread</span><input aria-label="Home spread for ${esc(matchup)}" type="number" step="0.5" placeholder="Set line" data-spread="${game.id}" value="${item.spread??''}" ${game.included||locked(game)?'disabled':''}><span class="spread-edit-slot">${game.included&&!locked(game)?`<button type="button" class="spread-edit" data-edit-spread="${game.id}" aria-label="Edit published spread for ${esc(matchup)}">Edit</button>`:''}</span></div></div>`;
}
function gameStatusLabel(game){
  const name=String(game.statusName||'');
  if(/HALFTIME/.test(name))return game.statusDetail||'Halftime';
  if(/DELAYED|SUSPENDED|END_PERIOD/.test(name))return game.statusDetail||game.period||'Game paused';
  if(game.status==='void')return /POSTPONED/.test(name)?'POSTPONED':/CANCELED|CANCELLED/.test(name)?'CANCELED':'VOID / POSTPONED';
  if(game.status==='final')return game.statusDetail||'FINAL';
  if(game.status==='live'){
    if(game.quarter){const quarter=game.quarter<=4?'Q'+game.quarter:game.quarter===5?'OT':(game.quarter-4)+'OT';return quarter+(game.quarter<=4&&game.clock?' · '+game.clock:'')}
    return game.period||game.statusDetail||'In progress';
  }
  return new Date(game.kickoff).toLocaleString('en-US',{weekday:'short',month:'short',day:'numeric',hour:'numeric',minute:'2-digit',timeZoneName:'short'});
}
function possessionSide(game){if(game.status!=='live'||!game.possessionId)return null;return ['away','home'].find(side=>String(game[side+'Id'])===String(game.possessionId))||null}
function gameFeedStatus(game){
  if(demo)return 'Sample game details';
  const stamp=game.feedCheckedAt||lastSync;
  if(refreshFailed)return 'Connection interrupted · Last received game info';
  if(!stamp)return game.status==='live'?'Waiting for a feed check':'Awaiting feed refresh';
  const time=new Date(stamp);if(!Number.isFinite(time.getTime()))return 'Waiting for a feed check';
  const delayed=game.status==='live'&&Date.now()-time.getTime()>60000;
  return `${delayed?'Feed delayed · Last check':'Feed checked'} ${time.toLocaleTimeString([],{hour:'numeric',minute:'2-digit',second:'2-digit'})}`;
}
function gameSituation(game){
  if(game.status!=='live')return '';
  const side=possessionSide(game),field=game.fieldPosition;
  const down=game.downDistance,showField=field&&(!down||!down.toLowerCase().includes(field.toLowerCase()));
  const available=side||down||field||game.redZone;
  return `<div class="game-situation ${changedPlayIds.has(game.id)?'play-updated':''}">${game.redZone?'<span class="red-zone-tag">Red zone</span>':''}${side?`<span class="possession-info"><span aria-hidden="true">●</span> ${esc(game[side+'Abbr']||game[side])} ball</span>`:''}${down?`<strong>${esc(down)}</strong>`:''}${showField?`<span>Ball at ${esc(field)}</span>`:''}${!available?'<span class="play-unavailable">Play details not available</span>':''}</div>${game.lastPlay?`<div class="game-last-play"><span>${game.lastPlayScoring?'Scoring play':'Last play'}</span><p>${esc(game.lastPlay)}</p></div>`:''}`;
}
function gamePickSummary(game){
  const side=locked(game)?saved[game.id]:picks[game.id];
  if(game.status==='void')return '<div class="game-pick-summary neutral"><span>Game void</span><strong>No points awarded</strong></div>';
  if(!side)return `<div class="game-pick-summary neutral"><span>${locked(game)?'No saved pick':'No pick selected'}</span><strong>${locked(game)?'0 points':'Pick any games you like'}</strong></div>`;
  const spread=side==='home'?game.spread:-game.spread;
  const pick=`${game[side+'Abbr']||game[side]} ${game.spread===null?'—':signed(spread)}`;
  let label='',state='neutral',detail='';
  if(game.status==='live'){
    label=livePickLabel(game,side);
    if(game.spread!==null&&game.homeScore!=null&&game.awayScore!=null){
      let margin=game.homeScore+game.spread-game.awayScore;if(side==='away')margin=-margin;
      state=margin>0?'covering':margin<0?'trailing':'pushing';
      detail=margin===0?'Right on the spread':`${Number(Math.abs(margin).toFixed(2))} ${margin>0?'ahead of':'behind'} the spread`;
    }
  }else if(game.status==='final'){label=gradeLabel(game,side);state=label.startsWith('Awaiting')?'neutral':label.startsWith('Covered')?'covering':label.startsWith('Push')?'pushing':'trailing'}
  else label=picks[game.id]!==saved[game.id]?'Unsaved selection':'Saved · Locks at kickoff';
  return `<div class="game-pick-summary ${state}"><div><span>Your ${game.status==='scheduled'&&picks[game.id]!==saved[game.id]?'selection':'saved pick'}</span><b>${esc(pick)}</b>${detail?`<small>${detail}</small>`:''}</div><strong>${esc(label)}</strong></div>`;
}
function gameCard(g,scoreMode=false){
  const selected=picks[g.id],sp=[-g.spread,g.spread],possession=possessionSide(g);
  const location=[g.venue,g.venueLocation].filter(Boolean).join(' · ');
  return `<article class="game ${g.status==='live'?'is-live ':''}${changedScoreIds.has(g.id)?'score-updated':''}" data-game-id="${g.id}"><div class="game-meta"><span class="${g.status==='live'?'live':''}">${esc(gameStatusLabel(g))}</span><span>${esc(g.network||'NCAA')}${locked(g)?' · 🔒':''}</span></div><div class="game-body">${['away','home'].map((side,index)=>`${index?'<span class="versus">AT</span>':''}<div class="team ${index?'right':''} ${possession===side?'has-possession':''}">${teamBadge(g,side)}<div class="team-text"><b>${isRanked(g[side+'Rank'])?`<sup>${g[side+'Rank']}</sup> `:''}${esc(g[side])}</b><small>${esc(g[side+'Record']||'FBS')}${scoreMode&&g.spread!==null?' · '+signed(sp[index]):''}</small>${possession===side?'<span class="possession-marker">● Possession</span>':''}${g.status==='live'&&Number.isInteger(g[side+'Timeouts'])?`<small class="team-timeouts">${g[side+'Timeouts']} timeouts</small>`:''}</div>${['live','final'].includes(g.status)?`<span class="score" aria-label="${esc(g[side])} score">${g[side+'Score']??'—'}</span>`:''}</div>`).join('')}</div>${gameSituation(g)}${!scoreMode?`<div class="pick-row">${['away','home'].map((side,index)=>`<button class="pick ${selected===side?'selected':''}" data-pick="${g.id}:${side}" ${locked(g)||g.spread===null?'disabled':''}><span><i class="circle">${selected===side?'✓':''}</i>${esc(g[side+'Abbr']||g[side])}</span><b>${g.spread===null?'No line':signed(sp[index])}</b></button>`).join('')}</div>`:''}${gamePickSummary(g)}${spreadCorrectionNotice(g)}${location?`<div class="game-location">${esc(location)}</div>`:''}<div class="game-note"><span>${esc(gameFeedStatus(g))}</span><span>${g.spread===null?'Awaiting spread':esc(g.bookmaker||'Commissioner')+' · '+(locked(g)?'Locked line':'Published line')}</span></div></article>`;
}

function livePickLabel(game,side){if(game.spread===null||game.homeScore==null||game.awayScore==null)return 'Awaiting live score';const margin=game.homeScore+game.spread-game.awayScore;return margin===0?'Pushing now · +0.5 projected':(side==='home'?margin>0:margin<0)?'Covering now · +1 projected':'Trailing now · 0 projected'}
function gradeLabel(g,side){if(g.spread===null||g.homeScore==null||g.awayScore==null)return 'Awaiting final score';const margin=g.homeScore+g.spread-g.awayScore;return margin===0?'Push · +0.5 points':(side==='home'?margin>0:margin<0)?'Covered · +1 point':'Miss · 0 points'}
function render(){view=location.hash.slice(1)||'picks';if(!['picks','scores','standings','history','admin'].includes(view))view='picks';const titles={picks:'Weekly picks',scores:'Scoreboard',standings:'Standings',history:'Season archive',admin:'Commissioner tools'};$('#breadcrumb').textContent=titles[view];document.querySelectorAll('[data-nav]').forEach(a=>a.classList.toggle('active',a.dataset.nav===view));$('#pickBadge').textContent=`${count()}/${activeGames().length}`;let html='';const archive=season<2026?`<div class="archive-banner">Viewing the ${season} archive. ${demo?'Sample historical results are shown.':'Archived picks are read-only.'}</div>`:'';
if(view==='picks'){const rows=rankRows(),me=rows.find(p=>p.id===user?.id);html=heading('Every pick. Every Saturday.','A little friendly competition. A whole lot of college football.',`<button class="button" id="weekPicker">▦ &nbsp; Week ${week} &nbsp;⌄</button>`)+archive+`<section class="hero"><div><div class="eyebrow">YOUR SATURDAY SPOT</div><h2>Pull up a chair. Pick a side.</h2><p>Week ${week} is on the clock. Pick your side against the spread.<br><strong>Pick any games you like.</strong> Skipped games earn 0 points.</p></div><div class="progress-panel"><div class="progress-label"><span>Your weekly picks</span><b>${count()} <span style="font-size:12px;font-weight:400;color:#a8bcae">/ ${activeGames().length}</span></b></div><div class="progress-track"><div style="width:${count()/Math.max(1,activeGames().length)*100}%"></div></div><p>⌁ &nbsp; Each pick locks at its game’s kickoff</p></div></section><div class="stats"><div class="stat"><div class="stat-top"><span>${leaderboardMode==='live'&&liveBoard.activeGames?'Projected rank':'Season rank'}</span><span>⚑</span></div><strong>${me?'#'+(me.rank||rows.indexOf(me)+1):'—'} <small> / ${rows.length}</small></strong><small class="positive">The season is still anyone’s game</small></div><div class="stat"><div class="stat-top"><span>Season record</span><span>↗</span></div><strong>${me?me.wins+'–'+me.losses:'0–0'}</strong><small>${me?.pushes||0} pushes this season</small></div><div class="stat"><div class="stat-top"><span>${leaderboardMode==='live'&&liveBoard.activeGames?'Projected points':'Total points'}</span><span>✧</span></div><strong>${me?.points||0}<small> pts</small></strong><small>1 cover. 1 point. Simple.</small></div><div class="stat"><div class="stat-top"><span>League members</span><span>♧</span></div><strong>${demo?members.length:rows.length}</strong><small>Your favorite football critics</small></div></div><div class="content-grid"><section><div class="sectionbar"><h2>Week ${week} pick sheet <span style="font:10px 'DM Sans';color:#9ba38f;margin-left:7px">${activeGames().length} GAMES</span></h2><div class="tabs"><button data-tab="all" class="${tab==='all'?'active':''}">All games</button><button data-tab="open" class="${tab==='open'?'active':''}">To pick</button></div></div>${activeGames().filter(g=>tab==='all'||!picks[g.id]&&!locked(g)).map(g=>gameCard(g)).join('')||`<div class="empty">${activeGames().length?'You’re all caught up. See you Saturday.':'No games have been published for this week yet. Check back after your commissioner builds the slate.'}</div>`}<div class="savebar"><span>${JSON.stringify(saved)!==JSON.stringify(picks)?'● You have unsaved picks':'✓ Your saved picks are up to date'}<br>Pick as many or as few games as you like. Click your selected side again to skip it before kickoff.</span><button class="button primary" id="savePicks">Save my picks &nbsp; ↗</button></div><p class="demo-note">${demo?'Preview league · Sample matchups, scores, spreads, and standings. Picks save on this browser. Connect the included server for shared play and live feeds.':'Spreads stay frozen. Scores are checked about every 15 seconds, with leaderboard updates every 5 seconds. Live points are projections until games finish.'}</p></section>${rail()}</div>`}
if(view==='scores')html=heading('Saturday, in motion.','Follow every drive. See how your picks are holding up.',`<button class="button" id="refresh">↻ Refresh scores</button>`)+archive+`<div class="sectionbar"><h2>Week ${week} scoreboard</h2><span class="eyebrow">${demo?'SAMPLE SCORES':lastSync?'UPDATED '+new Date(lastSync).toLocaleTimeString():'AWAITING FEED SYNC'}</span></div><div class="content-grid"><div>${activeGames().map(g=>gameCard(g,true)).join('')||'<div class="empty">No games selected for this week.</div>'}</div>${rail()}</div>`;
if(view==='standings')html=heading('The bragging rights board.','Watch the race move as scores change.',`<button class="button" id="export">↓ Export standings</button>`)+archive+standingsPanel()+liveGamesPanel();
if(view==='history')html=heading('Seasons end. Stories don’t.','A home for every season, every rivalry, and every questionable pick.')+`<div class="history-cards">${allSeasons.map((s,i)=>`<article class="history-card"><div class="eyebrow">${i?'ARCHIVED SEASON':'CURRENT SEASON'}</div><h3>${s} season</h3><p>${demo?(i?'Sample champion · '+['','Sarah Wilson','Matt Carter'][i]:'The race for the top is on.'):'Browse saved picks and final results.'}</p><button class="button" data-year="${s}">View season ↗</button></article>`).join('')}</div><p class="demo-note">${demo?'Archive cards use sample history in the preview.':'All competitions are retained by season and week in the database.'}</p>`;
if(view==='admin')html=renderAdmin();if(!demo&&!user)html=heading('Your crew. Your Saturday.','Sign in to make your picks and follow your league.')+'<div class="admin-panel"><h2>Welcome to Saturday Club</h2><p>Use your account or register with an invite code from the commissioner.</p><button class="button primary" id="signin">Sign in / Join the league</button></div>';$('#app').innerHTML=html;bind();}
function renderAdmin(){if(!demo&&user?.role!=='admin')return heading('Commissioner tools','An admin account is required to manage the league.')+'<button class="button primary" id="signin">Sign in</button>';return heading('Behind the Saturday magic.','Manage the crew, set the slate, and keep the season running.',`<button class="button" id="weekPicker">Week ${week} ⌄</button>`)+slateBuilder()+`<div class="admin-panel"><h2>League members</h2><p>Invite friends with a single-use link that expires in seven days. Disabling a member revokes access while preserving their picks.</p>${members.map(m=>`<div class="admin-game"><span>${esc(m.name)} <small>· ${esc(m.role)}</small></span><button class="button" data-member="${m.id}" ${m.id===user?.id?'disabled':''}>${m.active?'Disable':'Enable'}</button></div>`).join('')}<div class="form-row"><label class="field">Friend’s name<input id="inviteName" placeholder="e.g. Taylor Morgan" maxlength="80"></label><label class="field">Delivery<select id="inviteDelivery"><option value="link">Create link / text from my phone</option><option value="email">Send email automatically</option></select></label><label class="field">Recipient email (for email delivery)<input id="inviteEmail" type="email" placeholder="friend@example.com" maxlength="254"></label><button class="button primary" id="invite">Create invitation</button></div><div id="inviteResult"></div></div><div class="admin-panel"><h2>Add a game manually</h2><p>Use this when a public feed does not provide a matchup or spread. Home spread is negative when the home team is favored.</p><div class="form-row"><label class="field">Away team<input id="away"></label><label class="field">Home team<input id="home"></label><label class="field">Home spread<input id="line" type="number" step="0.5"></label><label class="field">Kickoff (your local time)<input id="kickoff" type="datetime-local"></label></div><button class="button" id="addGame">Add game</button></div><div class="admin-panel"><h2>Season & week</h2><p>Each season keeps an independent pick history and standings. Choose the active season and week above to manage its slate.</p><div class="form-row"><label class="field">Season year<input id="seasonYear" type="number" min="2000" max="2100" value="${season}"></label><button class="button" id="openSeason">Open season</button></div></div>`}
function bind(){
  document.querySelectorAll('[data-leader-mode]').forEach(button=>button.onclick=()=>{leaderboardMode=button.dataset.leaderMode;render()});
  bindSlateBuilder();
$('#openSeason')?.addEventListener('click',()=>{const year=+$('#seasonYear').value;if(year<2000||year>2100||!Number.isInteger(year))return toast('Enter a year between 2000 and 2100.');season=year;if(!Array.from($('#season').options).some(o=>parseInt(o.value)===year)){const opt=document.createElement('option');opt.value=year+' season';opt.textContent=year+' season';$('#season').append(opt)}$('#season').value=year+' season';if(!demo)load();else{games=[];picks={};saved={};render()}});
document.querySelectorAll('[data-result]').forEach(b=>b.onclick=()=>{const g=games.find(g=>g.id===b.dataset.result);modal(`<h2>Set game result</h2><p>${esc(g.away)} @ ${esc(g.home)}. Manual results override the current score. The next public feed sync may replace them for feed-backed games.</p><div class="form-row"><label class="field">Away score<input id="awayResult" type="number" min="0" max="200" value="${g.awayScore??0}"></label><label class="field">Home score<input id="homeResult" type="number" min="0" max="200" value="${g.homeScore??0}"></label></div><label class="field">Status<select id="resultStatus"><option value="final">Final</option><option value="void">Void / Canceled</option></select></label><br><button class="button primary" id="saveResult">Save result & grade picks</button>`);$('#saveResult').onclick=async()=>{try{const body={season,week,id:g.id,awayScore:+$('#awayResult').value,homeScore:+$('#homeResult').value,status:$('#resultStatus').value};if(demo){Object.assign(g,body);localStorage.setItem('sc-games',JSON.stringify(games));render()}else{await api('admin/result',body);await load()}$('#modal').close();toast('Result saved. Standings updated.')}catch(e){toast(e.message)}}});
document.querySelectorAll('[data-pick]').forEach(b=>b.onclick=()=>{const[id,side]=b.dataset.pick.split(':');if(picks[id]===side)delete picks[id];else picks[id]=side;render()});document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>{tab=b.dataset.tab;render()});$('#savePicks')?.addEventListener('click',async()=>{try{const submitted={...picks};if(demo)localStorage.setItem('sc-picks',JSON.stringify(submitted));else{if(!user)return accountModal();await api('picks',{season,week,picks:submitted})}saved={...submitted};render();toast('Your picks are saved. Bring on Saturday.')}catch(e){toast(e.message)}});$('#weekPicker')?.addEventListener('click',()=>{modal(`<h2>Choose your week</h2><p>View picks and games for each week of ${season}.</p><div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px">${Array.from({length:18},(_,i)=>`<button class="button" data-week="${i+1}">Week ${i+1}</button>`).join('')}</div>`);document.querySelectorAll('[data-week]').forEach(b=>b.onclick=()=>{week=+b.dataset.week;$('#modal').close();if(demo){games=week===12?JSON.parse(localStorage.getItem('sc-games')||'null')||seedGames:[];picks=week===12?JSON.parse(localStorage.getItem('sc-picks')||'{}'):{};saved={...picks};render()}else load()})});$('#refresh')?.addEventListener('click',()=>{if(demo)toast('Sample scores shown. Live scores require the included backend.');else load()});$('#export')?.addEventListener('click',()=>{const csv=standingsCsv();const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([csv],{type:'text/csv'}));a.download=`saturday-club-${season}-${leaderboardMode==='live'?'live-projection':'final'}.csv`;a.click();URL.revokeObjectURL(a.href)});document.querySelectorAll('[data-year]').forEach(b=>b.onclick=()=>{season=+b.dataset.year;$('#season').value=season+' season';location.hash='standings';if(!demo)load();else render()});$('#sync')?.addEventListener('click',async e=>{if(demo)return toast('Live feed sync is available with the AWS backend.');e.target.disabled=true;e.target.textContent='Syncing…';try{const d=await api('admin/sync',{season,week});toast(d.message);await load()}catch(e){toast(e.message)}finally{render()}});document.querySelectorAll('[data-member]').forEach(b=>b.onclick=async()=>{try{const m=members.find(m=>m.id===b.dataset.member);if(demo){m.active=!m.active;localStorage.setItem('sc-members',JSON.stringify(members));render()}else{await api('admin/member',{id:m.id,active:!m.active});await load()}toast('Member access updated.')}catch(e){toast(e.message)}});$('#invite')?.addEventListener('click',async()=>{const name=$('#inviteName').value.trim();if(!name)return toast('Enter your friend’s name.');try{if(demo){members.push({id:crypto.randomUUID(),name,active:true,role:'member'});localStorage.setItem('sc-members',JSON.stringify(members));render();toast('Sample member added. Real invite codes require the backend.')}else{const button=$('#invite');button.disabled=true;try{const d=await api('admin/invite',{name,delivery:$('#inviteDelivery').value,email:$('#inviteEmail').value.trim()});showInvitation(d.code,name,d.delivery);if(d.message)toast(d.message)}finally{button.disabled=false}}}catch(e){toast(e.message)}});$('#addGame')?.addEventListener('click',async()=>{try{const g={id:crypto.randomUUID(),away:$('#away').value.trim(),home:$('#home').value.trim(),spread:$('#line').value===''?null:+$('#line').value,kickoff:$('#kickoff').value?new Date($('#kickoff').value).toISOString():null,status:'scheduled',included:false,awayAbbr:$('#away').value.slice(0,4).toUpperCase(),homeAbbr:$('#home').value.slice(0,4).toUpperCase()};if(!g.away||!g.home||g.spread===null||!g.kickoff)return toast('Complete all game fields.');if(demo){games.push(g);localStorage.setItem('sc-games',JSON.stringify(games));render()}else{await api('admin/game',{season,week,game:g});await load()}toast('Game added. Select it to include it in the slate.')}catch(e){toast(e.message)}});$('#signin')?.addEventListener('click',accountModal)}
function editPublishedSpread(game){
  const original=game.spread,editSeason=season,editWeek=week;
  modal(`<h2>Correct published spread</h2><p>${esc(game.away)} at ${esc(game.home)}</p><p>Current home spread: <strong>${signed(original)}</strong>. Negative means the home team is favored.</p><form id="spreadCorrectionForm"><label class="field">New home spread<input id="correctedSpread" type="number" min="-100" max="100" step="0.5" required value="${original}"></label><br><label class="field">Reason (optional)<input id="spreadReason" maxlength="240" placeholder="Correcting a manual entry"></label><div class="spread-warning">${game.hasPicks?'Picks have already been submitted. ':''}Existing picks stay selected and will be scored against the corrected line. Players will see a notice to review their pick. The line locks at kickoff.</div><label class="spread-confirm"><input id="confirmSpread" type="checkbox" required> I confirm that existing picks will use the new spread.</label><div id="spreadError" class="form-error" role="alert" hidden></div><div class="form-actions"><button type="submit" class="button primary" id="saveSpreadCorrection">Update published spread</button></div></form>`);
  let submitting=false;
  $('#spreadCorrectionForm').addEventListener('submit',async event=>{
    event.preventDefault();if(submitting)return;
    const line=Number($('#correctedSpread').value),confirmed=$('#confirmSpread').checked,errorBox=$('#spreadError'),button=$('#saveSpreadCorrection');
    errorBox.hidden=true;
    if(!Number.isFinite(line)||Math.abs(line)>100||!confirmed){errorBox.textContent='Enter a valid spread and confirm the scoring change.';errorBox.hidden=false;return}
    submitting=true;button.disabled=true;button.textContent='Updating…';
    try{
      const reason=$('#spreadReason').value.trim();
      if(demo){const history=game.spreadHistory||[];history.push({previous:original,spread:line,changedAt:new Date().toISOString(),changedBy:user?.name||'Commissioner',reason});Object.assign(game,{spread:line,spreadHistory:history,bookmaker:'Commissioner correction'});localStorage.setItem('sc-games',JSON.stringify(games))}
      else await api('admin/spread',{season:editSeason,week:editWeek,id:game.id,spread:line,expectedSpread:original,confirmed,reason});
      if(slateDraft?.key===`${user?.id||'demo'}:${editSeason}:${editWeek}`){slateDraft.items[game.id].spread=line;slateDraft.base[game.id].spread=line}
      if(!demo)await load();else render();$('#modal').close();toast('Published spread updated. Existing picks are preserved.');
    }catch(error){errorBox.textContent=error.message;errorBox.hidden=false}
    finally{submitting=false;button.disabled=false;button.textContent='Update published spread'}
  });
}
function spreadCorrectionNotice(game){
  const change=game.spreadHistory?.at(-1);if(!change)return '';
  const side=saved[game.id]||picks[game.id]||'home',oldLine=side==='away'?-change.previous:change.previous,newLine=side==='away'?-change.spread:change.spread;
  return `<div class="spread-correction-notice"><strong>Commissioner corrected the line</strong><span>${esc(game[side+'Abbr']||game[side])}: ${signed(oldLine)} → ${signed(newLine)} · ${esc(new Date(change.changedAt).toLocaleString())}</span><p>${locked(game)?'This game uses the corrected spread.':'Review your pick before kickoff. Your selected team has not changed.'}${change.reason?' '+esc(change.reason):''}</p></div>`;
}
function bindSlateBuilder(){
  if(view!=='admin'||(!demo&&user?.role!=='admin'))return;
  document.querySelectorAll('[data-edit-spread]').forEach(button=>button.onclick=()=>editPublishedSpread(games.find(game=>game.id===button.dataset.editSpread)));
  $('#slateSearch')?.addEventListener('input',event=>{
    const position=event.target.selectionStart;slateFilters.search=event.target.value;render();
    const input=$('#slateSearch');input.focus();if(position!==null)input.setSelectionRange(position,position);
  });
  $('#slateConference')?.addEventListener('change',event=>{slateFilters.conference=event.target.value;render()});
  $('#slateRanking')?.addEventListener('change',event=>{slateFilters.ranking=event.target.value;render()});
  $('#slateConferenceOnly')?.addEventListener('change',event=>{slateFilters.conferenceOnly=event.target.checked;render()});
  $('#clearSlateFilters')?.addEventListener('click',()=>{slateFilters={search:'',conference:'all',ranking:'all',conferenceOnly:false,view:slateFilters.view};render()});
  document.querySelectorAll('[data-slate-view]').forEach(button=>button.onclick=()=>{slateFilters.view=button.dataset.slateView;render()});
  document.querySelectorAll('[data-include]').forEach(input=>input.addEventListener('change',()=>{setSlateSelection([input.dataset.include],input.checked);render()}));
  document.querySelectorAll('[data-spread]').forEach(input=>input.addEventListener('input',()=>{
    const value=input.value===''?null:Number(input.value);
    const valid=value===null||(Number.isFinite(value)&&Math.abs(value)<=100);
    input.setCustomValidity(valid?'':'Enter a spread between -100 and 100.');
    const item=slateDraft.items[input.dataset.spread],game=games.find(game=>game.id===input.dataset.spread);
    item.spread=value;if(value===null||!valid)item.included=false;
    const checkbox=$(`[data-include="${input.dataset.spread}"]`);
    checkbox.checked=item.included;checkbox.disabled=locked(game)||(game.included&&game.hasPicks)||(!item.included&&!canSelectSlateGame(game));
    const changed=slateHasChanges(),selected=games.filter(game=>slateDraft.items[game.id].included).length;
    $('#slateSelectedCount').textContent=selected;$('#slateSelectedFooter').textContent=`${selected} games selected`;
    $('#slateDraftStatus').textContent=slateHasInvalidSpread()?'Fix invalid spreads before publishing':changed?'● Unpublished changes':'✓ Slate is up to date';$('#slateDraftStatus').classList.toggle('pending',changed);
    $('#saveSlate').disabled=!changed||slateHasInvalidSpread();$('#discardSlate').disabled=!changed;
    $('[data-slate-view="selected"]').textContent=`Your slate (${selected})`;
    const visible=filteredSlateGames(),addable=visible.filter(game=>!slateDraft.items[game.id].included&&canSelectSlateGame(game)).length,removable=visible.filter(game=>slateDraft.items[game.id].included&&canRemoveSlateGame(game)).length;
    $('#addVisible').textContent=`Add visible (${addable})`;$('#addVisible').disabled=!addable;$('#removeVisible').textContent=`Remove visible (${removable})`;$('#removeVisible').disabled=!removable;
    input.closest('.slate-row').classList.toggle('in-slate',item.included);
  }));
  $('#addVisible')?.addEventListener('click',()=>{const count=setSlateSelection(filteredSlateGames().map(game=>game.id),true);render();toast(`${count} games added to your draft slate.`)});
  $('#removeVisible')?.addEventListener('click',()=>{const count=setSlateSelection(filteredSlateGames().map(game=>game.id),false);render();toast(`${count} games removed from your draft slate. Protected games were kept.`)});
  $('#discardSlate')?.addEventListener('click',()=>{slateDraft=null;render();toast('Unpublished changes discarded.')});
  $('#saveSlate')?.addEventListener('click',async event=>{
    if(slateHasInvalidSpread())return toast('Enter valid spreads between -100 and 100 before publishing.');
    const changes=slateChanges();if(!changes.length)return;
    event.target.disabled=true;event.target.textContent='Publishing…';
    try{
      if(demo){for(const game of games){const item=changes.find(item=>item.id===game.id);if(item)Object.assign(game,item)}localStorage.setItem('sc-games',JSON.stringify(games));slateDraft=null;render()}
      else{await api('admin/slate',{season,week,games:changes});slateDraft=null;await load()}
      toast('Weekly slate published. Players can now pick these games.');
    }catch(error){toast(error.message);render()}
  });
}
function showInvitation(code,name,delivery='link'){
  const link=new URL('/',location.origin);link.searchParams.set('invite',code);
  const message=`You're invited to Saturday Club by 4th & Soul. Join our college football pick'em league: ${link.href} This invitation is single-use and expires in 7 days.`;
  const email='mailto:?'+new URLSearchParams({subject:'Join Saturday Club',body:`Hi ${name},\n\n${message}`}).toString().replace(/\+/g,'%20');
  const sms='sms:'+(/iPad|iPhone|iPod/.test(navigator.userAgent)?'&':'?')+'body='+encodeURIComponent(message);
  $('#inviteResult').innerHTML=`<div class="invitation-share">${delivery==='email'?'<p role="status">Email service accepted your invitation. Delivery may take a moment.</p>':''}<p>Invitation for <strong>${esc(name)}</strong> · Single use · Expires in 7 days</p><label class="field">Invitation link<input id="inviteLink" readonly value="${esc(link.href)}"></label><div class="social-buttons"><button type="button" class="button" id="copyInvite">Copy link</button><a class="button" href="${esc(email)}">Email invitation</a><a class="button" href="${esc(sms)}">Text invitation</a></div><p class="form-status">Email and text open a prefilled message in your own app. Choose the recipient and send it there. You can also share the registration code: ${esc(code)}</p></div>`;
  $('#copyInvite').onclick=async()=>{
    try{await navigator.clipboard.writeText(link.href);toast('Invitation link copied.')}
    catch(error){$('#inviteLink').focus();$('#inviteLink').select();toast('Select and copy the invitation link.')}
  };
}
function rememberInvite(code){
  pendingInviteCode=code;
  try{if(code)sessionStorage.setItem('sc-pending-invite',code);else sessionStorage.removeItem('sc-pending-invite')}catch(error){}
}
function readInvitation(){
  if(!location.search)return false;
  const url=new URL(location.href),code=url.searchParams.get('invite');
  if(!code)return false;
  rememberInvite(code.slice(0,200));url.searchParams.delete('invite');
  window.history.replaceState(null,'',url.pathname+url.search+url.hash);
  return true;
}
async function socialControls(){
  const container=$('#socialOptions');
  if(!container||demo)return;
  try{
    const data=await api('auth/providers');
    if($('#socialOptions')!==container)return;
    container.innerHTML=data.providers?.length?`<p class="social-caption">${user?'Connect a sign-in method to your existing league account.':'New members need an invitation. Returning members can continue with a connected account.'}</p><div class="social-buttons">${data.providers.map(p=>`<button type="button" class="button social-button" data-social="${esc(p.id)}" ${p.connected?'disabled':''}>${p.connected?'Connected to':user?'Connect':'Continue with'} ${esc(p.name)}</button>`).join('')}</div>`:'';
    container.querySelectorAll('[data-social]').forEach(button=>button.addEventListener('click',async()=>{
      const errorBox=$('#socialError');errorBox.hidden=true;
      container.querySelectorAll('button').forEach(b=>b.disabled=true);
      button.textContent='Connecting…';
      try{
        const code=$('#loginForm')?.elements.code.value.trim()||'';
        if(!user)rememberInvite(code);
        const result=await api('auth/start',{provider:button.dataset.social,code},{timeoutMs:15000});
        window.location.assign(result.url);
      }catch(error){errorBox.textContent=error.message;errorBox.hidden=false;errorBox.focus();await socialControls()}
    }));
  }catch(error){container.innerHTML='<p class="form-status">Social sign-in is unavailable right now. Please try again later.</p>'}
}
function handleAuthReturn(){
  if(passwordResetToken){resetPasswordModal();return}
  if(pendingInviteCode&&!user)accountModal();
  if(!location.search)return;
  const url=new URL(location.href),error=url.searchParams.get('auth_error'),success=url.searchParams.has('auth_success');
  if(!error&&!success)return;
  url.searchParams.delete('auth_error');url.searchParams.delete('auth_success');
  window.history.replaceState(null,'',url.pathname+url.search+url.hash);
  if(error){
    accountModal();
    const messages={expired:'This sign-in attempt expired or was already used. Please try again.',cancelled:'Sign-in was cancelled. Your invitation has not been used.',invite:'A valid, unused invitation is required to join Saturday Club.',email:'Your provider must share an email address to create your account.',existing:'This email already has a league account. Sign in with your existing method, then connect this provider from your account.',disabled:'This league account is disabled. Contact your commissioner.',link:'Sign in to the original league account again before connecting this provider.',connected:'This provider account is already connected to another league account.'};
    const box=$('#socialError');box.textContent=messages[error]||'We could not verify your provider account. Please try again.';box.hidden=false;box.focus();
  }else if(!user){
    accountModal();const box=$('#socialError');box.textContent='Your league session could not be opened. Allow cookies for this site, check your connection, and try signing in again.';box.hidden=false;box.focus();
  }else{rememberInvite('');toast('You’re connected. Welcome to the Club.');}
}
function readPasswordReset(){
  if(!location.hash?.startsWith('#reset-password='))return;
  passwordResetToken=location.hash.slice('#reset-password='.length).slice(0,200);
  const url=new URL(location.href);url.hash='';window.history.replaceState(null,'',url.pathname+url.search);
}
function forgotPasswordModal(email=''){
  modal(`<h2>Reset your password.</h2><p>Enter your league email. If an active account matches, we’ll email a link that expires in 30 minutes.</p><form id="forgotForm"><label class="field">Email<input name="email" type="email" autocomplete="email" value="${esc(email)}" maxlength="254" required></label><div id="forgotError" class="form-error" role="alert" tabindex="-1" hidden></div><p id="forgotStatus" class="form-status" role="status" aria-live="polite"></p><div class="form-actions"><button type="submit" class="button primary" id="sendReset">Send reset link</button><button type="button" class="button" id="backToSignin">Back to sign in</button></div></form><p class="form-status">Your password stays the same until you use the link. <a href="/privacy.html">Privacy &amp; security</a> · <a href="/terms.html" target="_blank" rel="noopener">Terms of service</a></p>`);
  $('#backToSignin').onclick=accountModal;
  const form=$('#forgotForm'),button=$('#sendReset');let submitting=false;
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(submitting)return;submitting=true;button.disabled=true;button.textContent='Sending…';$('#forgotError').hidden=true;
    try{const result=await api('password/forgot',{email:form.elements.email.value.trim()},{timeoutMs:15000});$('#forgotStatus').textContent=result.message;button.textContent='Request another link'}
    catch(error){const box=$('#forgotError');box.textContent=error.message;box.hidden=false;box.focus();button.textContent='Send reset link'}
    finally{submitting=false;button.disabled=false}
  });
}
function resetPasswordModal(){
  modal(`<h2>Choose a new password.</h2><p>Use a unique password or passphrase of 12 to 256 characters. Updating it signs your account out on all devices.</p><form id="resetForm"><label class="field">New password<input id="resetPassword" name="password" type="password" autocomplete="new-password" minlength="12" maxlength="256" required></label><br><label class="field">Confirm new password<input id="resetConfirmation" name="confirm" type="password" autocomplete="new-password" minlength="12" maxlength="256" required></label><button type="button" class="button password-toggle reset-toggle" id="toggleResetPassword" aria-controls="resetPassword resetConfirmation" aria-pressed="false">Show passwords</button><div id="resetError" class="form-error" role="alert" tabindex="-1" hidden></div><div class="form-actions"><button type="submit" class="button primary" id="saveNewPassword">Update password</button><button type="button" class="button" id="requestNewReset">Request a new link</button></div></form><p class="form-status">The reset link works once. If you refresh this page, reopen the link from your email.</p>`);
  const form=$('#resetForm'),button=$('#saveNewPassword');let submitting=false;
  $('#requestNewReset').onclick=()=>{passwordResetToken='';forgotPasswordModal()};
  $('#toggleResetPassword').onclick=()=>{
    const show=form.elements.password.type==='password';form.elements.password.type=show?'text':'password';form.elements.confirm.type=show?'text':'password';
    $('#toggleResetPassword').textContent=show?'Hide passwords':'Show passwords';$('#toggleResetPassword').setAttribute('aria-pressed',String(show));
  };
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(submitting)return;
    const errorBox=$('#resetError');errorBox.hidden=true;
    if(form.elements.password.value!==form.elements.confirm.value){errorBox.textContent='Your passwords do not match.';errorBox.hidden=false;errorBox.focus();return}
    submitting=true;button.disabled=true;button.textContent='Updating…';
    try{
      await api('password/reset',{token:passwordResetToken,password:form.elements.password.value},{timeoutMs:15000});
      passwordResetToken='';rememberInvite('');await load();accountModal();$('#loginStatus').textContent='Password updated. Sign in with your new password.';
    }catch(error){errorBox.textContent=error.message;errorBox.hidden=false;errorBox.focus()}
    finally{submitting=false;button.disabled=false;button.textContent='Update password'}
  });
}
function accountModal(){
  if(user&&!demo){
    modal(`<h2>${esc(user.name)}</h2><p>You’re signed in as a ${esc(user.role)}.</p><p class="form-status"><a href="/privacy.html" target="_blank" rel="noopener">Privacy &amp; security</a> · <a href="/terms.html" target="_blank" rel="noopener">Terms of service</a></p><div id="socialOptions"></div><div id="socialError" class="form-error" role="alert" tabindex="-1" hidden></div><button class="button" id="logout">Sign out</button>`);
    if(!demo)socialControls();
    $('#logout').onclick=async()=>{await api('logout',{});$('#modal').close();await load()};return;
  }
  modal(`<h2>${demo?'Welcome to the Club.':'Sign in to Saturday Club.'}</h2><p>${demo?'This hosted preview uses sample data. Shared accounts are available when you run the included AWS backend.':'Sign in with your league account, or enter an invite code to create one.'}</p>${!demo?`<form id="loginForm"><label class="field">Email<input name="email" type="email" autocomplete="username" required></label><br><div class="password-field"><label class="field" for="loginPassword">Password</label><div class="password-controls"><input id="loginPassword" name="password" type="password" autocomplete="current-password" minlength="10" required><button type="button" class="button password-toggle" id="togglePassword" aria-controls="loginPassword" aria-pressed="false">Show password</button></div></div><br><label class="field">Invite code (new members only)<input name="code" autocomplete="off"></label><p class="form-status"><a href="/privacy.html" target="_blank" rel="noopener">Privacy &amp; security</a> · <a href="/terms.html" target="_blank" rel="noopener">Terms of service</a></p><div id="socialOptions"></div><div id="socialError" class="form-error" role="alert" tabindex="-1" hidden></div><div id="loginError" class="form-error" role="alert" tabindex="-1" hidden></div><div class="form-actions"><button type="submit" class="button primary" id="loginSubmit">Sign in</button></div><p id="loginStatus" class="form-status" role="status" aria-live="polite"></p><button type="button" class="text-button" id="forgotPassword">Forgot password?</button></form>`:'<button class="button primary" id="demoContinue">Explore the demo</button>'}`);
  $('#demoContinue')?.addEventListener('click',()=>$('#modal').close());
  const form=$('#loginForm');
  if(demo||!form)return;
  $('#forgotPassword').addEventListener('click',()=>forgotPasswordModal(form.elements.email.value.trim()));
  $('#togglePassword').addEventListener('click',()=>{
    const input=form.elements.password,button=$('#togglePassword'),show=input.type==='password';
    input.type=show?'text':'password';button.textContent=show?'Hide password':'Show password';button.setAttribute('aria-pressed',String(show));
  });
  if(pendingInviteCode)form.elements.code.value=pendingInviteCode;
  socialControls();
  let submitting=false;
  const button=$('#loginSubmit'),errorBox=$('#loginError'),status=$('#loginStatus');
  const label=()=>form.elements.code.value.trim()?'Create account':'Sign in';
  button.textContent=label();
  form.elements.code.addEventListener('input',()=>{if(!submitting)button.textContent=label()});
  form.addEventListener('submit',async event=>{
    event.preventDefault();
    if(submitting)return;
    submitting=true;button.disabled=true;form.setAttribute('aria-busy','true');
    errorBox.hidden=true;errorBox.textContent='';
    const data=Object.fromEntries(new FormData(form));
    data.email=data.email.trim();data.code=data.code.trim();
    button.textContent=data.code?'Creating account…':'Signing in…';status.textContent=button.textContent;
    try{
      await api(data.code?'register':'login',data,{timeoutMs:15000});
      status.textContent='Opening your league…';
      await load({requireUser:true});
      rememberInvite('');
      $('#modal').close();
      toast('You’re signed in. Welcome to the Club.');
    }catch(error){
      errorBox.textContent=error.message;errorBox.hidden=false;status.textContent='';errorBox.focus();
    }finally{
      submitting=false;button.disabled=false;button.textContent=label();form.removeAttribute('aria-busy');
    }
  });
}
$('#account').onclick=accountModal;$('#mobileAccount')?.addEventListener('click',accountModal);$('#rules').onclick=()=>modal('<h2>A simple game. A long season.</h2><p>Choose either team against the commissioner’s fixed point spread. Cover: 1 point. Push: 0.5 points. Miss or no pick: 0 points.</p><p>Each game locks at kickoff. Feed lines freeze when published. Commissioners may correct a spread before kickoff; corrections are shown on the game card. Canceled games are void. Final scores determine standings; tied point totals share a rank.</p>');$('#season').onchange=()=>{season=parseInt($('#season').value);if(demo)render();else load()};window.onhashchange=()=>{readPasswordReset();render();if(passwordResetToken)resetPasswordModal()};if(serverBacked){$('#connection').textContent='● CONNECTING';$('#profileName').innerHTML='Sign in<small>Join your friends</small>'}try{pendingInviteCode=sessionStorage.getItem('sc-pending-invite')||''}catch(error){}readPasswordReset();readInvitation();render();load().then(handleAuthReturn);setInterval(refreshLive,5000);document.addEventListener?.('visibilitychange',()=>{if(document.visibilityState!=='hidden')refreshLive()});window.addEventListener?.('online',refreshLive);

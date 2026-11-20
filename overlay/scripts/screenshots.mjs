// Visual check of the built overlay page against fixture payloads, outside Tauri.
// Usage: npm run build && node scripts/screenshots.mjs   (writes shots/*.png)
// Needs playwright (npm i -D playwright, or PLAYWRIGHT_CHROMIUM=/path/to/chrome).
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
import { createServer } from 'node:http';
import { readFileSync, existsSync } from 'node:fs';
import { join, extname } from 'node:path';

const dist = new URL('../dist/', import.meta.url).pathname;
const types = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.png': 'image/png', '.svg': 'image/svg+xml' };
const server = createServer((req, res) => {
  const path = req.url.split('?')[0];
  let p = join(dist, path === '/' ? 'index.html' : path);
  if (!existsSync(p)) p = join(dist, 'index.html');
  res.writeHead(200, { 'content-type': types[extname(p)] ?? 'application/octet-stream' });
  res.end(readFileSync(p));
});
await new Promise((r) => server.listen(5199, r));

// Fixtures: build the same states the vitest fixtures use, in plain JS.
const card = (name, type, cost, total, left, lib) => {
  const mv = cost ? (cost.match(/\{([^}]+)\}/g) ?? []).reduce((s, x) => s + (/^\{\d+\}$/.test(x) ? Number(x.slice(1, -1)) : 1), 0) : 0;
  const odds = (n) => (left <= 0 || lib <= 0 ? 0 : Math.round((1 - [...Array(Math.min(n, lib))].reduce((r, _, i) => (r * (lib - left - i)) / (lib - i), 1)) * 1000) / 10);
  return { name, type_category: type, mana_cost: cost, mana_value: mv, total, left, land: type === 'Land', basic: ['Plains','Island','Swamp','Mountain','Forest'].includes(name), odds: { 1: odds(1), 2: odds(2), 3: odds(3) } };
};
const lib = 41;
const cards = [
  card('Monastery Swiftspear','Creature','{R}',4,2,lib), card('Heartfire Hero','Creature','{R}',4,3,lib), card('Emberheart Challenger','Creature','{1}{R}',4,4,lib),
  card('Slickshot Show-Off','Creature','{1}{R}',4,3,lib), card('Screaming Nemesis','Creature','{2}{R}',3,2,lib), card('Lightning Strike','Instant','{1}{R}',4,3,lib),
  card('Monstrous Rage','Instant','{R}',4,4,lib), card('Shock','Instant','{R}',4,0,lib), card('Torch the Tower','Instant','{R}',2,2,lib), card('Witchstalker Frenzy','Instant','{2}{R}',2,2,lib),
  card('Burst Lightning','Instant','{R}',3,3,lib), card('Kumano Faces Kakkazan','Enchantment','{R}',2,2,lib), card('Mountain','Land',null,16,8,lib), card('Rockface Village','Land',null,4,3,lib),
];
const sideboard = [
  { name: 'Obliterating Bolt', type_category: 'Sorcery', mana_cost: '{1}{R}', mana_value: 2, count: 3, land: false },
  { name: "Urabrask's Forge", type_category: 'Artifact', mana_cost: '{2}{R}', mana_value: 3, count: 2, land: false },
  { name: 'Torch the Tower', type_category: 'Instant', mana_cost: '{R}', mana_value: 1, count: 2, land: false },
];
const inGame = { game_active:true, mid_game_attach:false, deck_name:'Mono-Red Aggro', format_label:'Standard Best-of-1 (Ranked)', match_type:'Ladder', opponent_name:'sansastark', turn_number:5, on_play:true, player_commanders:[], opponent_commanders:[], deck_size:60, library_size:lib, unaccounted:0, lands_left:11, lands_total:20, land_odds:{1:26.8,2:47.3,3:62.1}, cards, sideboard, updated_at:'x' };
const blib = 84;
const bnames = ['Sol Ring','Arcane Signet','Swords to Plowshares','Counterspell','Teferi, Hero of Dominaria','Wrath of God','Mulldrifter','Path to Exile','Esper Sentinel','Thalia, Guardian of Thraben','Consecrated Sphinx','Dovin\'s Veto'];
const bcards = bnames.map((n,i)=>card(n, i%2?'Instant':'Creature', i%3?'{1}{W}':'{U}{U}', 1, i<3?0:1, blib));
bcards.push(card('Plains','Land',null,18,15,blib), card('Island','Land',null,16,14,blib), card('Hallowed Fountain','Land',null,1,1,blib));
const brawl = { ...inGame, deck_name:'Azorius Control', format_label:'Historic Brawl', opponent_name:'Zephyr', on_play:false, player_commanders:['Teferi, Time Raveler'], deck_size:100, library_size:blib, lands_left:30, lands_total:35, cards:bcards };
const today = { games:8, wins:6, losses:2, draws:0, win_rate:75, play:{wins:4,losses:1}, draw:{wins:2,losses:1}, rank:{rank_class:'Diamond',rank_level:2,rank_step:3,rank_steps:6,mythic_percentile:null,mythic_rank:null}, deck:{wins:3,losses:1} };
// The flood meter's numbers (live_status.draw_quality): 7 lands in 12 cards from 60 with 22, flooding.
const drawQuality = { lands_seen:7, total_cards_seen:12, expected_lands_seen:4.4, expected_land_rate:36.7, deck_size:60, deck_lands:22, is_flood:true, is_screw:false, is_land_streak:false };
// The opponent panel's block (live_api._overlay_opponent).
const seen = [
  { name:'Swamp', type:'Land', mana_cost:null, mana_value:0, count:2 }, { name:'Bloodtithe Harvester', type:'Creature', mana_cost:'{B}{R}', mana_value:2, count:1 },
  { name:'Blood Crypt', type:'Land', mana_cost:null, mana_value:0, count:1 }, { name:'Go for the Throat', type:'Instant', mana_cost:'{1}{B}', mana_value:2, count:2 },
  { name:'Fable of the Mirror-Breaker // Reflection of Kiki-Jiki', type:'Enchantment', mana_cost:'{2}{R}', mana_value:3, count:1 },
  { name:'Mountain', type:'Land', mana_cost:null, mana_value:0, count:1 }, { name:'Cut Down', type:'Instant', mana_cost:'{B}', mana_value:1, count:1 },
  { name:'Sheoldred, the Apocalypse', type:'Creature', mana_cost:'{2}{B}{B}', mana_value:4, count:1 }, { name:'Duress', type:'Sorcery', mana_cost:'{B}', mana_value:1, count:1 },
];
const opponent = { colors:'BR', lands:4, deck:{ label:'Rakdos Midrange', source:'history', matched_cards:3 }, record:{ wins:3, losses:1 }, seen };
const opponentColors = { colors:'WU', lands:2, deck:{ label:'Azorius', source:'colors', matched_cards:null }, record:{ wins:5, losses:7 }, seen:[{ name:'Plains', type:'Land', mana_cost:null, mana_value:0, count:1 }, { name:'Island', type:'Land', mana_cost:null, mana_value:0, count:1 }, { name:'Get Lost', type:'Instant', mana_cost:'{1}{W}{W}', mana_value:3, count:1 }] };
const opponentEmpty = { colors:'', lands:0, deck:{ label:null, source:'none', matched_cards:null }, record:null, seen:[] };
const opponentBrawl = { colors:'WUBRG', lands:3, deck:{ label:'Kenrith, the Returned King', source:'commander', matched_cards:null }, record:{ wins:12, losses:10 }, seen:[{ name:'Arcane Signet', type:'Artifact', mana_cost:'{2}', mana_value:2, count:1 }, { name:'Command Tower', type:'Land', mana_cost:null, mana_value:0, count:1 }] };
const payloads = {
  game: { tracker:{state:'live',updated_at:'x',session_id:'s'}, state: inGame, head_to_head:{wins:1,losses:2}, today, opponent, draw_quality: drawQuality },
  screw: { tracker:{state:'live',updated_at:'x',session_id:'s'}, state: inGame, head_to_head:{wins:1,losses:2}, today, draw_quality: { ...drawQuality, lands_seen:1, is_flood:false, is_screw:true } },
  oppColors: { tracker:{state:'live',updated_at:'x',session_id:'s'}, state: inGame, head_to_head:null, opponent: opponentColors },
  oppEmpty: { tracker:{state:'live',updated_at:'x',session_id:'s'}, state: { ...inGame, turn_number:1 }, head_to_head:null, opponent: opponentEmpty },
  oppBrawl: { tracker:{state:'live',updated_at:'x',session_id:'s'}, state: brawl, head_to_head:{wins:2,losses:0}, opponent: opponentBrawl },
  brawl: { tracker:{state:'live',updated_at:'x',session_id:'s'}, state: brawl, head_to_head:null },
  final: { tracker:{state:'live',updated_at:'x',session_id:'s'}, state: { ...inGame, game_active:false, game_over:true }, head_to_head:{wins:2,losses:2} },
  // Half the library milled in a message Arena only summarized: 24 cards gone unnamed.
  unseen: { tracker:{state:'live',updated_at:'x',session_id:'s'}, state: { ...inGame, turn_number:11, library_size:21, unseen:24, draw_pool:45 }, head_to_head:{wins:1,losses:2} },
  // The summary has been logged and the library not listed since.
  gap: { tracker:{state:'live',updated_at:'x',session_id:'s'}, state: { ...inGame, turn_number:10, log_gap:true }, head_to_head:{wins:1,losses:2} },
  idle: { tracker:{state:'idle',updated_at:null,session_id:'s'}, state: { ...inGame, game_active:false, deck_name:null, cards:[], library_size:0, deck_size:0 }, head_to_head:null, today },
};

mkdirSync(new URL('../shots/', import.meta.url), { recursive: true });
// A stand-in for Scryfall's card image (488x680) so hover shots need no network.
const cardSvg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 488 680"><rect width="488" height="680" rx="22" fill="#265634"/><rect x="18" y="18" width="452" height="644" rx="14" fill="none" stroke="#c8be96" stroke-width="6"/><rect x="40" y="90" width="408" height="310" fill="#467850"/><text x="48" y="60" font-family="sans-serif" font-size="26" fill="#f0e6c8">Card image</text><text x="48" y="440" font-family="sans-serif" font-size="20" fill="#f0e6c8">Instant</text></svg>`;
const browser = await chromium.launch(process.env.PLAYWRIGHT_CHROMIUM ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM } : {});
// `node scripts/screenshots.mjs unseen` renders only the shots whose name has that text.
const only = process.argv[2];
// `settings` starts the page from other settings (the browser stub reads window.__TAPPS_SETTINGS__).
async function shot(name, fixture, size, steps, path = '/', settings = null) {
  if (only && !name.includes(only)) return;
  const ctx = await browser.newContext({ viewport: size, deviceScaleFactor: 2 });
  const page = await ctx.newPage();
  if (settings) await page.addInitScript((value) => { window.__TAPPS_SETTINGS__ = value; }, settings);
  page.on('pageerror', (e) => console.log('PAGE ERROR', name, e.message));
  page.on('console', (m) => { if (m.type() === 'error') console.log('CONSOLE', name, m.text()); });
  await page.route('https://api.scryfall.com/**', (route) => route.fulfill({ status: 200, contentType: 'image/svg+xml', body: cardSvg }));
  await page.route('**/api/overlay', (route) => fixture === 'offline' ? route.abort() : route.fulfill({ status: 200, contentType: 'application/json', headers: { ETag: '"1"' }, body: JSON.stringify(payloads[fixture]) }));
  await page.goto(`http://127.0.0.1:5199${path}`);
  await page.waitForTimeout(400);
  if (steps) await steps(page);
  await page.waitForTimeout(250);
  await page.screenshot({ path: `shots/${name}.png`, omitBackground: false });
  const h = await page.evaluate(() => { const r = document.querySelector('.opp-rail'); if (r) { const kids = Array.from(r.children); const cs = getComputedStyle(r); return { oppRailNatural: kids.reduce((s, k) => s + k.offsetHeight, 0) + parseFloat(cs.rowGap || cs.gap || 0) * (kids.length - 1) + parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom) }; } const op = document.querySelector('.panel.opp'); if (op) { let t = 0; for (const c of op.children) t += c.classList.contains('list') ? (c.querySelector('.list-body')?.offsetHeight ?? 0) : c.offsetHeight; return { oppNatural: t }; } const p = document.querySelector('.panel'); const l = p?.querySelector('.list'); const b = p?.querySelector('.list-body'); return p ? { panel: p.offsetHeight, list: l?.clientHeight, rows: b?.offsetHeight, natural: b ? p.offsetHeight - l.clientHeight + b.offsetHeight : null } : null; });
  console.log(name, JSON.stringify(h));
  await ctx.close();
}
const board = async (page) => { await page.addStyleTag({ content: 'body{background:radial-gradient(900px 500px at 60% 40%, #4d6a8a 0%, #2d4a6a 45%, #6b3a2a 100%) !important}' }); };
const openPanel = async (page) => { await page.click('button[aria-label="Open the deck panel"]'); await page.mouse.move(400, 400); await page.waitForTimeout(100); };
await shot('rail-game', 'game', { width: 58, height: 258 });
await shot('rail-offline', 'offline', { width: 58, height: 258 });
await shot('rail-warn', 'game', { width: 58, height: 258 }, async (page) => { await page.evaluate(() => { const b = document.querySelector('.rail .bar'); b.className = 'bar warn'; b.firstElementChild.style.width = '45%'; document.querySelector('.rail .v.lib b').textContent = '27'; }); });
await shot('rail-low', 'game', { width: 58, height: 258 }, async (page) => { await page.evaluate(() => { const b = document.querySelector('.rail .bar'); b.className = 'bar low'; b.firstElementChild.style.width = '18%'; document.querySelector('.rail .v.lib b').textContent = '11'; }); });
await shot('panel-game', 'game', { width: 583, height: 560 }, openPanel);
await shot('panel-hover', 'game', { width: 583, height: 560 }, async (page) => { await board(page); await openPanel(page); await page.hover('.list-body .row:nth-of-type(4)'); });
await shot('panel-sideboard', 'game', { width: 583, height: 560 }, async (page) => { await board(page); await openPanel(page); await page.click('.land-row'); await page.click('.side-row'); await page.mouse.move(10, 10); });
await shot('panel-left-hover', 'game', { width: 583, height: 560 }, async (page) => { await board(page); await openPanel(page); await page.click('button[aria-label="Settings"]'); await page.click('[aria-label="Dock"] button:has-text("Left")'); await page.click('button[aria-label="Close settings"]'); await page.hover('.list-body .row:nth-of-type(4)'); });
await shot('panel-flyout', 'game', { width: 583, height: 700 }, async (page) => { await openPanel(page); await page.click('button[aria-label="Settings"]'); });
// Settings beside the rail: the window lends the rail a gutter (58 + 338 wide).
await shot('rail-flyout', 'game', { width: 396, height: 700 }, async (page) => { await page.click('.rail button[aria-label="Overlay settings"]'); });
await shot('rail-flyout-left', 'game', { width: 396, height: 700 }, async (page) => { await page.click('.rail button[aria-label="Overlay settings"]'); await page.click('[aria-label="Dock"] button:has-text("Left")'); });
await shot('panel-brawl', 'brawl', { width: 583, height: 560 }, openPanel);
await shot('panel-final', 'final', { width: 583, height: 560 }, async (page) => { await board(page); await openPanel(page); });
await shot('panel-unseen', 'unseen', { width: 583, height: 600 }, async (page) => { await board(page); await openPanel(page); });
await shot('panel-unseen-gap', 'gap', { width: 583, height: 600 }, async (page) => { await board(page); await openPanel(page); });
await shot('panel-idle', 'idle', { width: 583, height: 200 }, openPanel);
await shot('panel-offline', 'offline', { width: 583, height: 200 }, openPanel);
await shot('rail-nobg', 'game', { width: 58, height: 258 }, board);
// The rail's own opacity slider: 0 leaves the rail bare while the panel keeps its default tint.
await shot('rail-op0', 'game', { width: 58, height: 258 }, async (page) => { await board(page); await page.evaluate(() => { const root = document.querySelector('.root'); root.classList.remove('has-bg'); root.classList.add('no-bg'); root.style.setProperty('--rail-alpha', '0'); }); });
await shot('panel-nobg', 'game', { width: 583, height: 560 }, async (page) => { await board(page); await openPanel(page); });
await shot('panel-op100', 'game', { width: 583, height: 560 }, async (page) => { await board(page); await openPanel(page); await page.click('button[aria-label="Settings"]'); await page.evaluate(() => { const el = document.querySelector('input[aria-label="Background opacity"]'); const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set; set.call(el, '100'); el.dispatchEvent(new Event('input', { bubbles: true })); }); await page.click('button[aria-label="Close settings"]'); });
await shot('panel-op20', 'game', { width: 583, height: 560 }, async (page) => { await board(page); await openPanel(page); await page.click('button[aria-label="Settings"]'); await page.evaluate(() => { const el = document.querySelector('input[aria-label="Background opacity"]'); const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set; set.call(el, '20'); el.dispatchEvent(new Event('input', { bubbles: true })); }); await page.click('button[aria-label="Close settings"]'); });
await shot('panel-nobg-flyout', 'game', { width: 583, height: 560 }, async (page) => { await board(page); await openPanel(page); await page.click('button[aria-label="Settings"]'); });
await shot('panel-scale150', 'game', { width: 845, height: 720 }, async (page) => { await board(page); await openPanel(page); await page.click('button[aria-label="Settings"]'); await page.evaluate(() => { const el = document.querySelector('input[aria-label="Scale, percent"]'); const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set; set.call(el, '150'); el.dispatchEvent(new Event('input', { bubbles: true })); }); await page.click('button[aria-label="Close settings"]'); });
await shot('panel-all-lands', 'game', { width: 583, height: 640 }, async (page) => { await openPanel(page); await page.click('button[aria-label="Settings"]'); await page.click('text=Every land'); await page.click('button[aria-label="Close settings"]'); });
// Today's record footer: the Full style (the record widget's layout), and between games.
// The page cannot resize this viewport the way the overlay window follows its list, so these
// use each state's natural height (the `natural` value logged below): nothing scrolls, as in the app.
await shot('panel-today-split', 'game', { width: 583, height: 736 }, async (page) => { await openPanel(page); await page.click('button[aria-label="Settings"]'); await page.click('[aria-label="Today\'s record"] button:has-text("Full")'); await page.click('button[aria-label="Close settings"]'); });
await shot('panel-today-split-nobg', 'game', { width: 583, height: 736 }, async (page) => { await board(page); await openPanel(page); await page.click('button[aria-label="Settings"]'); await page.click('[aria-label="Today\'s record"] button:has-text("Full")'); await page.click('button[aria-label="Close settings"]'); });
await shot('panel-today-nobg', 'game', { width: 583, height: 704 }, async (page) => { await board(page); await openPanel(page); });
await shot('panel-today-compact', 'game', { width: 583, height: 602 }, async (page) => { await openPanel(page); await page.click('button[aria-label="Settings"]'); await page.click('[aria-label="Density"] button:has-text("Compact")'); await page.click('button[aria-label="Close settings"]'); });
// The flood meter (Settings → Bottom of the panel → Flood meter): above today's record by default, below it, and in Mana screw.
await shot('panel-flood-below', 'game', { width: 583, height: 760 }, async (page) => { await openPanel(page); await page.click('button[aria-label="Settings"]'); await page.click('[aria-label="Flood meter"] button:has-text("Below")'); await page.click('[aria-label="Today\'s record"] button:has-text("Full")'); await page.click('button[aria-label="Close settings"]'); });
await shot('panel-flood-screw', 'screw', { width: 583, height: 760 }, async (page) => { await board(page); await openPanel(page); });
// The opponent window (?view=opponent): its rail on the right edge (beside a
// left-docked deck panel), and its panel with the gutter on the board side.
const OPP = '/?view=opponent';
const openOpp = async (page) => { await page.click('button[aria-label="Open the opponent panel"]'); await page.mouse.move(10, 10); await page.waitForTimeout(100); };
await shot('opp-rail', 'game', { width: 58, height: 196 }, null, OPP);
await shot('opp-rail-empty', 'oppEmpty', { width: 58, height: 196 }, null, OPP);
await shot('opp-rail-brawl', 'oppBrawl', { width: 58, height: 196 }, board, OPP);
await shot('opp-panel', 'game', { width: 583, height: 400 }, async (page) => { await board(page); await openOpp(page); }, OPP);
await shot('opp-panel-hover', 'game', { width: 583, height: 520 }, async (page) => { await board(page); await openOpp(page); await page.hover('.list-body .row:nth-of-type(3)'); }, OPP);
await shot('opp-panel-colors', 'oppColors', { width: 583, height: 220 }, async (page) => { await board(page); await openOpp(page); }, OPP);
await shot('opp-panel-empty', 'oppEmpty', { width: 583, height: 200 }, async (page) => { await board(page); await openOpp(page); }, OPP);
await shot('opp-panel-brawl', 'oppBrawl', { width: 583, height: 240 }, async (page) => { await board(page); await openOpp(page); }, OPP);
// Opponent only (Settings → Panels): the opponent panel carries the ⚙, and the deck window is empty until the settings open in it.
await shot('opp-only-panel', 'game', { width: 583, height: 400 }, async (page) => { await board(page); await openOpp(page); }, OPP, { deckPanel: false });
await shot('opp-only-deck-window', 'game', { width: 396, height: 258 }, board, '/', { deckPanel: false });
await shot('opp-only-settings', 'game', { width: 396, height: 760 }, async (page) => { await board(page); await page.evaluate(() => window.dispatchEvent(new CustomEvent('tapps:overlay-open-settings'))); }, '/', { deckPanel: false });
await shot('opp-panel-nobg', 'game', { width: 583, height: 400 }, async (page) => { await board(page); await openOpp(page); await page.evaluate(() => { const root = document.querySelector('.root'); root.classList.remove('has-bg'); root.classList.add('no-bg'); }); }, OPP);
await shot('panel-flyout-opponent', 'game', { width: 583, height: 760 }, async (page) => { await openPanel(page); await page.click('button[aria-label="Settings"]'); });
await browser.close();
server.close();

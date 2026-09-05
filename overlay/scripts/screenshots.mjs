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
  let p = join(dist, req.url === '/' ? 'index.html' : req.url.split('?')[0]);
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
const payloads = {
  game: { tracker:{state:'live',updated_at:'x',session_id:'s'}, state: inGame, head_to_head:{wins:1,losses:2} },
  brawl: { tracker:{state:'live',updated_at:'x',session_id:'s'}, state: brawl, head_to_head:null },
  idle: { tracker:{state:'idle',updated_at:null,session_id:'s'}, state: { ...inGame, game_active:false, deck_name:null, cards:[], library_size:0, deck_size:0 }, head_to_head:null },
};

mkdirSync(new URL('../shots/', import.meta.url), { recursive: true });
const browser = await chromium.launch(process.env.PLAYWRIGHT_CHROMIUM ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM } : {});
async function shot(name, fixture, size, steps) {
  const ctx = await browser.newContext({ viewport: size, deviceScaleFactor: 2 });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => console.log('PAGE ERROR', name, e.message));
  page.on('console', (m) => { if (m.type() === 'error') console.log('CONSOLE', name, m.text()); });
  await page.route('**/api/overlay', (route) => fixture === 'offline' ? route.abort() : route.fulfill({ status: 200, contentType: 'application/json', headers: { ETag: '"1"' }, body: JSON.stringify(payloads[fixture]) }));
  await page.goto('http://127.0.0.1:5199/');
  await page.waitForTimeout(400);
  if (steps) await steps(page);
  await page.waitForTimeout(250);
  await page.screenshot({ path: `shots/${name}.png`, omitBackground: false });
  const h = await page.evaluate(() => { const p = document.querySelector('.panel'); const l = p?.querySelector('.list'); const b = p?.querySelector('.list-body'); return p ? { panel: p.offsetHeight, list: l?.clientHeight, rows: b?.offsetHeight, natural: b ? p.offsetHeight - l.clientHeight + b.offsetHeight : null } : null; });
  console.log(name, JSON.stringify(h));
  await ctx.close();
}
const board = async (page) => { await page.addStyleTag({ content: 'body{background:radial-gradient(900px 500px at 60% 40%, #4d6a8a 0%, #2d4a6a 45%, #6b3a2a 100%) !important}' }); };
const openPanel = async (page) => { await page.click('button[aria-label="Open the deck panel"]'); await page.mouse.move(400, 400); await page.waitForTimeout(100); };
await shot('rail-game', 'game', { width: 44, height: 210 });
await shot('rail-offline', 'offline', { width: 44, height: 210 });
await shot('panel-game', 'game', { width: 518, height: 560 }, openPanel);
await shot('panel-hover', 'game', { width: 518, height: 560 }, async (page) => { await board(page); await openPanel(page); await page.hover('.list-body .row:nth-of-type(4)'); });
await shot('panel-sideboard', 'game', { width: 518, height: 560 }, async (page) => { await board(page); await openPanel(page); await page.click('.land-row'); await page.click('.side-row'); await page.mouse.move(10, 10); });
await shot('panel-left-hover', 'game', { width: 518, height: 560 }, async (page) => { await board(page); await openPanel(page); await page.click('button[aria-label="Settings"]'); await page.click('[aria-label="Dock"] button:has-text("Left")'); await page.click('button[aria-label="Close settings"]'); await page.hover('.list-body .row:nth-of-type(4)'); });
await shot('panel-flyout', 'game', { width: 518, height: 560 }, async (page) => { await openPanel(page); await page.click('button[aria-label="Settings"]'); });
await shot('panel-brawl', 'brawl', { width: 518, height: 560 }, openPanel);
await shot('panel-idle', 'idle', { width: 518, height: 200 }, openPanel);
await shot('panel-offline', 'offline', { width: 518, height: 200 }, openPanel);
await shot('rail-nobg', 'game', { width: 44, height: 210 }, board);
await shot('panel-nobg', 'game', { width: 518, height: 560 }, async (page) => { await board(page); await openPanel(page); });
await shot('panel-op100', 'game', { width: 518, height: 560 }, async (page) => { await board(page); await openPanel(page); await page.click('button[aria-label="Settings"]'); await page.evaluate(() => { const el = document.querySelector('input[aria-label="Background opacity"]'); const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set; set.call(el, '100'); el.dispatchEvent(new Event('input', { bubbles: true })); }); await page.click('button[aria-label="Close settings"]'); });
await shot('panel-op20', 'game', { width: 518, height: 560 }, async (page) => { await board(page); await openPanel(page); await page.click('button[aria-label="Settings"]'); await page.evaluate(() => { const el = document.querySelector('input[aria-label="Background opacity"]'); const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set; set.call(el, '20'); el.dispatchEvent(new Event('input', { bubbles: true })); }); await page.click('button[aria-label="Close settings"]'); });
await shot('panel-nobg-flyout', 'game', { width: 518, height: 560 }, async (page) => { await board(page); await openPanel(page); await page.click('button[aria-label="Settings"]'); });
await shot('panel-scale150', 'game', { width: 777, height: 720 }, async (page) => { await board(page); await openPanel(page); await page.click('button[aria-label="Settings"]'); await page.evaluate(() => { const el = document.querySelector('input[aria-label="Scale, percent"]'); const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set; set.call(el, '150'); el.dispatchEvent(new Event('input', { bubbles: true })); }); await page.click('button[aria-label="Close settings"]'); });
await shot('panel-all-lands', 'game', { width: 518, height: 640 }, async (page) => { await openPanel(page); await page.click('button[aria-label="Settings"]'); await page.click('text=Every land'); await page.click('button[aria-label="Close settings"]'); });
await browser.close();
server.close();

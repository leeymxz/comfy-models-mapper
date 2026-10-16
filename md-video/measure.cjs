/**
 * 布局体检：对每个镜头取若干时间点调 renderAt(t)，读 getBoundingClientRect()，
 * 报告「出画」与「压字幕」两类问题。凭截图目测极易漏判，用测量一次抓干净。
 */
const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer-core');

const HERE = __dirname;
const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';

const SKIP_SRC = '^(svg|g|path|circle|rect|text|line|style|script|defs|marker|html|body)$';

(async () => {
  const tl = JSON.parse(fs.readFileSync(path.join(HERE, 'timeline.json'), 'utf-8'));
  const browser = await puppeteer.launch({
    executablePath: CHROME, headless: 'new',
    args: ['--allow-file-access-from-files', '--hide-scrollbars',
           '--force-device-scale-factor=1', '--disable-gpu'],
    defaultViewport: { width: 1920, height: 1080 },
  });
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') errors.push('console: ' + m.text()); });

  await page.evaluateOnNewDocument(`window.__TLDATA = ${JSON.stringify(tl)};`);
  await page.goto('file:///' + path.join(HERE, 'player.html').replace(/\\/g, '/'), { waitUntil: 'load' });
  await page.waitForFunction('window.__READY === true', { timeout: 15000 });
  await page.evaluate(() => document.fonts.ready);

  let problems = 0;

  for (const shot of tl.shots) {
    const dur = shot.dur;
    const times = [dur * 0.15, dur * 0.45, dur * 0.8].map(x => +(shot.start + x).toFixed(2));
    for (const t of times) {
      const res = await page.evaluate((tt, skipSrc) => {
        const skipRe = new RegExp(skipSrc, 'i');
        window.renderAt(tt);
        const out = { off: [], cap: [], hidden: [] };
        const scene = document.querySelectorAll('.scene');
        // 找到当前可见的 scene
        let cur = null;
        scene.forEach(s => { if (parseFloat(getComputedStyle(s).opacity) > 0.05) cur = s; });
        if (!cur) { out.hidden.push('(没有可见场景)'); return out; }
        const walk = el => {
          for (const c of el.children) {
            const tag = c.tagName.toLowerCase();
            if (skipRe.test(tag)) continue;
            const st = getComputedStyle(c);
            if (st.display === 'none' || parseFloat(st.opacity) < 0.05) continue;
            const r = c.getBoundingClientRect();
            if (r.width === 0 || r.height === 0) continue;
            if (r.width >= 1900 || r.height >= 900) { walk(c); continue; }
            const label = (c.id ? '#' + c.id : tag) +
              (c.className && typeof c.className === 'string' ? '.' + c.className.split(' ')[0] : '');
            if (r.left < -8 || r.top < -8 || r.right > 1928 || r.bottom > 1088) {
              out.off.push(`${label} [${Math.round(r.left)},${Math.round(r.top)} → ` +
                           `${Math.round(r.right)},${Math.round(r.bottom)}]`);
            }
            if (r.bottom > 975 && r.top < 1045) {
              out.cap.push(`${label} bottom=${Math.round(r.bottom)}`);
            }
            walk(c);
          }
        };
        walk(cur);
        return out;
      }, t, SKIP_SRC);

      for (const k of ['off', 'cap']) {
        if (res[k].length) {
          problems += res[k].length;
          console.log(`✘ ${shot.id} @${t}s  ${k === 'off' ? '出画' : '压字幕'}:`);
          res[k].slice(0, 6).forEach(s => console.log('      ' + s));
        }
      }
      if (res.hidden.length) {
        console.log(`ℹ ${shot.id} @${t}s  ${res.hidden[0]}`);
      }
    }
  }

  // 关键元素是否真的渲染出来了
  const vital = await page.evaluate(() => {
    const t0 = performance.now();
    const checks = [];
    const at = (id, t) => { window.renderAt(t); const e = document.getElementById(id); return e; };
    const seen = {};
    for (const shot of window.__TLDATA.shots) {
      window.renderAt(shot.start + shot.dur * 0.6);
      const scene = [...document.querySelectorAll('.scene')]
        .find(s => parseFloat(getComputedStyle(s).opacity) > 0.05);
      if (!scene) { checks.push([shot.id, '无可见场景']); continue; }
      const txt = scene.textContent.replace(/\s+/g, '');
      checks.push([shot.id, txt.length > 40 ? `有内容(${txt.length}字)` : `内容过少(${txt.length}字)`]);
    }
    return checks;
  });
  console.log('\n--- 各镜头内容量 ---');
  for (const [id, r] of vital) console.log(`   ${id.padEnd(12)} ${r}`);

  if (errors.length) {
    console.log('\n--- JS 错误 ---');
    errors.slice(0, 10).forEach(e => console.log('   ' + e));
    problems += errors.length;
  } else {
    console.log('\n无 JS 错误');
  }

  await browser.close();
  console.log(`\n共 ${problems} 个问题`);
  process.exit(problems ? 1 : 0);
})();

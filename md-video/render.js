/**
 * puppeteer-core 逐帧截图
 *
 * 用法:
 *   node render.js                    全片渲染 (24fps)
 *   node render.js --probe --at=2,20,60   只渲指定秒数的几帧，用于核对
 *   node render.js --range=60,90      只重渲 60~90 秒
 *   node render.js --fps=30           改帧率
 */
const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer-core');

const HERE = __dirname;
const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const FRAMES = path.join(HERE, 'frames');

function arg(name, def) {
  const hit = process.argv.find(a => a.startsWith(`--${name}=`));
  return hit ? hit.split('=')[1] : def;
}
const has = n => process.argv.includes(`--${n}`);

(async () => {
  const tl = JSON.parse(fs.readFileSync(path.join(HERE, 'timeline.json'), 'utf-8'));
  const fps = parseFloat(arg('fps', '24'));

  fs.mkdirSync(FRAMES, { recursive: true });

  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: ['--allow-file-access-from-files', '--hide-scrollbars',
           '--force-device-scale-factor=1', '--disable-gpu'],
    defaultViewport: { width: 1920, height: 1080 },
  });

  const page = await browser.newPage();
  const client = await page.target().createCDPSession();

  // 注入时间轴，避免 file:// 下 fetch 失败
  await page.evaluateOnNewDocument(`window.__TLDATA = ${JSON.stringify(tl)};`);

  const url = 'file:///' + path.join(HERE, 'player.html').replace(/\\/g, '/');
  await page.goto(url, { waitUntil: 'load' });
  await new Promise(r => setTimeout(r, 700));

  const pad = n => String(n).padStart(6, '0');

  const shoot = async (t, name) => {
    await page.evaluate(tt => window.renderAt(tt), t);
    const { data } = await client.send('Page.captureScreenshot', {
      format: 'jpeg', quality: 92, optimizeForSpeed: true,
    });
    fs.writeFileSync(path.join(FRAMES, name), Buffer.from(data, 'base64'));
  };

  if (has('probe')) {
    const ats = arg('at', '2,20,60').split(',').map(Number);
    console.log('== PROBE 模式 ==');
    for (const t of ats) {
      await shoot(t, `probe_${String(t).replace('.', '_')}.jpg`);
      console.log(`  t=${t}s -> frames/probe_${String(t).replace('.', '_')}.jpg`);
    }
    await browser.close();
    return;
  }

  let tStart = 0, tEnd = tl.total;
  if (has('range')) {
    const [a, b] = arg('range').split(',').map(Number);
    tStart = a; tEnd = b;
    console.log(`== 区间渲染 ${a}s ~ ${b}s ==`);
  }

  const iStart = Math.floor(tStart * fps);
  const iEnd = Math.ceil(tEnd * fps);
  const n = iEnd - iStart;
  const t0 = Date.now();

  console.log(`渲染 ${n} 帧  (${tStart}s ~ ${tEnd}s, ${fps}fps)`);

  for (let i = iStart; i < iEnd; i++) {
    await shoot(i / fps, `f_${pad(i)}.jpg`);
    if ((i - iStart) % 48 === 0) {
      const el = (Date.now() - t0) / 1000;
      const done = i - iStart + 1;
      const rate = done / el;
      const eta = (n - done) / rate;
      console.log(`  ${done}/${n}  已用 ${el.toFixed(0)}s  预计还需 ${eta.toFixed(0)}s`);
    }
  }

  console.log(`完成，共 ${n} 帧，耗时 ${((Date.now() - t0) / 1000).toFixed(0)}s`);
  await browser.close();
})();

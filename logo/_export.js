/**
 * 用 headless Chrome 把 SVG 导出成各尺寸 PNG。
 *   NODE_PATH=... node _export.js
 */
const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer-core');

const HERE = __dirname;
const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const OUT = path.join(HERE, 'png');

/** 图标：正方形 */
const ICON_SIZES = [1024, 512, 256, 128, 64, 32];
/** 横版：宽度 */
const LOGO_WIDTHS = [1560, 780, 390];

async function render(browser, svgName, w, h, transparent, css) {
  const svg = fs.readFileSync(path.join(HERE, svgName), 'utf-8');
  const page = await browser.newPage();
  await page.setViewport({ width: w, height: h, deviceScaleFactor: 1 });
  const html = `<!doctype html><html><head><meta charset="utf-8"><style>
    *{margin:0;padding:0}
    html,body{width:${w}px;height:${h}px;overflow:hidden}
    .box{width:${w}px;height:${h}px;${css || ''}}
    .box svg{width:100%;height:100%;display:block}
  </style></head><body><div class="box">${svg}</div></body></html>`;
  await page.setContent(html, { waitUntil: 'load' });
  await new Promise(r => setTimeout(r, 120));
  const buf = await page.screenshot({ omitBackground: !!transparent });
  await page.close();
  return buf;
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await puppeteer.launch({
    executablePath: CHROME, headless: 'new',
    args: ['--allow-file-access-from-files', '--hide-scrollbars', '--disable-gpu'],
  });

  for (const s of ICON_SIZES) {
    fs.writeFileSync(path.join(OUT, `icon-${s}.png`),
      await render(browser, 'icon.svg', s, s, true));
    console.log(`icon-${s}.png`);
  }

  /* 单色版：深 / 浅两种 */
  fs.writeFileSync(path.join(OUT, 'icon-mono-dark.png'),
    await render(browser, 'icon-mono.svg', 512, 512, true, 'color:#16202b;'));
  fs.writeFileSync(path.join(OUT, 'icon-mono-light.png'),
    await render(browser, 'icon-mono.svg', 512, 512, true, 'color:#ffffff;'));
  console.log('icon-mono-dark.png / icon-mono-light.png');

  for (const w of LOGO_WIDTHS) {
    const h = Math.round(w * 200 / 780);
    fs.writeFileSync(path.join(OUT, `logo-dark-${w}.png`),
      await render(browser, 'logo-horizontal.svg', w, h, true));
    console.log(`logo-dark-${w}.png`);
  }
  fs.writeFileSync(path.join(OUT, 'logo-light-1560.png'),
    await render(browser, 'logo-horizontal-light.svg', 1560, 400, true));
  console.log('logo-light-1560.png');

  fs.writeFileSync(path.join(OUT, 'banner-1280.png'),
    await render(browser, 'banner.svg', 1280, 640, false));
  console.log('banner-1280.png');

  await browser.close();
  console.log('\n全部导出完成 ->', OUT);
})();

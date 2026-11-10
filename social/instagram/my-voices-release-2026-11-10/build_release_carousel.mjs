import fs from "node:fs/promises";
import path from "node:path";
import sharp from "file:///C:/Program%20Files/WindowsApps/OpenAI.CodexPrimaryRuntime.v26-1104-2876-0_26.1104.2876.0_x64__3k8sg7r9htsxt/dependencies/node/node_modules/sharp/dist/index.cjs";

const outDir = "D:/Gurbaj Singh website/voiceforge/social/instagram/my-voices-release-2026-11-10";
const webDir = "D:/Gurbaj Singh website/voiceforge/app/static/social";
await fs.mkdir(outDir, { recursive: true });
await fs.mkdir(webDir, { recursive: true });

const W = 1080;
const H = 1350;
const bg = "#0B0F0C";
const panel = "#141A15";
const line = "#303A31";
const lime = "#D9FF63";
const white = "#F5F7F2";
const soft = "#AAB3AA";
const esc = (value) => String(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");

function text(lines, x, y, size, color = white, weight = 400, lineHeight = 1.15, anchor = "start") {
  return `<text x="${x}" y="${y}" text-anchor="${anchor}" font-family="Arial, Helvetica, sans-serif" font-size="${size}" font-weight="${weight}" fill="${color}">${lines.map((item, i) => `<tspan x="${x}" dy="${i ? size * lineHeight : 0}">${esc(item)}</tspan>`).join("")}</text>`;
}

function logo() {
  const bars = [[16,27,5,18],[27,18,5,36],[38,10,5,52],[49,18,5,36],[60,27,5,18]];
  return `<g transform="translate(78 70)"><rect width="80" height="80" rx="20" fill="${lime}"/>${bars.map(([x,y,w,h]) => `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="3" fill="${bg}"/>`).join("")}</g>${text(["AI VOICE HQ"],184,118,28,white,700)}`;
}

function header(kicker, index) {
  return `${logo()}${text([kicker.toUpperCase()],78,218,18,lime,700)}${text([`${index} / 04`],1002,116,18,soft,700,1,"end")}`;
}

function footer(label) {
  return `<line x1="78" y1="1244" x2="1002" y2="1244" stroke="${line}" stroke-width="2"/>${text([label],78,1292,17,soft,700)}${text(["AIVOICEGENERATORHQ.COM"],1002,1292,17,lime,700,1,"end")}`;
}

function wave(x, y, width, height) {
  const values = [.22,.5,.75,.38,.92,.62,.32,.7,.46,.84,.34,.58,.25,.76,.42,.88,.55,.3];
  const gap = width / values.length;
  return values.map((v,i) => { const h = height * v; return `<rect x="${x + i * gap}" y="${y + (height-h)/2}" width="${Math.max(6,gap*.28)}" height="${h}" rx="4" fill="${lime}" opacity="${.72+(i%3)*.1}"/>`; }).join("");
}

function shell(kicker, index, label, body) {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}"><defs><radialGradient id="glow" cx="88%" cy="10%" r="75%"><stop offset="0" stop-color="#30411E" stop-opacity=".62"/><stop offset=".5" stop-color="#121912" stop-opacity=".16"/><stop offset="1" stop-color="${bg}" stop-opacity="0"/></radialGradient></defs><rect width="${W}" height="${H}" fill="${bg}"/><rect width="${W}" height="${H}" fill="url(#glow)"/>${header(kicker,index)}${body}${footer(label)}</svg>`;
}

function featureCard(x, y, number, title, description) {
  return `<rect x="${x}" y="${y}" width="444" height="184" rx="24" fill="${panel}" stroke="${line}" stroke-width="2"/>${text([number],x+28,y+42,16,lime,700)}${text([title],x+28,y+88,25,white,700)}${text(description,x+28,y+124,18,soft,400,1.42)}`;
}

function step(y, number, title, detail) {
  return `<circle cx="118" cy="${y}" r="38" fill="${number === "04" ? lime : panel}" stroke="${number === "04" ? lime : line}" stroke-width="2"/>${text([number],118,y+7,17,number === "04" ? bg : lime,700,1,"middle")}${text([title],184,y-5,25,white,700)}${text([detail],184,y+28,18,soft,400)}`;
}

const slides = [
  {
    file: "01-save-your-voice.png",
    kicker: "New in AI Voice HQ",
    label: "PRODUCT UPDATE • 10 NOV 2026",
    body: `${text(["Save your voice once.","Use it everywhere."],78,390,72,white,700,1.08)}${text(["Your authorized voice can now live in a private library,", "ready for every project and language."],82,590,29,soft,400,1.45)}<rect x="78" y="770" width="924" height="320" rx="32" fill="${panel}" stroke="${lime}" stroke-width="2"/>${wave(136,832,808,130)}${text(["MY VOICES"],540,1014,19,lime,700,1,"middle")}${text(["PRIVATE • REUSABLE • CONSENT-ATTACHED"],540,1052,16,soft,700,1,"middle")}`,
  },
  {
    file: "02-changelog.png",
    kicker: "Changelog 0.3.0",
    label: "WHAT SHIPPED",
    body: `${text(["Your own voice,", "production ready."],78,374,72,white,700,1.07)}${text(["A complete private voice workflow, not another upload box."],82,550,28,soft,400)}${featureCard(78,665,"01","Save once",["Record or upload a", "clean reference."])}${featureCard(558,665,"02","Label it",["Name, accent, language", "and use-case tags."])}${featureCard(78,875,"03","Set defaults",["Choose the delivery you", "use most often."])}${featureCard(558,875,"04","Reuse privately",["Cast it in projects and", "multilingual jobs."])}`,
  },
  {
    file: "03-you-stay-in-control.png",
    kicker: "Private by design",
    label: "YOUR VOICE • YOUR CONTROL",
    body: `${text(["Stored only when", "you say so."],78,374,74,white,700,1.06)}${text(["One-time references are still deleted after generation.", "Saved voices remain private until you delete them."],82,560,28,soft,400,1.43)}<rect x="78" y="710" width="924" height="360" rx="30" fill="${panel}" stroke="${line}" stroke-width="2"/>${["Preview privately","Rename anytime","Replace the sample","Delete permanently"].map((v,i) => `<circle cx="132" cy="${777+i*72}" r="15" fill="${lime}"/>${text(["✓"],132,784+i*72,16,bg,700,1,"middle")}${text([v],172,786+i*72,24,white,700)}`).join("")}${text(["Consent stays attached to every saved reference."],540,1028,17,lime,700,1,"middle")}`,
  },
  {
    file: "04-how-to-save.png",
    kicker: "How to use it",
    label: "AVAILABLE NOW IN STUDIO",
    body: `${text(["Four steps. Then it is", "ready whenever you are."],78,365,68,white,700,1.08)}${step(635,"01","Create a new voice","Upload or record 6–30 seconds.")}${step(755,"02","Confirm permission","Only authorized speakers are allowed.")}${step(875,"03","Name and describe it","Add language, accent and delivery.")}${step(995,"04","Save to My Voices","Choose it from Studio anytime.")}<rect x="78" y="1110" width="924" height="76" rx="18" fill="${lime}"/>${text(["OPEN STUDIO →"],540,1159,22,bg,800,1,"middle")}`,
  },
];

for (const [index, slide] of slides.entries()) {
  const svg = shell(slide.kicker, String(index + 1).padStart(2,"0"), slide.label, slide.body);
  await fs.writeFile(path.join(outDir, slide.file.replace(".png", ".svg")), svg);
  await sharp(Buffer.from(svg)).png({ quality: 96 }).toFile(path.join(outDir, slide.file));
}

await fs.copyFile(path.join(outDir, slides[0].file), path.join(webDir, "my-voices-release.png"));
console.log(`Built ${slides.length} release slides and website share image.`);

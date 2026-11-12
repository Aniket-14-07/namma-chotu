"use strict";
/* Namma Chotu client: mic -> 16 kHz PCM over WebSocket, Gnani Timbre PCM back to the speaker.
   No framework, no build step: loads fast on a low-end Android phone. */

const $ = (s) => document.querySelector(s);
const inr = (paise) => {
  const r = paise / 100;
  return new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", minimumFractionDigits: 0,
    maximumFractionDigits: paise % 100 ? 2 : 0 }).format(r);
};
const dayLabel = (iso) => {
  const d = new Date(iso + "T00:00:00+05:30");
  const t = new Date(new Date().toLocaleString("en-US", { timeZone: "Asia/Kolkata" }));
  t.setHours(0, 0, 0, 0);
  const diff = Math.round((t - d) / 86400000);
  return ({ 0: tr("today"), 1: tr("yesterday"), 2: tr("day_before") })[diff] || d.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
};

const S = {
  ws: null, live: false, started: false, mode: "ptt",
  ctx: null, node: null, stream: null, capturing: false, muted: false,
  ttsRate: 16000, nextTime: 0, sources: [], speaking: false,
  releaseAt: 0, waitingFirstAudio: false, retry: 0,
};


/* ---------------------------------------------------------------- language */
const I18N = {
  hi: { tag: "आपकी दुकान, आपकी आवाज़", first_entry: "आज की पहली एंट्री बोलिए", example: "“रमेश का 340 उधार”",
    rem_title: "विनम्र याद-संदेश तैयार", rem_send: "WhatsApp पर भेजें", close: "बंद करें", d_credit: "आज उधार गया",
    d_paid: "आज जमा हुआ", d_out: "बाज़ार में बाकी", d_top: "सबसे ज़्यादा बाकी", d_today: "आज की एंट्री", search: "ग्राहक खोजें",
    type: "लिखें", hold: "दबाकर बोलिए", send: "भेजें", tab_bolo: "बोलो", tab_hisaab: "हिसाब", tab_khata: "खाता",
    listening: "सुन रहा हूँ…", listening_ptt: "सुन रहा हूँ… छोड़ते ही लिख दूँगा", thinking: "लिख रहा हूँ…",
    speaking: "बोल रहा हूँ… (बीच में बोल सकते हैं)", no_speech: "कुछ सुनाई नहीं दिया। दबाकर बोलिए",
    muted: "माइक बंद है, टैप करके खोलें", hf: "“छोटू, …” बोलकर शुरू करें", mode_ptt: "दबाकर बोलें", mode_hf: "हैंड्स-फ़्री: “छोटू, …”",
    yes: "हाँ", no: "नहीं", skip: "रहने दो", credit: "उधार", payment: "जमा", removed: "हटा दी", due: "कुल बाकी",
    advance: "एडवांस", nothing_due: "कुछ बाकी नहीं", today: "आज", yesterday: "कल", day_before: "परसों",
    customers_n: "ग्राहक", none_owe: "किसी पर उधार नहीं", corrected: "सुधारी गई", voided: "हटाई गई", no_today: "आज अभी कोई एंट्री नहीं।",
    last_entry: "आख़िरी एंट्री", no_entry: "कोई एंट्री नहीं", adv_short: "एडवांस",
    optin: "ग्राहक ने याद-संदेश के लिए हाँ कहा है", src_seed: "पुरानी एंट्री", src_voice: "आवाज़ से", src_fix: "सुधार", src_ui: "हाथ से",
    mic_err: "माइक नहीं मिला। फ़ोन पर HTTPS लिंक खोलें और माइक की अनुमति दें।", ignored: "छोटू के लिए नहीं था, छोड़ दिया" },
  kn: { tag: "ನಿಮ್ಮ ಅಂಗಡಿ, ನಿಮ್ಮ ಧ್ವನಿ", first_entry: "ಇವತ್ತಿನ ಮೊದಲ ಎಂಟ್ರಿ ಹೇಳಿ", example: "“ರಮೇಶ್ 340 ಉದ್ರಿ”",
    rem_title: "ವಿನಯದ ನೆನಪಿನ ಸಂದೇಶ ಸಿದ್ಧ", rem_send: "WhatsApp ನಲ್ಲಿ ಕಳಿಸಿ", close: "ಮುಚ್ಚಿ", d_credit: "ಇವತ್ತು ಉದ್ರಿ",
    d_paid: "ಇವತ್ತು ಜಮಾ", d_out: "ಮಾರ್ಕೆಟ್‌ನಲ್ಲಿ ಬಾಕಿ", d_top: "ಅತಿ ಹೆಚ್ಚು ಬಾಕಿ", d_today: "ಇವತ್ತಿನ ಎಂಟ್ರಿಗಳು", search: "ಗ್ರಾಹಕರನ್ನು ಹುಡುಕಿ",
    type: "ಟೈಪ್", hold: "ಒತ್ತಿ ಹಿಡಿದು ಮಾತಾಡಿ", send: "ಕಳಿಸಿ", tab_bolo: "ಮಾತಾಡಿ", tab_hisaab: "ಲೆಕ್ಕ", tab_khata: "ಖಾತೆ",
    listening: "ಕೇಳುತ್ತಿದ್ದೇನೆ…", listening_ptt: "ಕೇಳುತ್ತಿದ್ದೇನೆ… ಬಿಟ್ಟ ತಕ್ಷಣ ಬರೆಯುತ್ತೇನೆ", thinking: "ಬರೆಯುತ್ತಿದ್ದೇನೆ…",
    speaking: "ಮಾತಾಡುತ್ತಿದ್ದೇನೆ… (ಮಧ್ಯದಲ್ಲಿ ಮಾತಾಡಬಹುದು)", no_speech: "ಏನೂ ಕೇಳಿಸಲಿಲ್ಲ. ಒತ್ತಿ ಹಿಡಿದು ಮಾತಾಡಿ",
    muted: "ಮೈಕ್ ಆಫ್ ಆಗಿದೆ, ಟ್ಯಾಪ್ ಮಾಡಿ", hf: "“ಛೋಟು, …” ಎಂದು ಶುರು ಮಾಡಿ", mode_ptt: "ಒತ್ತಿ ಮಾತಾಡಿ", mode_hf: "ಹ್ಯಾಂಡ್ಸ್-ಫ್ರೀ: “ಛೋಟು, …”",
    yes: "ಹೌದು", no: "ಇಲ್ಲ", skip: "ಬೇಡ", credit: "ಉದ್ರಿ", payment: "ಜಮಾ", removed: "ತೆಗೆದಿದೆ", due: "ಒಟ್ಟು ಬಾಕಿ",
    advance: "ಮುಂಗಡ", nothing_due: "ಏನೂ ಬಾಕಿ ಇಲ್ಲ", today: "ಇವತ್ತು", yesterday: "ನಿನ್ನೆ", day_before: "ಮೊನ್ನೆ",
    customers_n: "ಗ್ರಾಹಕರು", none_owe: "ಯಾರ ಮೇಲೂ ಉದ್ರಿ ಇಲ್ಲ", corrected: "ಸರಿಪಡಿಸಲಾಗಿದೆ", voided: "ತೆಗೆಯಲಾಗಿದೆ", no_today: "ಇವತ್ತು ಇನ್ನೂ ಎಂಟ್ರಿ ಇಲ್ಲ.",
    last_entry: "ಕೊನೆಯ ಎಂಟ್ರಿ", no_entry: "ಎಂಟ್ರಿ ಇಲ್ಲ", adv_short: "ಮುಂಗಡ",
    optin: "ಗ್ರಾಹಕರು ನೆನಪಿನ ಸಂದೇಶಕ್ಕೆ ಒಪ್ಪಿದ್ದಾರೆ", src_seed: "ಹಳೆಯ ಎಂಟ್ರಿ", src_voice: "ಧ್ವನಿಯಿಂದ", src_fix: "ತಿದ್ದುಪಡಿ", src_ui: "ಕೈಯಿಂದ",
    mic_err: "ಮೈಕ್ ಸಿಗಲಿಲ್ಲ. ಫೋನ್‌ನಲ್ಲಿ HTTPS ಲಿಂಕ್ ತೆರೆಯಿರಿ ಮತ್ತು ಮೈಕ್ ಅನುಮತಿ ಕೊಡಿ.", ignored: "ಛೋಟುಗೆ ಅಲ್ಲ, ಬಿಟ್ಟೆ" },
  en: { tag: "Your kirana, your voice", first_entry: "Say today's first entry", example: "“Ramesh, 340 credit”",
    rem_title: "Polite reminder ready", rem_send: "Send on WhatsApp", close: "Close", d_credit: "Credit given today",
    d_paid: "Received today", d_out: "Pending in the market", d_top: "Highest dues", d_today: "Today's entries", search: "Find a customer",
    type: "Type", hold: "Hold and speak", send: "Send", tab_bolo: "Speak", tab_hisaab: "Summary", tab_khata: "Khata",
    listening: "Listening…", listening_ptt: "Listening… release to record", thinking: "Writing…",
    speaking: "Speaking… (you can interrupt)", no_speech: "Didn't hear anything. Hold and speak",
    muted: "Mic is off, tap to turn on", hf: "Start with “Chotu, …”", mode_ptt: "Hold to talk", mode_hf: "Hands-free: “Chotu, …”",
    yes: "Yes", no: "No", skip: "Skip", credit: "credit", payment: "paid", removed: "removed", due: "Total due",
    advance: "advance", nothing_due: "Nothing due", today: "today", yesterday: "yesterday", day_before: "day before",
    customers_n: "customers", none_owe: "Nobody owes anything", corrected: "corrected", voided: "removed", no_today: "No entries yet today.",
    last_entry: "Last entry", no_entry: "No entries", adv_short: "adv",
    optin: "Customer agreed to reminders", src_seed: "earlier entry", src_voice: "by voice", src_fix: "correction", src_ui: "by hand",
    mic_err: "No microphone. Open the HTTPS link on the phone and allow the mic.", ignored: "not for Chotu, ignored" },
};
const uiLang = () => (S.lang && S.lang !== "auto" ? S.lang : S.replyLang || "hi");
const tr = (k) => (I18N[uiLang()] || I18N.en)[k] ?? I18N.en[k] ?? k;
function applyI18n() {
  document.documentElement.lang = uiLang();
  document.querySelectorAll("[data-i18n]").forEach((el) => (el.textContent = tr(el.dataset.i18n)));
  document.querySelectorAll("[data-i18n-ph]").forEach((el) => (el.placeholder = tr(el.dataset.i18nPh)));
  $("#modeBtn").textContent = S.mode === "handsfree" ? tr("mode_hf") : tr("mode_ptt");
  if (S.started) micState(restingHint());
}
function setLang(lang, fromUser) {
  S.lang = lang;
  $("#langSel").value = lang;
  try { localStorage.setItem("nc_lang", lang); } catch (_) {}
  applyI18n();
  if (fromUser && S.started) send({ type: "lang", lang });
  if (S.started) refreshAll();
}

/* ---------------------------------------------------------------- websocket */
function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.binaryType = "arraybuffer";
  S.ws = ws;
  ws.onopen = () => { S.retry = 0; if (S.started) send({ type: "start", mode: S.mode, lang: S.lang, resume: true }); };
  ws.onclose = () => {
    setBadge("offline", "");
    setTimeout(connect, Math.min(4000, 500 * 2 ** S.retry++));
  };
  ws.onmessage = (ev) => (typeof ev.data === "string" ? onJson(JSON.parse(ev.data)) : playPcm(ev.data));
}
const send = (o) => S.ws && S.ws.readyState === 1 && S.ws.send(JSON.stringify(o));

function onJson(m) {
  switch (m.type) {
    case "ready":
      S.live = m.live;
      setBadge(m.live ? "Live" : "Mock", m.live ? "live" : "mock");
      if (!m.live) { $("#typeForm").hidden = false; $("#mic").disabled = true; micState("Mock mode: no Gnani key, type below"); }
      break;
    case "transcript":
      if (m.text) addFeed(m.text, m.typed ? "you typed" : "you");
      break;
    case "stt_event":
      if (m.event === "speech_start" && S.mode === "handsfree") setMic("listening", tr("listening"));
      if (m.event === "processing") setMic("thinking", tr("thinking"));
      break;
    case "no_speech":
      setMic("", tr("no_speech"));
      break;
    case "reply":
      onReply(m);
      break;
    case "tts_start":
      S.ttsRate = m.sample_rate || 16000;
      break;
    case "tts_end":
      break;
    case "tts_cancel":
      stopPlayback();
      break;
    case "metrics":
      if (m.end_to_first_audio_ms != null) showLatency(m.end_to_first_audio_ms, "server");
      break;
    case "dashboard_dirty":
      refreshSoon();
      break;
    case "stt_closed":
      break;
    case "ignored":
      addFeed(`"${m.text}" (${tr("ignored")})`, "sys");
      break;
    case "error":
      addFeed(`${m.where || ""} error: ${m.message}`, "err");
      setMic("", restingHint());
      break;
  }
}

/* -------------------------------------------------------------------- audio */
async function startAudio() {
  S.ctx = new (window.AudioContext || window.webkitAudioContext)();
  await S.ctx.resume();
  if (!S.live) return;
  S.stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  });
  await S.ctx.audioWorklet.addModule("/pcm-worklet.js");
  const src = S.ctx.createMediaStreamSource(S.stream);
  S.node = new AudioWorkletNode(S.ctx, "pcm-downsampler");
  const sink = S.ctx.createGain();
  sink.gain.value = 0;
  src.connect(S.node).connect(sink).connect(S.ctx.destination);
  S.node.port.onmessage = (e) => {
    if (S.capturing && !S.muted && S.ws && S.ws.readyState === 1) S.ws.send(e.data);
  };
}

function playPcm(buf) {
  if (!S.ctx) return;
  const i16 = new Int16Array(buf);
  if (!i16.length) return;
  const f32 = new Float32Array(i16.length);
  for (let i = 0; i < i16.length; i++) f32[i] = i16[i] / 32768;
  const ab = S.ctx.createBuffer(1, f32.length, S.ttsRate);
  ab.copyToChannel(f32, 0);
  const src = S.ctx.createBufferSource();
  src.buffer = ab;
  src.connect(S.ctx.destination);
  const at = Math.max(S.ctx.currentTime + 0.03, S.nextTime);
  src.start(at);
  S.nextTime = at + ab.duration;
  S.sources.push(src);
  src.onended = () => {
    S.sources = S.sources.filter((x) => x !== src);
    if (!S.sources.length) { S.speaking = false; if (!S.capturing || S.mode === "handsfree") setMic("", restingHint()); }
  };
  if (S.waitingFirstAudio) {
    S.waitingFirstAudio = false;
    showLatency(Math.round(performance.now() - S.releaseAt + (at - S.ctx.currentTime) * 1000), "phone");
  }
  if (!S.speaking) { S.speaking = true; if (!S.capturing || S.mode === "handsfree") setMic("speaking", tr("speaking")); }
}

function stopPlayback() {
  for (const s of S.sources) { try { s.stop(); } catch (_) {} }
  S.sources = [];
  S.nextTime = 0;
  S.speaking = false;
}

/* ------------------------------------------------------------ talk controls */
function pressStart(e) {
  if (!S.live || S.mode !== "ptt") return;
  e && e.preventDefault();
  if (S.capturing) return;
  stopPlayback();                       // barge-in: silence the agent instantly
  S.capturing = true;
  send({ type: "ptt_down" });
  setMic("listening", tr("listening_ptt"));
  if (navigator.vibrate) navigator.vibrate(15);
}
function pressEnd(e) {
  if (!S.live || S.mode !== "ptt" || !S.capturing) return;
  e && e.preventDefault();
  S.capturing = false;
  S.releaseAt = performance.now();
  S.waitingFirstAudio = true;
  send({ type: "ptt_up" });
  setMic("thinking", tr("thinking"));
}

function setMode(mode) {
  S.mode = mode;
  const hf = mode === "handsfree";
  $("#modeBtn").setAttribute("aria-pressed", String(hf));
  $("#modeBtn").textContent = hf ? tr("mode_hf") : tr("mode_ptt");
  S.capturing = hf;
  S.muted = false;
  send({ type: "mode", mode });
  setMic(hf ? "listening" : "", restingHint());
}
const restingHint = () => (S.mode === "handsfree" ? (S.muted ? tr("muted") : tr("hf")) : tr("hold"));

function setMic(state, text) {
  const mic = $("#mic");
  mic.classList.remove("listening", "thinking", "speaking");
  if (state) mic.classList.add(state);
  if (text) micState(text);
}
const micState = (t) => ($("#micState").textContent = t);

/* ------------------------------------------------------------------ replies */
function onReply(m) {
  if (m.lang && m.lang !== S.replyLang) { S.replyLang = m.lang; if (S.lang === "auto") applyI18n(); }
  addFeed(m.display, "bot");
  const q = $("#question");
  if (m.pending) {
    q.hidden = false;
    q.querySelector(".q-text").textContent = m.display;
    const box = q.querySelector(".q-options");
    box.innerHTML = "";
    const opts = m.pending.options.length ? m.pending.options.map((o) => [o.name, o.name])
      : [[tr("yes"), "haan"], [tr("no"), "nahi"]];
    if (m.pending.options.length) opts.push([tr("skip"), "nahi rehne do"]);
    for (const [label, said] of opts) {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = label;
      b.onclick = () => submitText(said);
      box.appendChild(b);
    }
  } else {
    q.hidden = true;
  }
  const txns = m.events.filter((e) => e.type === "txn");
  const fresh = txns.filter((e) => e.action !== "voided");
  if (fresh.length) showEntry(fresh[fresh.length - 1].txn, txns.find((e) => e.action === "voided"));
  else if (txns.length) showEntry(txns[0].txn, null, true);
  const rem = m.events.find((e) => e.type === "reminder");
  if (rem) showReminder(rem);
  if (!S.live) setMic("", restingHint());
}

async function showEntry(t, voided, removed) {
  const box = $("#ledgerLine");
  box.classList.remove("empty", "payment", "fresh");
  void box.offsetWidth;
  box.classList.add("fresh");
  if (t.kind === "PAYMENT") box.classList.add("payment");
  box.querySelector(".who").textContent = t.customer;
  const amt = box.querySelector(".amt");
  amt.textContent = `${inr(t.amount_paise)} ${t.kind === "PAYMENT" ? tr("payment") : tr("credit")}`;
  if (removed) amt.innerHTML = `<span class="was">${inr(t.amount_paise)}</span> ${esc(tr("removed"))}`;
  else if (voided && voided.txn.amount_paise !== t.amount_paise) {
    const w = document.createElement("span");
    w.className = "was";
    w.textContent = inr(voided.txn.amount_paise);
    amt.appendChild(w);
  }
  box.querySelector(".meta").textContent = dayLabel(t.txn_date);
  try {
    const c = await (await fetch(`/api/customers/${t.customer_id}`)).json();
    const bal = c.balance > 0 ? `${tr("due")} ${inr(c.balance)}` : c.balance < 0 ? `${inr(-c.balance)} ${tr("advance")}` : tr("nothing_due");
    box.querySelector(".meta").textContent = `${dayLabel(t.txn_date)}, ${bal}`;
  } catch (_) {}
}

function showReminder(r) {
  const card = $("#reminderCard");
  card.hidden = false;
  card.querySelector(".r-text").textContent = r.message;
  const phone = (r.phone || "").replace(/\D/g, "");
  card.querySelector(".r-send").href = `https://wa.me/91${phone.slice(-10)}?text=${encodeURIComponent(r.message)}`;
}

function addFeed(text, cls) {
  const li = document.createElement("li");
  li.className = cls;
  li.textContent = text;
  const feed = $("#feed");
  feed.prepend(li);
  while (feed.children.length > 30) feed.lastChild.remove();
}

function showLatency(ms, where) {
  const el = $("#latency");
  el.hidden = false;
  el.textContent = `${(ms / 1000).toFixed(2)} s`;
  el.title = `End of speech to first reply audio (${where})`;
}
function setBadge(text, cls) {
  const b = $("#modeBadge");
  b.textContent = text;
  b.className = `badge ${cls}`;
}

function submitText(text) {
  text = text.trim();
  if (!text) return;
  stopPlayback();
  S.releaseAt = performance.now();
  S.waitingFirstAudio = true;
  send({ type: "text", text });
}

/* ------------------------------------------------------- dashboard & khata */
let refreshTimer = null;
function refreshSoon() { clearTimeout(refreshTimer); refreshTimer = setTimeout(refreshAll, 250); }
async function refreshAll() { await Promise.all([refreshDash(), refreshCustomers()]); }

async function refreshDash() {
  const d = await (await fetch("/api/dashboard")).json();
  $("#dCredit").textContent = inr(d.today_credit);
  $("#dPaid").textContent = inr(d.today_payments);
  $("#dOut").textContent = inr(d.total_outstanding);
  $("#dCust").textContent = `${d.customers} ${tr("customers_n")}`;
  $("#dTop").innerHTML = d.top_debtors.map((c) =>
    `<li><span class="n">${esc(c.name)}</span><span class="m c">${inr(c.balance)}</span></li>`).join("") ||
    `<li class="empty-row">${tr("none_owe")}</li>`;
  const today = d.date;
  const rows = d.recent.filter((t) => t.created_at.slice(0, 10) === today && t.source !== "seed");
  $("#dRecent").innerHTML = rows.map((t) =>
    `<li class="${t.status === "voided" ? "void" : ""}"><span class="n">${esc(t.customer)}<span class="s">${dayLabel(t.txn_date)}${t.replaces ? ", " + tr("corrected") : ""}${t.status === "voided" ? ", " + tr("voided") : ""}</span></span>
     <span class="m ${t.kind === "PAYMENT" ? "p" : "c"}">${t.kind === "PAYMENT" ? "−" : "+"}${inr(t.amount_paise)}</span></li>`).join("") ||
    `<li class="empty-row">${tr("no_today")}</li>`;
}

let customers = [];
async function refreshCustomers() {
  customers = await (await fetch("/api/customers")).json();
  renderCustomers();
}
function renderCustomers() {
  const q = $("#search").value.trim().toLowerCase();
  const list = customers.filter((c) => !q || c.name.toLowerCase().includes(q) || (c.name_hi || "").includes(q));
  $("#custList").innerHTML = list.map((c) =>
    `<li><button class="rowbtn" data-id="${c.id}" type="button"><span class="n">${esc(c.name)}<span class="s">${c.last_txn_date ? tr("last_entry") + " " + dayLabel(c.last_txn_date) : tr("no_entry")}</span></span>
     <span class="m ${c.balance > 0 ? "c" : "p"}">${c.balance < 0 ? inr(-c.balance) + " " + tr("adv_short") : inr(c.balance)}</span></button></li>`).join("");
}
async function openCustomer(id) {
  const c = await (await fetch(`/api/customers/${id}`)).json();
  const box = $("#custDetail");
  box.hidden = false;
  box.innerHTML = `<h3>${esc(c.name)} ${c.name_hi ? `<span class="s">${esc(c.name_hi)}</span>` : ""}</h3>
    <p class="bal" style="color:${c.balance > 0 ? "var(--udhaar)" : "var(--jama)"}">${c.balance < 0 ? inr(-c.balance) + " " + tr("advance") : inr(c.balance)}</p>
    <label><input type="checkbox" id="optin" ${c.reminder_opt_in ? "checked" : ""}> ${esc(tr("optin"))}</label>
    <ol class="rows txns">${c.transactions.map((t) =>
      `<li class="${t.status === "voided" ? "void" : ""}"><span class="n">${dayLabel(t.txn_date)}<span class="s">${({ seed: tr("src_seed"), voice: tr("src_voice"), "voice-correction": tr("src_fix"), ui: tr("src_ui") })[t.source] || t.source}${t.status === "voided" ? ", " + tr("voided") : ""}</span></span>
       <span class="m ${t.kind === "PAYMENT" ? "p" : "c"}">${t.kind === "PAYMENT" ? "−" : "+"}${inr(t.amount_paise)}</span></li>`).join("")}</ol>`;
  box.querySelector("#optin").onchange = async (e) => {
    await fetch(`/api/customers/${id}/opt-in`, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ opt_in: e.target.checked }) });
    refreshCustomers();
  };
  box.scrollIntoView({ behavior: "smooth", block: "start" });
}
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

/* -------------------------------------------------------------------- wire */
function wire() {
  const mic = $("#mic");
  mic.addEventListener("pointerdown", (e) => {
    if (S.mode === "handsfree") {
      S.muted = !S.muted;
      if (!S.muted) stopPlayback();
      setMic(S.muted ? "" : "listening", restingHint());
      return;
    }
    mic.setPointerCapture(e.pointerId);
    pressStart(e);
  });
  mic.addEventListener("pointerup", pressEnd);
  mic.addEventListener("pointercancel", pressEnd);
  mic.addEventListener("contextmenu", (e) => e.preventDefault());
  document.addEventListener("keydown", (e) => {
    if (e.code === "Space" && !e.repeat && document.activeElement.tagName !== "INPUT") pressStart(e);
  });
  document.addEventListener("keyup", (e) => {
    if (e.code === "Space" && document.activeElement.tagName !== "INPUT") pressEnd(e);
  });
  $("#modeBtn").onclick = () => setMode(S.mode === "ptt" ? "handsfree" : "ptt");
  $("#typeBtn").onclick = () => { const f = $("#typeForm"); f.hidden = !f.hidden; if (!f.hidden) $("#typeInput").focus(); };
  $("#typeForm").onsubmit = (e) => { e.preventDefault(); submitText($("#typeInput").value); $("#typeInput").value = ""; };
  $("#reminderCard .r-close").onclick = () => ($("#reminderCard").hidden = true);
  $("#search").oninput = renderCustomers;
  $("#custList").onclick = (e) => { const b = e.target.closest("[data-id]"); if (b) openCustomer(b.dataset.id); };
  for (const b of document.querySelectorAll(".tabs button")) {
    b.onclick = () => {
      document.querySelectorAll(".tabs button").forEach((x) => x.classList.toggle("on", x === b));
      document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.id === `tab-${b.dataset.tab}`));
      if (b.dataset.tab !== "bolo") refreshAll();
    };
  }
  for (const b of document.querySelectorAll(".langs button")) b.onclick = () => begin(b.dataset.lang);
  async function begin(lang) {
    setLang(lang, false);
    document.querySelectorAll(".langs button").forEach((x) => (x.disabled = true));
    try {
      await startAudio();
    } catch (err) {
      addFeed(`${tr("mic_err")} (${err.name})`, "err");
      $("#typeForm").hidden = false;
    }
    $("#startSheet").hidden = true;
    S.started = true;
    send({ type: "start", mode: S.mode, lang });
    refreshAll();
  }
}

wire();
$("#langSel").onchange = (e) => setLang(e.target.value, true);
try { const saved = localStorage.getItem("nc_lang"); if (saved) setLang(saved, false); } catch (_) {}
applyI18n();
connect();
refreshAll();

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
  return ({ 0: "aaj", 1: "kal", 2: "parso" })[diff] || d.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
};

const S = {
  ws: null, live: false, started: false, mode: "ptt",
  ctx: null, node: null, stream: null, capturing: false, muted: false,
  ttsRate: 16000, nextTime: 0, sources: [], speaking: false,
  releaseAt: 0, waitingFirstAudio: false, retry: 0,
};

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
      setBadge(m.live ? "Gnani live" : "Mock: typed only", m.live ? "live" : "mock");
      if (!m.live) { $("#typeForm").hidden = false; $("#mic").disabled = true; micState("Mock mode: no Gnani key, type below"); }
      break;
    case "transcript":
      if (m.text) addFeed(m.text, m.typed ? "you typed" : "you");
      break;
    case "stt_event":
      if (m.event === "speech_start" && S.mode === "handsfree") setMic("listening", "Sun raha hoon…");
      if (m.event === "processing") setMic("thinking", "Likh raha hoon…");
      break;
    case "no_speech":
      setMic("", "Kuch sunai nahi diya. Daba ke bolo");
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
      addFeed(`"${m.text}" (not for Chotu, ignored)`, "sys");
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
  if (!S.speaking) { S.speaking = true; if (!S.capturing || S.mode === "handsfree") setMic("speaking", "Bol raha hoon… (beech mein bol sakte ho)"); }
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
  setMic("listening", "Sun raha hoon… chhodo to likh dunga");
  if (navigator.vibrate) navigator.vibrate(15);
}
function pressEnd(e) {
  if (!S.live || S.mode !== "ptt" || !S.capturing) return;
  e && e.preventDefault();
  S.capturing = false;
  S.releaseAt = performance.now();
  S.waitingFirstAudio = true;
  send({ type: "ptt_up" });
  setMic("thinking", "Likh raha hoon…");
}

function setMode(mode) {
  S.mode = mode;
  const hf = mode === "handsfree";
  $("#modeBtn").setAttribute("aria-pressed", String(hf));
  $("#modeBtn").textContent = hf ? "Hands-free: say \"Chotu, …\"" : "Hold to talk";
  S.capturing = hf;
  S.muted = false;
  send({ type: "mode", mode });
  setMic(hf ? "listening" : "", restingHint());
}
const restingHint = () => (S.mode === "handsfree" ? (S.muted ? "Mic band hai, tap karke kholo" : "Bolte rahiye, main sun raha hoon") : "Daba ke bolo");

function setMic(state, text) {
  const mic = $("#mic");
  mic.classList.remove("listening", "thinking", "speaking");
  if (state) mic.classList.add(state);
  if (text) micState(text);
}
const micState = (t) => ($("#micState").textContent = t);

/* ------------------------------------------------------------------ replies */
function onReply(m) {
  addFeed(m.display, "bot");
  const q = $("#question");
  if (m.pending) {
    q.hidden = false;
    q.querySelector(".q-text").textContent = m.display;
    const box = q.querySelector(".q-options");
    box.innerHTML = "";
    const opts = m.pending.options.length ? m.pending.options.map((o) => o.name) : ["Haan", "Nahi"];
    if (m.pending.options.length) opts.push("Rehne do");
    for (const label of opts) {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = label;
      b.onclick = () => submitText(label === "Rehne do" ? "nahi rehne do" : label);
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
  amt.textContent = `${inr(t.amount_paise)} ${t.kind === "PAYMENT" ? "jama" : "udhaar"}`;
  if (removed) amt.innerHTML = `<span class="was">${inr(t.amount_paise)}</span> hata diya`;
  else if (voided && voided.txn.amount_paise !== t.amount_paise) {
    const w = document.createElement("span");
    w.className = "was";
    w.textContent = inr(voided.txn.amount_paise);
    amt.appendChild(w);
  }
  box.querySelector(".meta").textContent = dayLabel(t.txn_date);
  try {
    const c = await (await fetch(`/api/customers/${t.customer_id}`)).json();
    const bal = c.balance > 0 ? `Kul baaki ${inr(c.balance)}` : c.balance < 0 ? `${inr(-c.balance)} advance` : "Kuch baaki nahi";
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
  $("#dCust").textContent = `${d.customers} grahak`;
  $("#dTop").innerHTML = d.top_debtors.map((c) =>
    `<li><span class="n">${esc(c.name)}</span><span class="m c">${inr(c.balance)}</span></li>`).join("") ||
    `<li class="empty-row">Kisi par udhaar nahi</li>`;
  const today = d.date;
  const rows = d.recent.filter((t) => t.created_at.slice(0, 10) === today && t.source !== "seed");
  $("#dRecent").innerHTML = rows.map((t) =>
    `<li class="${t.status === "voided" ? "void" : ""}"><span class="n">${esc(t.customer)}<span class="s">${dayLabel(t.txn_date)}${t.replaces ? ", sudhara gaya" : ""}${t.status === "voided" ? ", hataya" : ""}</span></span>
     <span class="m ${t.kind === "PAYMENT" ? "p" : "c"}">${t.kind === "PAYMENT" ? "−" : "+"}${inr(t.amount_paise)}</span></li>`).join("") ||
    `<li class="empty-row">Aaj abhi koi entry nahi.</li>`;
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
    `<li><button class="rowbtn" data-id="${c.id}" type="button"><span class="n">${esc(c.name)}<span class="s">${c.last_txn_date ? "Aakhri entry " + dayLabel(c.last_txn_date) : "Koi entry nahi"}</span></span>
     <span class="m ${c.balance > 0 ? "c" : "p"}">${c.balance < 0 ? inr(-c.balance) + " adv" : inr(c.balance)}</span></button></li>`).join("");
}
async function openCustomer(id) {
  const c = await (await fetch(`/api/customers/${id}`)).json();
  const box = $("#custDetail");
  box.hidden = false;
  box.innerHTML = `<h3>${esc(c.name)} ${c.name_hi ? `<span class="s">${esc(c.name_hi)}</span>` : ""}</h3>
    <p class="bal" style="color:${c.balance > 0 ? "var(--udhaar)" : "var(--jama)"}">${c.balance < 0 ? inr(-c.balance) + " advance" : inr(c.balance)}</p>
    <label><input type="checkbox" id="optin" ${c.reminder_opt_in ? "checked" : ""}> Grahak ne reminder ke liye haan kaha hai</label>
    <ol class="rows txns">${c.transactions.map((t) =>
      `<li class="${t.status === "voided" ? "void" : ""}"><span class="n">${dayLabel(t.txn_date)}<span class="s">${({ seed: "purani entry", voice: "aawaz se", "voice-correction": "sudhaar", ui: "haath se" })[t.source] || t.source}${t.status === "voided" ? ", " + (t.void_reason || "hataya") : ""}</span></span>
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
    S.lang = lang;
    document.querySelectorAll(".langs button").forEach((x) => (x.disabled = true));
    try {
      await startAudio();
    } catch (err) {
      addFeed(`Mic nahi mila (${err.name}). Phone par HTTPS link kholiye aur mic ki permission dijiye.`, "err");
      $("#typeForm").hidden = false;
    }
    $("#startSheet").hidden = true;
    S.started = true;
    send({ type: "start", mode: S.mode, lang });
    refreshAll();
  }
}

wire();
connect();
refreshAll();

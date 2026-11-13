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
  hi: { convo: "बात करो", get_lbl: "लेना है", give_lbl: "देना है", settled: "हिसाब बराबर", d_owe: "आपको देना है", d_yday: "कल की एंट्री", d_alarms: "याद-दिहानी", d_closing: "रोज़ हिसाब सुनाने का समय", alarm_title: "याद-दिहानी", cancel_alarm: "हटाएँ", add: "जोड़ें", add_title: "नया ग्राहक", name: "नाम", phone: "फ़ोन (ज़रूरी नहीं)", save: "सेव करें", cancel: "रद्द", edit: "नाम/फ़ोन बदलें", edit_title: "ग्राहक बदलें", remove: "ग्राहक हटाएँ", remove_q: "इस ग्राहक को सूची से हटाएँ? पुराना हिसाब ऑडिट में रहेगा।", saved: "सेव हो गया", new_acct: "नया खाता", fix_name: "नाम ठीक करें", renamed: "नाम बदला", balance: "बाकी", tag: "आपकी दुकान, आपकी आवाज़", first_entry: "आज की पहली एंट्री बोलिए", example: "“रमेश का 340 उधार”",
    rem_title: "विनम्र याद-संदेश तैयार", rem_send: "WhatsApp पर भेजें", close: "बंद करें", d_credit: "आज उधार दिया",
    d_paid: "आज जमा मिला", d_out: "बाज़ार से लेना है", d_top: "सबसे ज़्यादा बाकी", d_today: "आज की एंट्री", search: "ग्राहक खोजें",
    type: "लिखें", hold: "दबाकर बोलिए", send: "भेजें", tab_bolo: "बोलो", tab_hisaab: "हिसाब", tab_khata: "खाता",
    listening: "सुन रहा हूँ…", listening_ptt: "सुन रहा हूँ… छोड़ते ही लिख दूँगा", thinking: "लिख रहा हूँ…",
    speaking: "बोल रहा हूँ… (बीच में बोल सकते हैं)", no_speech: "कुछ सुनाई नहीं दिया। दबाकर बोलिए",
    muted: "माइक बंद है, टैप करके खोलें", hf: "“छोटू, …” बोलकर शुरू करें", mode_ptt: "दबाकर बोलें", mode_hf: "हैंड्स-फ़्री: “छोटू, …”", mode_wake: "“Hey Chotu”", wake_idle: "बोलिए “Hey Chotu”", wake_listen: "सुन रहा हूँ… बोलिए", wake_err: "Wake word शुरू नहीं हुआ",
    yes: "हाँ", no: "नहीं", skip: "रहने दो", credit: "उधार", payment: "जमा", removed: "हटा दी", due: "कुल बाकी",
    advance: "एडवांस", nothing_due: "कुछ बाकी नहीं", today: "आज", yesterday: "कल", day_before: "परसों",
    customers_n: "ग्राहक", none_owe: "किसी से कुछ लेना नहीं", corrected: "सुधारी गई", voided: "हटाई गई", no_today: "आज अभी कोई एंट्री नहीं।",
    last_entry: "आख़िरी एंट्री", no_entry: "कोई एंट्री नहीं", adv_short: "एडवांस",
    optin: "ग्राहक ने याद-संदेश के लिए हाँ कहा है", src_seed: "पुरानी एंट्री", src_voice: "आवाज़ से", src_fix: "सुधार", src_ui: "हाथ से",
    mic_err: "माइक नहीं मिला। फ़ोन पर HTTPS लिंक खोलें और माइक की अनुमति दें।", ignored: "छोटू के लिए नहीं था, छोड़ दिया" },
  kn: { convo: "ಮಾತಾಡಿ", get_lbl: "ಬರಬೇಕು", give_lbl: "ಕೊಡಬೇಕು", settled: "ಲೆಕ್ಕ ಸರಿಸಮ", d_owe: "ನೀವು ಕೊಡಬೇಕು", d_yday: "ನಿನ್ನೆಯ ಎಂಟ್ರಿಗಳು", d_alarms: "ನೆನಪಿನ ಸೂಚನೆಗಳು", d_closing: "ದಿನದ ಲೆಕ್ಕ ಹೇಳುವ ಸಮಯ", alarm_title: "ನೆನಪು", cancel_alarm: "ತೆಗೆಯಿರಿ", add: "ಸೇರಿಸಿ", add_title: "ಹೊಸ ಗ್ರಾಹಕರು", name: "ಹೆಸರು", phone: "ಫೋನ್ (ಐಚ್ಛಿಕ)", save: "ಉಳಿಸಿ", cancel: "ರದ್ದು", edit: "ಹೆಸರು/ಫೋನ್ ಬದಲಿಸಿ", edit_title: "ಗ್ರಾಹಕರ ವಿವರ ಬದಲಿಸಿ", remove: "ಗ್ರಾಹಕರನ್ನು ತೆಗೆಯಿರಿ", remove_q: "ಈ ಗ್ರಾಹಕರನ್ನು ಪಟ್ಟಿಯಿಂದ ತೆಗೆಯಲೇ? ಹಳೆಯ ಲೆಕ್ಕ ಆಡಿಟ್‌ನಲ್ಲಿ ಇರುತ್ತದೆ.", saved: "ಉಳಿಸಲಾಗಿದೆ", new_acct: "ಹೊಸ ಖಾತೆ", fix_name: "ಹೆಸರು ಸರಿಪಡಿಸಿ", renamed: "ಹೆಸರು ಬದಲಾಯಿತು", balance: "ಬಾಕಿ", tag: "ನಿಮ್ಮ ಅಂಗಡಿ, ನಿಮ್ಮ ಧ್ವನಿ", first_entry: "ಇವತ್ತಿನ ಮೊದಲ ಎಂಟ್ರಿ ಹೇಳಿ", example: "“ರಮೇಶ್ 340 ಉದ್ರಿ”",
    rem_title: "ವಿನಯದ ನೆನಪಿನ ಸಂದೇಶ ಸಿದ್ಧ", rem_send: "WhatsApp ನಲ್ಲಿ ಕಳಿಸಿ", close: "ಮುಚ್ಚಿ", d_credit: "ಇವತ್ತು ಉದ್ರಿ",
    d_paid: "ಇವತ್ತು ಜಮಾ", d_out: "ಮಾರ್ಕೆಟ್‌ನಿಂದ ಬರಬೇಕು", d_top: "ಅತಿ ಹೆಚ್ಚು ಬಾಕಿ", d_today: "ಇವತ್ತಿನ ಎಂಟ್ರಿಗಳು", search: "ಗ್ರಾಹಕರನ್ನು ಹುಡುಕಿ",
    type: "ಟೈಪ್", hold: "ಒತ್ತಿ ಹಿಡಿದು ಮಾತಾಡಿ", send: "ಕಳಿಸಿ", tab_bolo: "ಮಾತಾಡಿ", tab_hisaab: "ಲೆಕ್ಕ", tab_khata: "ಖಾತೆ",
    listening: "ಕೇಳುತ್ತಿದ್ದೇನೆ…", listening_ptt: "ಕೇಳುತ್ತಿದ್ದೇನೆ… ಬಿಟ್ಟ ತಕ್ಷಣ ಬರೆಯುತ್ತೇನೆ", thinking: "ಬರೆಯುತ್ತಿದ್ದೇನೆ…",
    speaking: "ಮಾತಾಡುತ್ತಿದ್ದೇನೆ… (ಮಧ್ಯದಲ್ಲಿ ಮಾತಾಡಬಹುದು)", no_speech: "ಏನೂ ಕೇಳಿಸಲಿಲ್ಲ. ಒತ್ತಿ ಹಿಡಿದು ಮಾತಾಡಿ",
    muted: "ಮೈಕ್ ಆಫ್ ಆಗಿದೆ, ಟ್ಯಾಪ್ ಮಾಡಿ", hf: "“ಛೋಟು, …” ಎಂದು ಶುರು ಮಾಡಿ", mode_ptt: "ಒತ್ತಿ ಮಾತಾಡಿ", mode_hf: "ಹ್ಯಾಂಡ್ಸ್-ಫ್ರೀ: “ಛೋಟು, …”", mode_wake: "“Hey Chotu”", wake_idle: "“Hey Chotu” ಎಂದು ಹೇಳಿ", wake_listen: "ಕೇಳುತ್ತಿದ್ದೇನೆ… ಹೇಳಿ", wake_err: "Wake word ಶುರುವಾಗಲಿಲ್ಲ",
    yes: "ಹೌದು", no: "ಇಲ್ಲ", skip: "ಬೇಡ", credit: "ಉದ್ರಿ", payment: "ಜಮಾ", removed: "ತೆಗೆದಿದೆ", due: "ಒಟ್ಟು ಬಾಕಿ",
    advance: "ಮುಂಗಡ", nothing_due: "ಏನೂ ಬಾಕಿ ಇಲ್ಲ", today: "ಇವತ್ತು", yesterday: "ನಿನ್ನೆ", day_before: "ಮೊನ್ನೆ",
    customers_n: "ಗ್ರಾಹಕರು", none_owe: "ಯಾರ ಮೇಲೂ ಉದ್ರಿ ಇಲ್ಲ", corrected: "ಸರಿಪಡಿಸಲಾಗಿದೆ", voided: "ತೆಗೆಯಲಾಗಿದೆ", no_today: "ಇವತ್ತು ಇನ್ನೂ ಎಂಟ್ರಿ ಇಲ್ಲ.",
    last_entry: "ಕೊನೆಯ ಎಂಟ್ರಿ", no_entry: "ಎಂಟ್ರಿ ಇಲ್ಲ", adv_short: "ಮುಂಗಡ",
    optin: "ಗ್ರಾಹಕರು ನೆನಪಿನ ಸಂದೇಶಕ್ಕೆ ಒಪ್ಪಿದ್ದಾರೆ", src_seed: "ಹಳೆಯ ಎಂಟ್ರಿ", src_voice: "ಧ್ವನಿಯಿಂದ", src_fix: "ತಿದ್ದುಪಡಿ", src_ui: "ಕೈಯಿಂದ",
    mic_err: "ಮೈಕ್ ಸಿಗಲಿಲ್ಲ. ಫೋನ್‌ನಲ್ಲಿ HTTPS ಲಿಂಕ್ ತೆರೆಯಿರಿ ಮತ್ತು ಮೈಕ್ ಅನುಮತಿ ಕೊಡಿ.", ignored: "ಛೋಟುಗೆ ಅಲ್ಲ, ಬಿಟ್ಟೆ" },
  en: { convo: "Talk", get_lbl: "you get", give_lbl: "you owe", settled: "Settled", d_owe: "You owe", d_yday: "Yesterday's entries", d_alarms: "Reminders", d_closing: "Daily summary time", alarm_title: "Reminder", cancel_alarm: "Remove", add: "Add", add_title: "New customer", name: "Name", phone: "Phone (optional)", save: "Save", cancel: "Cancel", edit: "Edit name / phone", edit_title: "Edit customer", remove: "Remove customer", remove_q: "Remove this customer from the list? Their history stays in the audit log.", saved: "Saved", new_acct: "New account", fix_name: "Fix name", renamed: "Name changed", balance: "Due", tag: "Your kirana, your voice", first_entry: "Say today's first entry", example: "“Ramesh, 340 credit”",
    rem_title: "Polite reminder ready", rem_send: "Send on WhatsApp", close: "Close", d_credit: "You gave today",
    d_paid: "You got today", d_out: "You'll get from the market", d_top: "Highest dues", d_today: "Today's entries", search: "Find a customer",
    type: "Type", hold: "Hold and speak", send: "Send", tab_bolo: "Speak", tab_hisaab: "Summary", tab_khata: "Khata",
    listening: "Listening…", listening_ptt: "Listening… release to record", thinking: "Writing…",
    speaking: "Speaking… (you can interrupt)", no_speech: "Didn't hear anything. Hold and speak",
    muted: "Mic is off, tap to turn on", hf: "Start with “Chotu, …”", mode_ptt: "Hold to talk", mode_hf: "Hands-free: “Chotu, …”", mode_wake: "“Hey Chotu”", wake_idle: "Say “Hey Chotu”", wake_listen: "Listening… go ahead", wake_err: "Wake word could not start",
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
  $("#modeBtn .lbl").textContent = modeLabel(S.mode);
  if (S.started) micState(restingHint());
}
function setLang(lang, fromUser) {
  S.lang = lang;
  $("#langSel").value = lang;
  try { localStorage.setItem("nc_lang", lang); } catch (_) {}
  applyI18n();
  if (fromUser && S.started) { send({ type: "lang", lang }); toast($("#langSel").selectedOptions[0].textContent); }
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
      S.wakeCfg = m.wake || null;
      if (wakeAvailable() && S.live && S.mode === "ptt" && !S.wakeTried) { S.wakeTried = true; if (S.started) setMode("wake"); }
      setBadge(m.live ? "Live" : "Mock", m.live ? "live" : "mock");
      if (!m.live) { $("#typeForm").hidden = false; $("#typeBtn").setAttribute("aria-pressed", "true"); $("#mic").disabled = true; micState("Mock mode: no Gnani key, type below"); }
      break;
    case "transcript":
      if (m.text) addFeed(m.text, m.typed ? "you typed" : "you");
      break;
    case "stt_event":
      if (m.event === "speech_start" && S.mode === "handsfree") { S.turnOpen = true; setMic("listening", tr("listening")); }
      if (m.event === "processing" && S.turnOpen && !S.speaking) setMic("thinking", tr("thinking"));
      break;
    case "no_speech":
      S.turnOpen = false;
      if (m.quiet) restMic(); else setMic("", tr("no_speech"));
      break;
    case "reply":
      onReply(m);
      break;
    case "tts_start":
      S.ttsRate = m.sample_rate || 16000;
      break;
    case "tts_end":
      if (!S.sources.length) restMic();
      break;
    case "tts_cancel":
      stopPlayback();
      restMic();
      break;
    case "metrics":
      if (m.end_to_first_audio_ms != null) showLatency(m.end_to_first_audio_ms, "server");
      break;
    case "dashboard_dirty":
      refreshSoon();
      break;
    case "stt_closed":
      break;
    case "notice":
      addFeed(m.text, "sys");
      break;
    case "ignored":
      addFeed(`"${m.text}" (${tr("ignored")})`, "sys");
      restMic();
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
    if (S.mode === "wake" || S.convo) return onWakeFrame(e.data);
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
    if (!S.sources.length) { S.speaking = false; restMic(); afterReplyDone(); }
  };
  if (S.waitingFirstAudio) {
    S.waitingFirstAudio = false;
    showLatency(Math.round(performance.now() - S.releaseAt + (at - S.ctx.currentTime) * 1000), "phone");
  }
  if (!S.speaking) { S.replySeq = (S.replySeq || 0) + 1; if (S.pv && S.mode === "wake") S.pv.pause(); S.speaking = true; if (!S.capturing || S.mode === "handsfree") setMic("speaking", tr("speaking")); }
}

function stopPlayback() {
  for (const s of S.sources) { try { s.stop(); } catch (_) {} }
  S.sources = [];
  S.nextTime = 0;
  S.speaking = false;
}


/* ------------------------------------------------------- "Hey Chotu" wake word
   Porcupine runs on the phone (WASM); nothing leaves the phone until the wake word is heard.
   After the wake word: one command is captured with a loudness gate (far/quiet voices are sent as
   silence), it ends on ~0.9 s of quiet, then Chotu goes back to sleep. After Chotu replies there is
   an 8 s follow-up window ("haan", "aur 200") without saying the wake word again. */
function loadScript(src) {
  return new Promise((ok, bad) => { const s = document.createElement("script"); s.src = src; s.onload = ok; s.onerror = bad; document.head.appendChild(s); });
}
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
const wakeAvailable = () => Boolean(S.wakeCfg || SR);
// words the recognisers return for "Chotu" in Hindi / Kannada / English
// "Chotu" as the recognisers write it (Latin, Devanagari, Kannada) — with or without hey/hi/oye/arre/ae in front
// (not "chhota/chhote" = "small", which is said all day in a shop)
const WAKE_RE = /(c+h*o+t+[uo]+\b|shot+u\b|jot+u\b|छो[टठ][ूुो]|चोट[ूु]|ಛೋಟು|ಚೋಟು|ಛೋಟೂ|ಚೋಟೂ)/i;

/* Fallback wake word without any account: the browser's own speech recogniser (Chrome / Edge / Android).
   It listens for "Chotu" in short bursts and restarts itself; it pauses while Chotu is talking
   (so Chotu's own name in a reply can't wake it) and while a command is being captured. */
function initWebSpeechWake() {
  if (!SR) return false;
  const rec = new SR();
  rec.lang = "hi-IN";
  rec.continuous = true;
  rec.interimResults = true;
  rec.maxAlternatives = 3;
  const eng = { kind: "webspeech", rec, running: false, dead: false, quietUntil: 0 };
  rec.onresult = (e) => {
    if (S.mode !== "wake" || S.wakeTurn || S.speaking || performance.now() < eng.quietUntil) return;
    for (let i = e.resultIndex; i < e.results.length; i++)
      for (let j = 0; j < e.results[i].length; j++)
        if (WAKE_RE.test(e.results[i][j].transcript)) { eng.pause(); onWake(); return; }
  };
  rec.onstart = () => { eng.running = true; eng.startedAt = performance.now(); };
  rec.onend = () => { eng.running = false; setTimeout(() => eng.resume(), 250); };
  rec.onerror = (e) => {
    if (e.error === "not-allowed" || e.error === "service-not-allowed") { eng.dead = true; addFeed(tr("wake_err"), "err"); }
  };
  eng.resume = () => {
    if (eng.dead || eng.running || S.mode !== "wake" || S.convo || S.wakeTurn || S.speaking) return;
    try { rec.start(); } catch (_) {}
  };
  // watchdog: Chrome's recogniser silently stalls now and then; keep it alive and fresh
  setInterval(() => {
    if (eng.dead || S.mode !== "wake" || S.convo || S.wakeTurn || S.speaking) return;
    if (!eng.running) eng.resume();
    else if (performance.now() - (eng.startedAt || 0) > 50000) { try { rec.stop(); } catch (_) {} }
  }, 1500);
  eng.pause = () => { try { rec.abort(); } catch (_) {} eng.running = false; };
  eng.process = () => {};
  S.pv = eng;
  eng.resume();
  return true;
}

async function initWake() {
  if (S.pv) return true;
  if (!S.wakeCfg) return initWebSpeechWake();
  try {
    if (!window.PorcupineWeb) await loadScript("/vendor/porcupine-web.min.js");
    const c = S.wakeCfg;
    S.pv = await PorcupineWeb.PorcupineWorker.create(
      c.access_key,
      [{ label: c.label, publicPath: c.keyword_url, sensitivity: c.sensitivity, forceWrite: true }],
      () => onWake(),
      { publicPath: c.model_url, forceWrite: true },
      { processErrorCallback: (err) => console.warn("porcupine", err) });
    S.pv.pause = () => {};
    S.pv.resume = () => {};
    return true;
  } catch (err) {
    console.warn("wake init failed", err);
    addFeed(`${tr("wake_err")}: ${err.message || err}`, "err");
    S.pv = null;
    return false;
  }
}
function frameDb(i16) {
  let sum = 0;
  for (let i = 0; i < i16.length; i++) sum += i16[i] * i16[i];
  const rms = Math.sqrt(sum / i16.length) / 32768;
  return 20 * Math.log10(rms + 1e-9);
}
S.floorBuf = [];
function noiseFloor() {
  if (S.floorBuf.length < 10) return -60;
  const a = [...S.floorBuf].sort((x, y) => x - y);
  return a[Math.floor(a.length * 0.3)];
}
function onWakeFrame(buf) {
  const frame = new Int16Array(buf);
  const db = frameDb(frame);
  const t = performance.now();
  const w = S.wakeTurn;
  if (!w) {
    S.floorBuf.push(db);
    if (S.floorBuf.length > 120) S.floorBuf.shift();            // ~4 s of shop noise
    if (S.pv && S.pv.kind !== "webspeech" && !S.speaking && !S.convo) S.pv.process(frame);
    return;
  }
  // capturing one command: gate = shop noise + 12 dB (someone close to the phone)
  const gate = Math.max(noiseFloor() + 12, -50);
  const loud = db > gate;
  w.run = loud ? w.run + 1 : 0;
  if (w.run >= 3) { w.heard = true; w.lastLoud = t; }
  else if (loud && w.heard) w.lastLoud = t;
  if (S.ws && S.ws.readyState === 1) S.ws.send(loud || w.heard ? buf : new Int16Array(frame.length).buffer);
  const done = (w.heard && t - w.lastLoud > 900) || (!w.heard && t - w.start > w.wait) || t - w.start > 12000;
  if (done) endWakeTurn();
}
function beep() {
  if (!S.ctx) return;
  const o = S.ctx.createOscillator(), g = S.ctx.createGain();
  o.frequency.value = 880; g.gain.value = 0.08;
  o.connect(g).connect(S.ctx.destination);
  o.start(); o.stop(S.ctx.currentTime + 0.12);
}
function onWake(followUp = false) {
  if ((S.mode !== "wake" && !S.convo) || S.wakeTurn) return;
  if (!followUp) { stopPlayback(); send({ type: "interrupt" }); beep(); if (navigator.vibrate) navigator.vibrate(20); }
  if (S.pv) S.pv.pause();
  S.wakeTurn = { start: performance.now(), heard: false, lastLoud: 0, run: 0, wait: followUp ? 8000 : 5000, followUp };
  S.capturing = true;
  send({ type: "ptt_down", wake: true, followup: followUp });
  setMic("listening", tr("wake_listen"));
  convoState("listening");
}
function endWakeTurn() {
  const w = S.wakeTurn;
  S.wakeTurn = null;
  S.capturing = false;
  S.releaseAt = performance.now();
  send({ type: "ptt_up" });
  if (w && w.heard) { S.turnOpen = true; S.waitingFirstAudio = true; S.lastWake = true; setMic("thinking", tr("thinking")); convoState("thinking"); }
  else {
    S.lastWake = false; restMic();
    if (S.convo) { setTimeout(() => onWake(true), 200); return; }       // conversation: keep listening
    if (S.pv) setTimeout(() => S.pv.resume(), 300);
  }
}
function afterReplyDone() {
  if (S.convo) { convoState("listening"); if (!S.wakeTurn) setTimeout(() => onWake(true), 250); return; }
  if (S.mode === "wake" && S.pv) { S.pv.quietUntil = performance.now() + 800; setTimeout(() => S.pv && !S.wakeTurn && S.pv.resume(), 900); }
  // follow-up listening only when Chotu asked a question; otherwise back to sleep (ignore counter chatter)
  if (S.mode !== "wake" || !S.lastWake || S.wakeTurn || !S.followNeeded) return;
  S.lastWake = false;
  setTimeout(() => onWake(true), 250);
}

/* --------------------------------------------- voice conversation (no reading)
   Full-screen: Chotu listens, answers aloud, listens again, until you close it. */
function convoState(state, caption) {
  if (!S.convo) return;
  const o = $("#convo");
  o.dataset.state = state;
  o.querySelector(".c-status").textContent = tr(state === "listening" ? "wake_listen" : state === "thinking" ? "thinking" : "speaking");
  if (caption !== undefined) o.querySelector(".c-caption").textContent = caption;
}
function openConvo() {
  if (!S.live) { toast("Mock mode"); return; }
  S.convo = true;
  if (S.pv && S.pv.pause) S.pv.pause();
  $("#convo").hidden = false;
  convoState("listening", "");
  stopPlayback();
  onWake(true);
}
function closeConvo() {
  S.convo = false;
  $("#convo").hidden = true;
  if (S.wakeTurn) { S.wakeTurn = null; S.capturing = false; send({ type: "ptt_up" }); }
  stopPlayback(); send({ type: "interrupt" });
  restMic();
  if (S.mode === "wake" && S.pv) setTimeout(() => S.pv.resume(), 300);
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
  S.turnOpen = true;
  setMic("thinking", tr("thinking"));
}

function setMode(mode) {
  if (mode === "wake" && !S.pv) { initWake().then((ok) => ok ? setMode("wake") : micState(tr("wake_err"))); return; }
  S.mode = mode;
  if (mode !== "wake" && S.pv) S.pv.pause();
  if (mode === "wake" && S.pv) setTimeout(() => S.pv.resume(), 200);
  const hf = mode === "handsfree";
  $("#modeBtn").setAttribute("aria-pressed", String(mode !== "ptt"));
  $("#modeBtn .lbl").textContent = modeLabel(mode);
  S.capturing = hf;
  S.muted = false;
  S.wakeTurn = null;
  send({ type: "mode", mode: hf ? "handsfree" : "ptt" });
  setMic("", restingHint());
}
const restingHint = () => (S.mode === "wake" ? tr("wake_idle") : S.mode === "handsfree" ? (S.muted ? tr("muted") : tr("hf")) : tr("hold"));
const modeLabel = (m) => (m === "wake" ? tr("mode_wake") : m === "handsfree" ? tr("mode_hf") : tr("mode_ptt"));

let micTimer = null;
function setMic(state, text) {
  const mic = $("#mic");
  mic.classList.remove("listening", "thinking", "speaking");
  if (state) mic.classList.add(state);
  if (text) micState(text);
  // safety net: no state may spin forever
  clearTimeout(micTimer);
  if (state === "thinking" || state === "speaking") micTimer = setTimeout(() => restMic(), state === "thinking" ? 9000 : 30000);
}
// back to idle unless the user is actively holding the button / wake capture is open
function restMic() {
  if (S.capturing && S.mode === "ptt") return;
  S.turnOpen = false;
  setMic(S.wakeTurn ? "listening" : "", restingHint());
}
const micState = (t) => ($("#micState").textContent = t);

/* ------------------------------------------------------------------ replies */
function onReply(m) {
  S.turnOpen = false;
  S.followNeeded = Boolean(m.pending);
  // reply arrived: if no audio follows (TTS off/failed), stop the spinner. Spoken replies get time to start.
  const myReply = (S.replySeq = (S.replySeq || 0) + 1);
  const wait = m.speak && S.live ? 8000 : 1200;
  setTimeout(() => { if (myReply === S.replySeq && !S.speaking && !S.sources.length) { restMic(); afterReplyDone(); } }, wait);
  if (S.convo) convoState("speaking", m.display);
  if (m.lang && m.lang !== S.replyLang) { S.replyLang = m.lang; if (S.lang === "auto") applyI18n(); }
  addFeed(m.display, "bot");
  const q = $("#question");
  if (m.pending) {
    q.hidden = false;
    q.querySelector(".q-text").textContent = "";   // the question is already the last chat bubble
    const box = q.querySelector(".q-options");
    box.innerHTML = "";
    const opts = m.pending.options.length ? m.pending.options.map((o) => [o.name, o.say || o.name])
      : [[tr("yes"), "haan"], [tr("no"), "nahi"]];
    if (m.pending.options.length && m.pending.kind !== "need_kind") opts.push([tr("skip"), "nahi rehne do"]);
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
  for (const e of m.events) {
    if (e.type === "alarm" || e.type === "closing") notify(m.display);
    if (e.type === "alarm_set" || e.type === "settings") refreshSoon();
    if (e.type === "customer_created") addEditChip(e.customer, tr("new_acct"));
    if (e.type === "customer_updated") document.querySelectorAll(".entry .e-name").forEach((n) => { if (n.textContent === e.old) n.textContent = e.customer.name; });
  }
  if (m.events.some((e) => e.type.startsWith("customer_"))) refreshSoon();
  const rem = m.events.find((e) => e.type === "reminder");
  if (rem) showReminder(rem);
  scrollChat();
  if (!S.live) setMic("", restingHint());
}

// every saved entry becomes one ruled line in the khata (chat), like a line written in the notebook
async function showEntry(t, voided, removed) {
  S.lineCust = t.customer_id;
  const li = document.createElement("li");
  li.className = `entry ${t.kind === "PAYMENT" ? "got" : "gave"}${removed ? " removed" : ""}`;
  const sign = t.kind === "PAYMENT" ? "−" : "+";
  const was = voided && voided.txn.amount_paise !== t.amount_paise ? `<s>${inr(voided.txn.amount_paise)}</s> ` : "";
  li.innerHTML = `<span class="e-time">${esc(t.txn_time ? fmtTime(t.txn_time) : dayLabel(t.txn_date))}</span>
    <span class="e-name"></span><button class="e-edit" type="button" aria-label="Edit name">✎</button>
    <span class="e-amt">${was}${sign}${inr(t.amount_paise)}</span>
    <span class="e-bal"></span>`;
  li.querySelector(".e-name").textContent = t.customer;
  li.querySelector(".e-edit").onclick = () => openEdit(t.customer_id);
  const feed = $("#feed");
  feed.append(li);
  scrollChat();
  try {
    const c = await (await fetch(`/api/customers/${t.customer_id}`)).json();
    li.querySelector(".e-bal").textContent = removed ? tr("removed") : balText(c.balance);
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
  feed.append(li);
  while (feed.children.length > 40) feed.firstChild.remove();
  scrollChat();
  return li;
}
function scrollChat() {
  if (!$("#tab-bolo").classList.contains("active")) return;
  requestAnimationFrame(() => { const m = $("#scroller"); m.scrollTop = m.scrollHeight; });
}
function addEditChip(cust, label) {
  const li = addFeed("", "chip");
  li.innerHTML = `<span>${esc(label)}: <strong>${esc(cust.name)}</strong></span>`;
  const b = document.createElement("button");
  b.type = "button";
  b.textContent = "✎ " + tr("fix_name");
  b.onclick = () => openEdit(cust.id);
  li.appendChild(b);
}
function chime() {
  if (!S.ctx) return;
  [660, 880, 990].forEach((f, i) => {
    const o = S.ctx.createOscillator(), g = S.ctx.createGain();
    o.frequency.value = f; g.gain.value = 0.09;
    o.connect(g).connect(S.ctx.destination);
    const t0 = S.ctx.currentTime + i * 0.18;
    o.start(t0); o.stop(t0 + 0.15);
  });
}
function notify(text) {
  chime();
  const li = addFeed(text, "alarm");
  const b = document.createElement("button");
  b.type = "button"; b.textContent = "✓";
  b.onclick = () => li.classList.add("done");
  li.appendChild(b);
  if (navigator.vibrate) navigator.vibrate([200, 100, 200]);
  try {
    if ("Notification" in window && Notification.permission === "granted" && document.hidden)
      new Notification("Namma Chotu", { body: text, icon: "/icon.svg" });
  } catch (_) {}
}
let toastTimer = null;
function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), 2200);
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

const entryRow = (t) =>
  `<li><span class="n">${esc(t.customer)}<span class="s">${t.txn_time ? fmtTime(t.txn_time) : dayLabel(t.txn_date)}${t.replaces ? ", " + tr("corrected") : ""}</span></span>
   <span class="m ${t.kind === "PAYMENT" ? "p" : "c"}">${t.kind === "PAYMENT" ? "−" : "+"}${inr(t.amount_paise)}</span></li>`;

async function refreshDash() {
  const d = await (await fetch("/api/dashboard")).json();
  $("#dCredit").textContent = inr(d.today_credit);
  $("#dPaid").textContent = inr(d.today_payments);
  $("#dOut").textContent = inr(d.total_outstanding);
  $("#dCust").textContent = `${d.customers} ${tr("customers_n")}`;
  $("#dOwe").textContent = inr(d.shop_owes || 0);
  $("#dTop").innerHTML = d.top_debtors.map((c) =>
    `<li><span class="n">${esc(c.name)}</span><span class="m c">${inr(c.balance)}</span></li>`).join("") ||
    `<li class="empty-row">${tr("none_owe")}</li>`;
  const day = (r) => r.entries.filter((t) => t.source !== "seed" || true);
  $("#dRecent").innerHTML = day(d.today).map(entryRow).join("") || `<li class="empty-row">${tr("no_today")}</li>`;
  $("#dYday").innerHTML = day(d.yesterday).map(entryRow).join("") || `<li class="empty-row">${tr("no_entry")}</li>`;
  $("#dYdaySum").textContent = `+${inr(d.yesterday.credit)} · −${inr(d.yesterday.payments)}`;
  $("#dAlarms").innerHTML = (d.alarms || []).map((a) =>
    `<li><span class="n">${esc(a.text)}<span class="s">${dayLabel(a.due_at.slice(0, 10))}, ${fmtTime(a.due_at.slice(11, 16))}</span></span>
     <button class="btn danger small" data-alarm="${a.id}" type="button">${esc(tr("cancel_alarm"))}</button></li>`).join("") ||
    `<li class="empty-row">—</li>`;
  for (const b of document.querySelectorAll("[data-alarm]"))
    b.onclick = async () => { await fetch(`/api/alarms/${b.dataset.alarm}`, { method: "DELETE" }); refreshDash(); };
  try {
    const st = await (await fetch("/api/settings")).json();
    $("#closingOn").checked = st.closing_on;
    if (document.activeElement !== $("#closingTime")) $("#closingTime").value = st.closing_time;
  } catch (_) {}
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
     <span class="m ${c.balance > 0 ? "c" : "p"}">${c.balance === 0 ? "—" : inr(Math.abs(c.balance))}<span class="s">${c.balance > 0 ? tr("get_lbl") : c.balance < 0 ? tr("give_lbl") : ""}</span></span></button></li>`).join("");
}
const sheet = {
  open(html) { $("#custSheetBody").innerHTML = html; $("#custSheet").hidden = false; },
  close() { $("#custSheet").hidden = true; $("#custSheetBody").innerHTML = ""; },
};
// one balance, always said from the shopkeeper's side: "₹500 लेना है" / "₹300 देना है" / "हिसाब बराबर"
const balText = (b) => (b > 0 ? `${inr(b)} ${tr("get_lbl")}` : b < 0 ? `${inr(-b)} ${tr("give_lbl")}` : tr("settled"));
const fmtTime = (hhmm) => {
  if (!hhmm) return "";
  const [h, m] = hhmm.split(":").map(Number);
  return `${h % 12 || 12}:${String(m).padStart(2, "0")} ${h < 12 ? "AM" : "PM"}`;
};
const whenText = (t) => `${dayLabel(t.txn_date)}${t.txn_time ? ", " + fmtTime(t.txn_time) : ""}`;

async function openCustomer(id) {
  const r = await fetch(`/api/customers/${id}`);
  if (!r.ok) return refreshCustomers();
  const c = await r.json();
  sheet.open(`<div class="cust-head"><h3>${esc(c.name)}</h3>
      ${c.name_hi ? `<p class="alt">${esc(c.name_hi)}</p>` : ""}
      ${c.phone ? `<p class="phone">☎ ${esc(c.phone)}</p>` : ""}</div>
    <p class="bal" style="color:${c.balance > 0 ? "var(--udhaar)" : "var(--jama)"}">${balText(c.balance)}</p>
    <div class="actions"><button class="btn" id="cEdit" type="button">✎ ${esc(tr("edit"))}</button>
      ${c.balance === 0 ? `<button class="btn danger" id="cRemove" type="button">${esc(tr("remove"))}</button>` : ""}</div>
    <label class="optin"><input type="checkbox" id="optin" ${c.reminder_opt_in ? "checked" : ""}> ${esc(tr("optin"))}</label>
    <ol class="rows txns">${c.transactions.map((t) =>
      `<li class="${t.status === "voided" ? "void" : ""}"><span class="n">${whenText(t)}<span class="s">${({ seed: tr("src_seed"), voice: tr("src_voice"), "voice-correction": tr("src_fix"), ui: tr("src_ui") })[t.source] || t.source}${t.status === "voided" ? ", " + tr("voided") : ""}</span></span>
       <span class="m ${t.kind === "PAYMENT" ? "p" : "c"}">${t.kind === "PAYMENT" ? "−" : "+"}${inr(t.amount_paise)}</span></li>`).join("") || `<li class="empty-row">${tr("no_entry")}</li>`}</ol>`);
  $("#cEdit").onclick = () => openEdit(id, c);
  const rm = $("#cRemove");
  if (rm) rm.onclick = async () => {
    if (!confirm(tr("remove_q"))) return;
    const res = await fetch(`/api/customers/${id}`, { method: "DELETE" });
    if (res.ok) { sheet.close(); toast(tr("saved")); refreshAll(); }
    else toast((await res.json()).detail || "Error");
  };
  $("#optin").onchange = async (e) => {
    await fetch(`/api/customers/${id}/opt-in`, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ opt_in: e.target.checked }) });
    refreshCustomers();
  };
}

function customerForm(title, c) {
  return `<h3 style="margin:0 44px 4px 0">${esc(title)}</h3>
    <form id="custForm" autocomplete="off">
      <label class="field">${esc(tr("name"))}<input id="fName" required minlength="2" maxlength="60" value="${esc(c ? c.name : "")}" autocapitalize="words"></label>
      <label class="field">${esc(tr("phone"))}<input id="fPhone" inputmode="tel" maxlength="14" value="${esc(c && c.phone ? c.phone : "")}"></label>
      <p class="form-err" id="fErr"></p>
      <div class="actions"><button class="btn primary" type="submit">${esc(tr("save"))}</button>
        <button class="btn" type="button" id="fCancel">${esc(tr("cancel"))}</button></div>
    </form>`;
}
async function saveCustomer(url, method, after) {
  const body = { name: $("#fName").value.trim(), phone: $("#fPhone").value.trim() };
  const res = await fetch(url, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) { $("#fErr").textContent = typeof data.detail === "string" ? data.detail : "Please check the name and phone"; return; }
  toast(tr("saved"));
  await refreshAll();
  after(data);
}
async function openEdit(id, c) {
  if (!c) { const r = await fetch(`/api/customers/${id}`); if (!r.ok) return; c = await r.json(); }
  sheet.open(customerForm(tr("edit_title"), c));
  $("#fName").focus();
  $("#fCancel").onclick = () => openCustomer(id);
  $("#custForm").onsubmit = (e) => { e.preventDefault(); saveCustomer(`/api/customers/${id}`, "PATCH", (d) => {
    refreshSoon();
    openCustomer(id);
  }); };
}
function openAdd() {
  sheet.open(customerForm(tr("add_title"), null));
  $("#fName").focus();
  $("#fCancel").onclick = () => sheet.close();
  $("#custForm").onsubmit = (e) => { e.preventDefault(); saveCustomer("/api/customers", "POST", (d) => openCustomer(d.id)); };
}
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

/* -------------------------------------------------------------------- wire */
function wire() {
  const mic = $("#mic");
  mic.addEventListener("pointerdown", (e) => {
    if (S.mode === "wake") { if (!S.capturing) onWake(); return; }
    if (S.mode === "handsfree") {
      S.muted = !S.muted;
      if (!S.muted) stopPlayback();
      setMic("", restingHint());
      return;
    }
    mic.setPointerCapture(e.pointerId);
    pressStart(e);
  });
  mic.addEventListener("pointerup", (e) => { if (S.mode !== "wake") pressEnd(e); });
  mic.addEventListener("pointercancel", pressEnd);
  mic.addEventListener("contextmenu", (e) => e.preventDefault());
  document.addEventListener("keydown", (e) => {
    if (e.code === "Space" && !e.repeat && document.activeElement.tagName !== "INPUT") pressStart(e);
  });
  document.addEventListener("keyup", (e) => {
    if (e.code === "Space" && document.activeElement.tagName !== "INPUT") pressEnd(e);
  });
  $("#modeBtn").onclick = () => setMode(S.mode !== "ptt" ? "ptt" : (wakeAvailable() ? "wake" : "handsfree"));
  $("#typeBtn").onclick = () => {
    const f = $("#typeForm"); f.hidden = !f.hidden;
    $("#typeBtn").setAttribute("aria-pressed", String(!f.hidden));
    if (!f.hidden) $("#typeInput").focus();
  };
  $("#addCustBtn").onclick = openAdd;
  $("#convoBtn").onclick = openConvo;
  $("#convo .c-close").onclick = closeConvo;
  $("#convo .c-orb").onclick = () => { if (S.speaking) { stopPlayback(); send({ type: "interrupt" }); afterReplyDone(); } };
  const saveClosing = () => fetch("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ closing_time: $("#closingTime").value, closing_on: $("#closingOn").checked }) }).then(() => toast(tr("saved")));
  $("#closingTime").onchange = saveClosing;
  $("#closingOn").onchange = saveClosing;

  $("#custSheet .sheet-x").onclick = () => sheet.close();
  $("#custSheet").onclick = (e) => { if (e.target.id === "custSheet") sheet.close(); };
  $("#typeForm").onsubmit = (e) => { e.preventDefault(); submitText($("#typeInput").value); $("#typeInput").value = ""; };
  $("#reminderCard .r-close").onclick = () => ($("#reminderCard").hidden = true);
  $("#search").oninput = renderCustomers;
  $("#custList").onclick = (e) => { const b = e.target.closest("[data-id]"); if (b) openCustomer(b.dataset.id); };
  for (const b of document.querySelectorAll(".tabs button")) {
    b.onclick = () => {
      document.querySelectorAll(".tabs button").forEach((x) => x.classList.toggle("on", x === b));
      document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.id === `tab-${b.dataset.tab}`));
      if (b.dataset.tab !== "bolo") refreshAll(); else scrollChat();
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
    try { if ("Notification" in window && Notification.permission === "default") Notification.requestPermission(); } catch (_) {}
    send({ type: "start", mode: S.mode === "handsfree" ? "handsfree" : "ptt", lang });
    if (wakeAvailable() && S.live && S.mode === "ptt") setMode("wake");
    refreshAll();
  }
}

wire();
$("#langSel").onchange = (e) => setLang(e.target.value, true);
try { const saved = localStorage.getItem("nc_lang"); if (saved) setLang(saved, false); } catch (_) {}
applyI18n();
connect();
refreshAll();

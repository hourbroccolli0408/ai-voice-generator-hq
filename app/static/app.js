const state = {
  config: null,
  file: null,
  recorder: null,
  recordedChunks: [],
  timer: null,
  seconds: 0,
  currentJob: null,
  pollTimer: null,
  supabase: null,
  session: null,
  audioObjectUrl: null,
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const elements = {
  form: $("#generation-form"),
  input: $("#reference-input"),
  drop: $("#drop-zone"),
  uploadState: $("#upload-state"),
  fileState: $("#file-state"),
  fileName: $("#file-name"),
  fileMeta: $("#file-meta"),
  record: $("#record-button"),
  recordLabel: $("#record-label"),
  recordTime: $("#record-time"),
  script: $("#script"),
  count: $("#char-count"),
  voice: $("#voice"),
  voiceDescription: $("#voice-description"),
  cloneControls: $("#clone-controls"),
  presetReady: $("#preset-ready"),
  model: $("#model"),
  language: $("#language"),
  translateMode: $("#translate-mode"),
  translateOptions: $("#translate-options"),
  sourceLanguage: $("#source-language"),
  targetLanguages: $("#target-languages"),
  outputLanguage: $("#output-language"),
  outputLanguageControl: $("#output-language-control"),
  submit: $("#generate-button"),
  result: $("#result-card"),
  resultTitle: $("#result-title"),
  resultMessage: $("#result-message"),
  resultTime: $("#result-time"),
  progressTrack: $("#progress-track"),
  progress: $("#progress-bar"),
  player: $("#player"),
  audio: $("#result-audio"),
  play: $("#play-button"),
  waveform: $("#waveform"),
  playerTime: $("#player-time"),
  download: $("#download-button"),
  toast: $("#toast"),
};

function toast(message, isError = false) {
  elements.toast.textContent = message;
  elements.toast.classList.toggle("error", isError);
  elements.toast.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => elements.toast.classList.remove("show"), 3600);
}

async function apiFetch(url, options = {}) {
  const headers = new Headers(options.headers || {});
  if (state.session?.access_token) headers.set("Authorization", `Bearer ${state.session.access_token}`);
  return fetch(url, { ...options, headers });
}

async function initAuth() {
  if (state.config.auth.mode !== "supabase") return;
  if (!window.supabase || !state.config.auth.supabase_url || !state.config.auth.supabase_anon_key) {
    throw new Error("Authentication is not configured correctly");
  }
  state.supabase = window.supabase.createClient(
    state.config.auth.supabase_url,
    state.config.auth.supabase_anon_key,
  );
  const { data } = await state.supabase.auth.getSession();
  state.session = data.session;
  $("#auth-overlay").classList.toggle("hidden", Boolean(state.session));
  $("#signout-button").classList.toggle("hidden", !state.session);
  state.supabase.auth.onAuthStateChange((_event, session) => {
    state.session = session;
    $("#auth-overlay").classList.toggle("hidden", Boolean(session));
    $("#signout-button").classList.toggle("hidden", !session);
    if (session) loadAccount();
  });
}

async function submitAuth(createAccount = false) {
  const form = $("#auth-form");
  if (!form.reportValidity()) return;

  const email = $("#auth-email").value.trim();
  const password = $("#auth-password").value;
  const message = $("#auth-message");
  message.textContent = "";
  const action = createAccount
    ? state.supabase.auth.signUp({ email, password })
    : state.supabase.auth.signInWithPassword({ email, password });
  const { data, error } = await action;
  if (error) {
    message.textContent = error.message;
    return;
  }
  if (createAccount && !data.session) {
    message.textContent = "Check your email to confirm your beta account.";
    return;
  }
  state.session = data.session;
  $("#auth-overlay").classList.add("hidden");
  $("#signout-button").classList.remove("hidden");
  await loadAccount();
  await loadHistory();
}

async function loadAccount() {
  const response = await apiFetch("/api/account");
  if (!response.ok) return;
  const account = await response.json();
  $("#credit-balance").textContent = account.credits.toLocaleString();
}

function formatBytes(bytes) {
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function formatTime(seconds) {
  const safe = Number.isFinite(seconds) ? Math.max(0, Math.floor(seconds)) : 0;
  return `${String(Math.floor(safe / 60)).padStart(2, "0")}:${String(safe % 60).padStart(2, "0")}`;
}

function setFile(file) {
  if (!file) return;
  if (state.config && file.size > state.config.limits.max_upload_mb * 1024 * 1024) {
    toast(`Please use a file under ${state.config.limits.max_upload_mb} MB.`, true);
    return;
  }
  state.file = file;
  elements.fileName.textContent = file.name;
  elements.fileMeta.textContent = `${formatBytes(file.size)} · Ready to clone`;
  elements.uploadState.classList.add("hidden");
  elements.fileState.classList.remove("hidden");
}

function clearFile(event) {
  event?.stopPropagation();
  state.file = null;
  elements.input.value = "";
  elements.fileState.classList.add("hidden");
  elements.uploadState.classList.remove("hidden");
}

function updateScriptMeta() {
  const length = elements.script.value.length;
  elements.count.textContent = length.toLocaleString();
  if (elements.translateMode.checked) {
    const targets = selectedTargetLanguages();
    $("#duration-estimate").textContent = (length * targets.length).toLocaleString();
    $("#estimate-label").textContent = "credits for all outputs";
    $("#translation-cost").textContent = targets.length
      ? `${length.toLocaleString()} characters × ${targets.length} languages = ${(length * targets.length).toLocaleString()} credits.`
      : "Choose output languages to see the credit cost.";
  } else {
    $("#duration-estimate").textContent = `~${Math.max(0, Math.round(length / 15))} sec`;
    $("#estimate-label").textContent = "estimated audio";
  }
}

function isCloneMode() {
  return elements.voice.value === "clone";
}

function selectedTargetLanguages() {
  return $$("#target-languages input:checked").map((input) => input.value);
}

function languageName(code) {
  if (state.config.languages[code]) return state.config.languages[code];
  try {
    return new Intl.DisplayNames(["en"], { type: "language" }).of(code) || code.toUpperCase();
  } catch {
    return code.toUpperCase();
  }
}

function updateTargetSelection(changedInput) {
  const targets = selectedTargetLanguages();
  const limit = state.config.limits.max_translation_targets;
  if (targets.length > limit && changedInput) {
    changedInput.checked = false;
    toast(`Choose up to ${limit} output languages at once.`, true);
  }
  const count = selectedTargetLanguages().length;
  $("#target-count").textContent = `${count} / ${limit} selected`;
  $$("#target-languages input:not(:checked)").forEach((input) => {
    input.disabled = count >= limit;
  });
  updateScriptMeta();
}

function renderTranslationMode() {
  const translating = elements.translateMode.checked;
  elements.translateOptions.classList.toggle("hidden", !translating);
  $("#language-control").classList.toggle("hidden", translating);
  elements.submit.querySelector("span").textContent = translating
    ? "Translate & generate"
    : "Generate voiceover";
  if (translating) {
    const voice = state.config.voices[elements.voice.value];
    if (!voice || !["chatterbox", "chatterbox-default"].includes(voice.engine)) {
      elements.voice.value = "global";
    }
    elements.model.value = "multilingual-v3";
  }
  renderVoiceMode();
  updateScriptMeta();
}

function renderLanguages() {
  const model = state.config.models[elements.model.value];
  const voice = state.config.voices[elements.voice.value];
  const previous = elements.language.value;
  const languages = isCloneMode()
    ? model.languages
    : voice.languages.filter((code) => model.languages.includes(code));
  elements.language.innerHTML = languages
    .map((code) => `<option value="${code}">${state.config.languages[code]}</option>`)
    .join("");
  elements.language.value = languages.includes(previous)
    ? previous
    : (languages.includes("en") ? "en" : languages[0]);
  const advancedDisabled = !isCloneMode() || elements.model.value !== "multilingual-v3";
  $("#exaggeration").disabled = advancedDisabled;
  $("#cfg-weight").disabled = advancedDisabled;
}

function renderVoiceMode() {
  let voice = state.config.voices[elements.voice.value];
  if (
    elements.translateMode.checked
    && !["chatterbox", "chatterbox-default"].includes(voice.engine)
  ) {
    elements.voice.value = "global";
    voice = state.config.voices.global;
  }
  const cloning = isCloneMode();
  elements.voiceDescription.textContent = `${voice.description} · ${voice.accent}`;
  elements.cloneControls.classList.toggle("hidden", !cloning);
  elements.presetReady.classList.toggle("hidden", cloning);
  $("#model-control").classList.toggle("hidden", !cloning || elements.translateMode.checked);
  $("#advanced-controls").classList.toggle("hidden", !cloning);
  if (elements.translateMode.checked) elements.model.value = "multilingual-v3";
  renderLanguages();
}

async function loadConfig() {
  const [configResponse, healthResponse] = await Promise.all([fetch("/api/config"), fetch("/api/health")]);
  state.config = await configResponse.json();
  const health = await healthResponse.json();
  await initAuth();
  elements.voice.innerHTML = Object.entries(state.config.voices)
    .map(([value, voice]) => `<option value="${value}">${voice.label} — ${voice.accent}</option>`)
    .join("");
  elements.voice.value = "heart";
  elements.model.innerHTML = Object.entries(state.config.models)
    .map(([value, model]) => `<option value="${value}">${model.label}</option>`)
    .join("");
  elements.model.value = health.device === "cpu" ? "nano" : "multilingual-v3";
  elements.sourceLanguage.innerHTML = [
    '<option value="auto">Auto-detect</option>',
    ...state.config.translation.source_languages.map(
      (code) => `<option value="${code}">${languageName(code)}</option>`,
    ),
  ].join("");
  elements.targetLanguages.innerHTML = state.config.translation.target_languages
    .map((code) => `
      <label class="target-language">
        <input type="checkbox" value="${code}" />
        <span>${state.config.languages[code]}</span>
      </label>`)
    .join("");
  updateTargetSelection();
  renderVoiceMode();
  elements.script.maxLength = state.config.limits.max_text_chars;
  $("#char-limit").textContent = state.config.limits.max_text_chars.toLocaleString();
  $("#runtime-label").textContent = health.engine === "mock" ? "Preview engine" : "Secure voice engine";
  $("#runtime-detail").textContent = `${health.worker_mode} · ${health.device}`;
  await loadAccount();
}

async function toggleRecording() {
  if (state.recorder?.state === "recording") {
    state.recorder.stop();
    return;
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    toast("Audio recording is not supported in this browser.", true);
    return;
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
      ? "audio/webm;codecs=opus"
      : "audio/webm";
    state.recordedChunks = [];
    state.recorder = new MediaRecorder(stream, { mimeType });
    state.recorder.ondataavailable = (event) => {
      if (event.data.size) state.recordedChunks.push(event.data);
    };
    state.recorder.onstop = () => {
      clearInterval(state.timer);
      const blob = new Blob(state.recordedChunks, { type: mimeType });
      setFile(new File([blob], `voice-sample-${Date.now()}.webm`, { type: mimeType }));
      stream.getTracks().forEach((track) => track.stop());
      elements.record.classList.remove("recording");
      elements.recordLabel.textContent = "Record another sample";
    };
    state.seconds = 0;
    elements.recordTime.textContent = "00:00";
    elements.record.classList.add("recording");
    elements.recordLabel.textContent = "Stop recording";
    state.recorder.start();
    state.timer = setInterval(() => {
      state.seconds += 1;
      elements.recordTime.textContent = formatTime(state.seconds);
      if (state.seconds >= 30) state.recorder.stop();
    }, 1000);
  } catch {
    toast("Microphone access was not available. You can upload a clip instead.", true);
  }
}

function setGenerating(job) {
  elements.result.classList.remove("hidden");
  elements.player.classList.add("hidden");
  elements.progressTrack.classList.remove("hidden");
  elements.resultTitle.textContent = job.stage || "Generating…";
  elements.resultMessage.textContent = "The first run may take a few minutes while model weights download.";
  elements.progress.style.width = `${job.progress || 0}%`;
  elements.submit.disabled = true;
  elements.result.scrollIntoView({ behavior: "smooth", block: "center" });
}

function drawWaveform(buffer) {
  const canvas = elements.waveform;
  const context = canvas.getContext("2d");
  const ratio = window.devicePixelRatio || 1;
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  canvas.width = width * ratio;
  canvas.height = height * ratio;
  context.scale(ratio, ratio);
  context.clearRect(0, 0, width, height);
  const data = buffer.getChannelData(0);
  const bars = Math.max(40, Math.floor(width / 5));
  const step = Math.floor(data.length / bars);
  context.fillStyle = "#596056";
  for (let i = 0; i < bars; i += 1) {
    let sum = 0;
    for (let j = 0; j < step; j += 1) sum += Math.abs(data[i * step + j] || 0);
    const amplitude = Math.max(3, Math.min(height * 0.84, (sum / step) * height * 3.6));
    const x = i * (width / bars);
    context.fillRect(x, (height - amplitude) / 2, 2, amplitude);
  }
}

async function prepareAudio(job, requestedLanguage = null) {
  elements.player.classList.remove("hidden");
  elements.progressTrack.classList.add("hidden");
  try {
    const outputs = job.outputs || [];
    const language = requestedLanguage || outputs[0]?.language || null;
    elements.outputLanguageControl.classList.toggle("hidden", outputs.length < 2);
    if (outputs.length) {
      elements.outputLanguage.innerHTML = outputs
        .map((output) => `<option value="${output.language}">${escapeHtml(output.language_label)}</option>`)
        .join("");
      elements.outputLanguage.value = language;
    }
    const access = await getAudioAccess(job.id, false, language);
    elements.audio.src = access.url;
    elements.audio.load();
    elements.download.dataset.jobId = job.id;
    elements.download.dataset.language = language || "";
    elements.download.href = "#";
    elements.download.download = access.download_name || job.download_name || "voiceover.wav";
  } catch (error) {
    toast(error.message, true);
  }
}

async function getAudioAccess(jobId, download = false, language = null) {
  const parameters = new URLSearchParams();
  if (download) parameters.set("download", "true");
  if (language) parameters.set("language", language);
  const query = parameters.toString();
  const response = await apiFetch(`/api/jobs/${jobId}/audio-url${query ? `?${query}` : ""}`);
  if (!response.ok) throw new Error(download
    ? "Could not prepare this download."
    : "Could not prepare this voiceover for playback.");
  return response.json();
}

async function startDownload(jobId, language = null) {
  const access = await getAudioAccess(jobId, true, language);
  const anchor = document.createElement("a");
  anchor.href = access.url;
  anchor.download = access.download_name || `ai-voice-${jobId.slice(0, 8)}.wav`;
  anchor.rel = "noopener";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
}

async function pollJob(jobId) {
  clearTimeout(state.pollTimer);
  try {
    const response = await apiFetch(`/api/jobs/${jobId}`);
    if (!response.ok) throw new Error("Could not read generation status");
    const job = await response.json();
    state.currentJob = job;
    elements.resultTitle.textContent = job.stage;
    elements.resultMessage.textContent = job.status === "processing"
      ? "Your script is being rendered locally. You can leave this tab open."
      : elements.resultMessage.textContent;
    elements.progress.style.width = `${job.progress || 0}%`;
    if (job.status === "completed") {
      const outputCount = job.outputs?.length || 1;
      elements.resultTitle.textContent = outputCount > 1 ? "All voiceovers ready" : "Voiceover ready";
      elements.resultMessage.textContent = outputCount > 1
        ? `${outputCount} translated, watermarked voiceovers are ready to play or download.`
        : "Generated securely and watermarked for provenance.";
      elements.resultTime.textContent = outputCount > 1
        ? `${outputCount} languages · ${job.credits.toLocaleString()} credits`
        : `${job.characters.toLocaleString()} characters`;
      elements.submit.disabled = false;
      await prepareAudio(job);
      await loadHistory();
      await loadAccount();
      toast("Your voiceover is ready.");
      return;
    }
    if (job.status === "failed") {
      elements.resultTitle.textContent = "Generation failed";
      elements.resultMessage.textContent = job.error || "Something went wrong.";
      elements.progress.style.width = "100%";
      elements.progress.style.background = "var(--danger)";
      elements.submit.disabled = false;
      await loadAccount();
      toast(job.error || "Generation failed.", true);
      return;
    }
    state.pollTimer = setTimeout(() => pollJob(jobId), 1400);
  } catch (error) {
    elements.submit.disabled = false;
    toast(error.message, true);
  }
}

async function submitGeneration(event) {
  event.preventDefault();
  const cloning = isCloneMode();
  const translating = elements.translateMode.checked;
  const targets = selectedTargetLanguages();
  if (cloning && !state.file) return toast("Add or record a reference voice first.", true);
  if (!elements.script.value.trim()) return toast("Write a script to generate.", true);
  if (cloning && !$("#consent").checked) return toast("Please confirm the speaker has consented.", true);
  if (translating && !targets.length) return toast("Choose at least one output language.", true);

  const body = new FormData();
  if (cloning) body.append("reference", state.file);
  body.append("text", elements.script.value.trim());
  body.append("voice", elements.voice.value);
  body.append("model", elements.model.value);
  body.append("language", elements.language.value);
  body.append("exaggeration", $("#exaggeration").value);
  body.append("cfg_weight", $("#cfg-weight").value);
  body.append("temperature", $("#temperature").value);
  body.append("consent", cloning ? "true" : "false");
  if (translating) {
    body.append("source_language", elements.sourceLanguage.value);
    body.append("target_languages", targets.join(","));
  }
  elements.submit.disabled = true;
  elements.result.classList.remove("hidden");
  elements.resultTitle.textContent = translating
    ? "Preparing translations"
    : cloning
    ? "Preparing reference audio"
    : "Preparing your voice";
  elements.resultMessage.textContent = cloning
    ? "Cleaning and validating your voice sample…"
    : `Loading ${state.config.voices[elements.voice.value].label}…`;
  elements.progress.style.width = "3%";
  elements.player.classList.add("hidden");

  try {
    const endpoint = translating ? "/api/generate-multilingual" : "/api/generate";
    const response = await apiFetch(endpoint, { method: "POST", body });
    const payload = await response.json();
    const detail = typeof payload.detail === "object" ? payload.detail.message : payload.detail;
    if (!response.ok) throw new Error(detail || "Could not start generation");
    state.currentJob = payload;
    setGenerating(payload);
    pollJob(payload.id);
  } catch (error) {
    elements.submit.disabled = false;
    elements.resultTitle.textContent = "Could not start";
    elements.resultMessage.textContent = error.message;
    toast(error.message, true);
  }
}

async function loadHistory() {
  const response = await apiFetch("/api/jobs");
  if (!response.ok) return;
  const jobs = await response.json();
  $("#history-count").textContent = jobs.length;
  const container = $("#history-list");
  if (!jobs.length) {
    container.innerHTML = '<div class="empty-state">No voiceovers yet. Your completed generations will appear here.</div>';
    return;
  }
  container.innerHTML = jobs.map((job) => {
    const outputs = job.outputs?.length
      ? job.outputs
      : [{ language: job.language, language_label: state.config.languages[job.language] }];
    const languageSummary = job.outputs?.length
      ? `${job.outputs.length} languages`
      : (job.language || "").toUpperCase();
    const outputActions = job.audio_url ? outputs.map((output) => `
      <div class="history-output">
        <b>${escapeHtml(output.language_label || languageName(output.language))}</b>
        <button type="button" class="history-play" data-job-id="${job.id}" data-language="${output.language}">▶ Play</button>
        <button type="button" class="history-download" data-job-id="${job.id}" data-language="${output.language}">Download ↓</button>
        <audio class="history-audio" data-language="${output.language}" preload="none"></audio>
      </div>`).join("") : "";
    return `
      <article class="history-item">
        <div class="history-icon">♪</div>
        <div class="history-copy">
          <strong>${escapeHtml(job.text_preview)}</strong>
          <span>${new Date(job.created_at).toLocaleString()} · ${escapeHtml(job.voice_label || "Cloned voice")} · ${languageSummary}</span>
        </div>
        <div class="history-actions">
          <span class="history-status">${job.status}</span>
          ${outputActions}
        </div>
      </article>`;
  }).join("");
}

function escapeHtml(value) {
  const node = document.createElement("span");
  node.textContent = value;
  return node.innerHTML;
}

function switchView(view) {
  $$(".view").forEach((element) => element.classList.remove("active"));
  $$(".nav-item").forEach((element) => element.classList.toggle("active", element.dataset.view === view));
  $(`#${view}-view`).classList.add("active");
  $(".sidebar").classList.remove("open");
  if (view === "history") loadHistory();
}

function bindEvents() {
  $("#auth-form").addEventListener("submit", (event) => {
    event.preventDefault();
    submitAuth(false);
  });
  $("#signup-button").addEventListener("click", () => submitAuth(true));
  $("#signout-button").addEventListener("click", async () => {
    await state.supabase?.auth.signOut();
    state.session = null;
    $("#auth-overlay").classList.remove("hidden");
    $("#signout-button").classList.add("hidden");
  });
  $("#history-list").addEventListener("click", async (event) => {
    const button = event.target.closest(".history-play, .history-download");
    if (!button) return;
    try {
      if (button.classList.contains("history-download")) {
        button.disabled = true;
        await startDownload(button.dataset.jobId, button.dataset.language || null);
        button.disabled = false;
        return;
      }
      const audio = button.closest(".history-output").querySelector(".history-audio");
      if (!audio.src) {
        const access = await getAudioAccess(
          button.dataset.jobId,
          false,
          button.dataset.language || null,
        );
        audio.src = access.url;
        audio.load();
      }
      if (audio.paused) {
        document.querySelectorAll(".history-audio").forEach((item) => {
          if (item !== audio) item.pause();
        });
        await audio.play();
        button.textContent = "❚❚ Pause";
        audio.addEventListener("pause", () => { button.textContent = "▶ Play"; }, { once: true });
      } else {
        audio.pause();
      }
    } catch (error) {
      button.disabled = false;
      toast(error.message, true);
    }
  });
  elements.drop.addEventListener("click", () => elements.input.click());
  elements.input.addEventListener("change", () => setFile(elements.input.files[0]));
  $("#remove-file").addEventListener("click", clearFile);
  ["dragenter", "dragover"].forEach((name) => elements.drop.addEventListener(name, (event) => {
    event.preventDefault();
    elements.drop.classList.add("dragover");
  }));
  ["dragleave", "drop"].forEach((name) => elements.drop.addEventListener(name, (event) => {
    event.preventDefault();
    elements.drop.classList.remove("dragover");
  }));
  elements.drop.addEventListener("drop", (event) => setFile(event.dataTransfer.files[0]));
  elements.record.addEventListener("click", toggleRecording);
  elements.script.addEventListener("input", updateScriptMeta);
  elements.translateMode.addEventListener("change", renderTranslationMode);
  elements.targetLanguages.addEventListener("change", (event) => {
    if (event.target.matches("input[type='checkbox']")) updateTargetSelection(event.target);
  });
  $("#sample-script").addEventListener("click", () => {
    elements.script.value = "There are moments when the world grows quiet enough for us to hear what matters. Not the noise, not the rush—just the steady rhythm of a story waiting to be told.";
    updateScriptMeta();
  });
  elements.model.addEventListener("change", renderLanguages);
  elements.voice.addEventListener("change", renderVoiceMode);
  elements.form.addEventListener("submit", submitGeneration);
  $$(".nav-item").forEach((button) => button.addEventListener("click", () => switchView(button.dataset.view)));
  $(".mobile-menu").addEventListener("click", () => $(".sidebar").classList.toggle("open"));
  [["#exaggeration", "#exaggeration-value", (v) => `${Math.round(v * 100)}%`],
   ["#cfg-weight", "#cfg-value", (v) => `${Math.round(v * 100)}%`],
   ["#temperature", "#temperature-value", (v) => Number(v).toFixed(1)]].forEach(([input, output, format]) => {
    $(input).addEventListener("input", (event) => { $(output).value = format(event.target.value); });
  });
  elements.play.addEventListener("click", () => {
    if (elements.audio.paused) elements.audio.play(); else elements.audio.pause();
  });
  elements.audio.addEventListener("play", () => { elements.play.textContent = "❚❚"; });
  elements.audio.addEventListener("pause", () => { elements.play.textContent = "▶"; });
  elements.audio.addEventListener("timeupdate", () => {
    elements.playerTime.textContent = `${formatTime(elements.audio.currentTime)} / ${formatTime(elements.audio.duration)}`;
  });
  elements.outputLanguage.addEventListener("change", async () => {
    if (!state.currentJob) return;
    elements.audio.pause();
    elements.playerTime.textContent = "00:00";
    await prepareAudio(state.currentJob, elements.outputLanguage.value);
  });
  elements.download.addEventListener("click", async (event) => {
    event.preventDefault();
    const jobId = elements.download.dataset.jobId;
    if (!jobId) return;
    try {
      await startDownload(jobId, elements.download.dataset.language || null);
    } catch (error) {
      toast(error.message, true);
    }
  });
}

async function init() {
  bindEvents();
  updateScriptMeta();
  try {
    await loadConfig();
    if (state.config.auth.mode !== "supabase" || state.session) await loadHistory();
  } catch (error) {
    if (error.message !== "Sign in to continue") {
      $("#runtime-detail").textContent = "Server unavailable";
      toast("AI Voice HQ could not reach its service.", true);
    }
  }
}

init();


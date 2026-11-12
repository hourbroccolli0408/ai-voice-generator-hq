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
  billingCycle: "annual",
  paddleReady: false,
  projects: [],
  savedVoices: [],
  savedVoicePreview: null,
  historyProjectId: null,
  account: null,
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const publicSamplePlayer = new Audio();
publicSamplePlayer.preload = "metadata";
let activePublicSample = null;

const DELIVERY_PRESETS = {
  natural: { exaggeration: .5, cfg: .5, temperature: .8, speed: 1 },
  warm: { exaggeration: .6, cfg: .45, temperature: .75, speed: .9 },
  energetic: { exaggeration: .78, cfg: .35, temperature: 1, speed: 1.1 },
  dramatic: { exaggeration: .9, cfg: .3, temperature: .9, speed: .9 },
  calm: { exaggeration: .3, cfg: .65, temperature: .65, speed: .9 },
};

const MARKETING_PRESET_COPY = {
  natural: "Natural keeps the pacing balanced with a clear, dependable delivery.",
  warm: "Warm slows the pace slightly and adds a more reassuring expression.",
  energetic: "Energetic adds quicker pacing, stronger expression and wider variation.",
  calm: "Calm uses measured pacing, lighter expression and controlled variation.",
};

function resetPublicSampleButton(button) {
  if (!button) return;
  button.classList.remove("is-playing");
  button.setAttribute("aria-pressed", "false");
  const icon = button.querySelector(".sample-play-icon");
  const label = button.querySelector("[data-sample-state]");
  if (icon) icon.textContent = "▶";
  if (label) label.textContent = "Play sample";
}

function bindPublicSamples() {
  $$(".public-sample-trigger").forEach((button) => {
    button.addEventListener("click", async () => {
      if (activePublicSample === button) {
        if (!publicSamplePlayer.paused) {
          publicSamplePlayer.pause();
          return;
        }
      } else {
        resetPublicSampleButton(activePublicSample);
        activePublicSample = button;
        publicSamplePlayer.src = button.dataset.sampleSrc;
        publicSamplePlayer.currentTime = 0;
      }

      button.classList.add("is-playing");
      button.setAttribute("aria-pressed", "true");
      const icon = button.querySelector(".sample-play-icon");
      const label = button.querySelector("[data-sample-state]");
      if (icon) icon.textContent = "❚❚";
      if (label) label.textContent = "Pause";
      try {
        await publicSamplePlayer.play();
      } catch (error) {
        resetPublicSampleButton(button);
        activePublicSample = null;
        toast("This sample could not be played. Please try again.", true);
      }
    });
  });
  publicSamplePlayer.addEventListener("pause", () => resetPublicSampleButton(activePublicSample));
  publicSamplePlayer.addEventListener("ended", () => {
    resetPublicSampleButton(activePublicSample);
    activePublicSample = null;
  });
}

function presetLabel(name) {
  return `${name.charAt(0).toUpperCase()}${name.slice(1)}`;
}

function renderMarketingPreset(name) {
  const preset = DELIVERY_PRESETS[name];
  if (!preset || !MARKETING_PRESET_COPY[name]) return;
  const speedWidth = Math.round(((preset.speed - .75) / .5) * 100);
  const expression = Math.round(preset.exaggeration * 100);
  const variationWidth = Math.round(preset.temperature * 80);
  $("#demo-speed").textContent = `${preset.speed.toFixed(1)}×`;
  $("#demo-expression").textContent = `${expression}%`;
  $("#demo-variation").textContent = preset.temperature.toFixed(2).replace(/0$/, "");
  $("#demo-speed-meter").style.width = `${speedWidth}%`;
  $("#demo-expression-meter").style.width = `${expression}%`;
  $("#demo-variation-meter").style.width = `${variationWidth}%`;
  $("#control-summary").textContent = MARKETING_PRESET_COPY[name];
  const callToAction = $("#control-cta");
  callToAction.href = `/studio?preset=${name}`;
  callToAction.firstChild.textContent = `Use ${presetLabel(name)} in Studio `;
  $$("[data-marketing-preset]").forEach((button) => {
    const active = button.dataset.marketingPreset === name;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
}

function bindMarketingPresets() {
  $$("[data-marketing-preset]").forEach((button) => {
    button.addEventListener("click", () => renderMarketingPreset(button.dataset.marketingPreset));
  });
}

const BILLING_DISPLAY = {
  creator: {
    monthly: { price: "$6", period: "/month", credits: "100,000 credits every month", minutes: "About 130 minutes" },
    annual: { price: "$4", period: "/mo · $48 yearly", credits: "1.2M credits issued annually", minutes: "About 1,600 minutes" },
  },
  pro: {
    monthly: { price: "$12", period: "/month", credits: "400,000 credits every month", minutes: "About 530 minutes" },
    annual: { price: "$10", period: "/mo · $120 yearly", credits: "4.8M credits issued annually", minutes: "About 6,400 minutes" },
  },
  studio: {
    monthly: { price: "$39", period: "/month", credits: "1.5M credits every month", minutes: "About 2,000 minutes" },
    annual: { price: "$32.50", period: "/mo · $390 yearly", credits: "18M credits issued annually", minutes: "About 24,000 minutes" },
  },
};

function renderBillingCycle(cycle) {
  state.billingCycle = cycle;
  $$('[data-billing-cycle]').forEach((button) => {
    const active = button.dataset.billingCycle === cycle;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  $$('[data-paid-plan]').forEach((card) => {
    const display = BILLING_DISPLAY[card.dataset.paidPlan]?.[cycle];
    if (!display) return;
    card.querySelector('[data-plan-price]').textContent = display.price;
    card.querySelector('[data-plan-period]').textContent = display.period;
    card.querySelector('[data-plan-credits]').textContent = display.credits;
    const minutes = card.querySelector('[data-plan-credits] + li');
    if (minutes) minutes.textContent = display.minutes;
  });
}

function initializeBilling() {
  const billing = state.config?.billing;
  const status = $("#billing-status");
  if (!billing?.enabled) {
    if (status) status.textContent = "Secure paid checkout is installed in test mode and will open after the Paddle account and plan IDs are verified.";
    return;
  }
  if (!window.Paddle || !billing.client_token) {
    if (status) status.textContent = "Secure checkout is temporarily unavailable. Free beta accounts still work normally.";
    return;
  }
  if (billing.environment === "sandbox") window.Paddle.Environment.set("sandbox");
  window.Paddle.Initialize({
    token: billing.client_token,
    eventCallback: (event) => {
      if (event.name === "checkout.completed") {
        sessionStorage.removeItem("pendingBillingPlan");
        toast("Test payment completed. Your credits will appear after secure verification.");
        setTimeout(loadAccount, 1800);
      }
    },
  });
  state.paddleReady = true;
  if (status) {
    status.textContent = billing.environment === "sandbox"
      ? "Paddle sandbox is connected. Checkout uses test payments only—no real money can be charged."
      : "Secure checkout, tax calculation, invoices and subscription management are provided by Paddle.";
  }
}

function openCheckout(basePlan) {
  const planCode = `${basePlan}_${state.billingCycle}`;
  if (!state.session) {
    sessionStorage.setItem("pendingBillingPlan", planCode);
    window.location.assign("/studio");
    return;
  }
  const billing = state.config?.billing;
  const plan = billing?.plans?.[planCode];
  if (!billing?.enabled || !state.paddleReady || !plan?.price_id) {
    toast("Paid checkout is still in secure test setup. Your free beta access remains available.", true);
    return;
  }
  window.Paddle.Checkout.open({
    items: [{ priceId: plan.price_id, quantity: 1 }],
    customData: { user_id: state.session.user.id, plan_code: planCode },
    customer: { email: state.session.user.email },
    settings: { displayMode: "overlay", theme: "dark", locale: "en" },
  });
}

function maybeOpenPendingCheckout() {
  if (!state.session || !state.config?.billing) return;
  const pending = sessionStorage.getItem("pendingBillingPlan");
  if (!pending) return;
  const [basePlan, cycle] = pending.split("_");
  if (!BILLING_DISPLAY[basePlan]?.[cycle]) {
    sessionStorage.removeItem("pendingBillingPlan");
    return;
  }
  renderBillingCycle(cycle);
  setTimeout(() => openCheckout(basePlan), 250);
}

function applyStudioPreset(name) {
  const preset = DELIVERY_PRESETS[name];
  if (!preset) return;
  $("#exaggeration").value = preset.exaggeration;
  $("#cfg-weight").value = preset.cfg;
  $("#temperature").value = preset.temperature;
  $("#speed").value = String(preset.speed);
  $("#exaggeration-value").value = `${Math.round(preset.exaggeration * 100)}%`;
  $("#cfg-value").value = `${Math.round(preset.cfg * 100)}%`;
  $("#temperature-value").value = preset.temperature.toFixed(1);
  $$(".delivery-preset").forEach((button) => {
    const active = button.dataset.preset === name;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
}

function renderRoute() {
  const path = window.location.pathname.replace(/\/+$/, "") || "/";
  const isStudio = path === "/studio";
  const route = path === "/pricing" ? "pricing"
    : path === "/changelog" ? "changelog"
    : path === "/faq" ? "faq"
    : path === "/about" ? "about"
    : path === "/privacy" ? "privacy"
    : path === "/terms" ? "terms"
    : "home";
  $("#marketing-site").classList.toggle("hidden", isStudio);
  $("#app-shell").classList.toggle("hidden", !isStudio);
  $$(".marketing-page").forEach((page) => {
    page.classList.toggle("hidden", isStudio || page.dataset.route !== route);
  });
  $$(".marketing-links a").forEach((link) => {
    const isCurrent = link.pathname === window.location.pathname && window.location.pathname !== "/";
    if (isCurrent) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  const requiresAuth = state.config?.auth?.mode === "supabase";
  $("#auth-overlay").classList.toggle("hidden", !isStudio || !requiresAuth || Boolean(state.session));
  const titles = {
    home: "AI Voice HQ — Create voices people remember",
    pricing: "Pricing — AI Voice HQ",
    changelog: "Changelog — AI Voice HQ",
    faq: "FAQ — AI Voice HQ",
    about: "About — AI Voice HQ",
    privacy: "Privacy — AI Voice HQ",
    terms: "Terms — AI Voice HQ",
  };
  document.title = isStudio ? "Voiceover Studio — AI Voice HQ" : titles[route];
  const descriptions = {
    home: "Create natural AI voiceovers with 29 ready voices, consent-first voice cloning, multilingual delivery and transparent character pricing.",
    pricing: "Compare transparent AI Voice HQ plans, credits and founder pricing for creators, podcasts and production teams.",
    changelog: "Read every meaningful AI Voice HQ product release, including private reusable voices, creator projects and multilingual voiceover tools.",
    faq: "Answers about AI Voice HQ voices, cloning consent, credits, translation, privacy, billing, downloads and commercial use.",
    about: "Learn why AI Voice HQ is building a focused, consent-first AI voice studio for creators and production teams.",
    privacy: "Learn how AI Voice HQ handles accounts, voice references, saved voices, payments and private generation data.",
    terms: "Read the AI Voice HQ terms for authorized voice cloning, beta service, user content and prohibited activity.",
  };
  const pageDescription = descriptions[route] || descriptions.home;
  document.querySelector('meta[name="description"]').content = pageDescription;
  document.querySelector('meta[property="og:description"]').content = pageDescription;
  // Canonical and og:url are set by the server before JavaScript runs.
  document.querySelector('meta[property="og:title"]').content = document.title;
  if (!isStudio) window.scrollTo({ top: 0, behavior: "auto" });
}

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
  voiceSearch: $("#voice-search"),
  voiceAccent: $("#voice-accent"),
  voiceGender: $("#voice-gender"),
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
  if (state.config.auth.mode !== "supabase") {
    renderRoute();
    return;
  }
  if (!window.supabase || !state.config.auth.supabase_url || !state.config.auth.supabase_anon_key) {
    throw new Error("Authentication is not configured correctly");
  }
  state.supabase = window.supabase.createClient(
    state.config.auth.supabase_url,
    state.config.auth.supabase_anon_key,
  );
  const { data } = await state.supabase.auth.getSession();
  state.session = data.session;
  $("#signout-button").classList.toggle("hidden", !state.session);
  renderRoute();
  state.supabase.auth.onAuthStateChange((_event, session) => {
    state.session = session;
    $("#signout-button").classList.toggle("hidden", !session);
    renderRoute();
    if (session) {
      loadAccount();
      loadHistory();
      loadProjects();
      loadSavedVoices();
      maybeOpenPendingCheckout();
    } else {
      state.savedVoices = [];
      renderSavedVoiceLibrary();
    }
  });
}

async function submitAuth(createAccount = false) {
  const form = $("#auth-form");
  if (!form.reportValidity()) return;

  const email = $("#auth-email").value.trim();
  const password = $("#auth-password").value;
  const message = $("#auth-message");
  message.textContent = "";
  message.classList.remove("success");
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
    message.classList.add("success");
    return;
  }
  state.session = data.session;
  $("#signout-button").classList.remove("hidden");
  renderRoute();
  await loadAccount();
  await loadHistory();
  await loadProjects();
  await loadSavedVoices();
  maybeOpenPendingCheckout();
}

async function loadAccount() {
  const response = await apiFetch("/api/account");
  if (!response.ok) return;
  const account = await response.json();
  state.account = account;
  $("#credit-balance").textContent = account.credits.toLocaleString();
  $("#profile-credits").textContent = account.credits.toLocaleString();
  const email = state.session?.user?.email || "Local preview account";
  const displayName = email.includes("@") ? email.split("@")[0] : "Your account";
  const initial = displayName.charAt(0).toUpperCase() || "A";
  $$('[data-profile-initial]').forEach((element) => { element.textContent = initial; });
  $$('[data-profile-name]').forEach((element) => { element.textContent = displayName; });
  $("#profile-email").textContent = email;
  const planName = account.subscription?.plan_name || "Free beta";
  $$('[data-profile-plan]').forEach((element) => { element.textContent = planName; });
  $("#billing-action-label").textContent = account.subscription ? "Manage billing" : "View plans";
}

async function loadProjects() {
  const response = await apiFetch("/api/projects");
  if (!response.ok) return;
  state.projects = await response.json();
  const select = $("#task-project");
  const selected = select.value;
  select.innerHTML = '<option value="">Unfiled</option>' + state.projects
    .map((project) => `<option value="${project.id}">${escapeHtml(project.name)}</option>`)
    .join("");
  if ([...select.options].some((option) => option.value === selected)) select.value = selected;
  renderProjectList();
}

function renderProjectList() {
  const list = $("#project-list");
  list.innerHTML = state.projects.map((project) => `
    <button type="button" class="project-item ${state.historyProjectId === project.id ? "active" : ""}" data-project-id="${project.id}">
      <span>▱</span><b>${escapeHtml(project.name)}</b><small>${project.job_count}</small>
    </button>`).join("");
  $('[data-project-filter="all"]').classList.toggle("active", !state.historyProjectId);
}

async function createProject(event) {
  event.preventDefault();
  const input = $("#new-project-name");
  const name = input.value.trim();
  if (!name) return;
  const response = await apiFetch("/api/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  const project = await response.json();
  if (!response.ok) return toast(project.detail || "Could not create that project", true);
  input.value = "";
  $("#new-project-form").classList.add("hidden");
  await loadProjects();
  $("#task-project").value = project.id;
  toast(`${project.name} is ready.`);
}

async function loadSavedVoices({ refreshPicker = true } = {}) {
  if (state.config?.auth?.mode === "supabase" && !state.session) {
    state.savedVoices = [];
    renderSavedVoiceLibrary();
    return;
  }
  const response = await apiFetch("/api/voices");
  if (!response.ok) return;
  state.savedVoices = await response.json();
  renderSavedVoiceLibrary();
  if (refreshPicker && state.config && elements.model.options.length) {
    refreshVoiceFilters();
    filterVoices();
  }
}

function renderSavedVoiceLibrary() {
  const list = $("#voice-library-list");
  if (!list) return;
  if (!state.savedVoices.length) {
    list.innerHTML = `
      <div class="voice-library-empty">
        <span>◌</span><h3>No saved voices yet</h3>
        <p>Create an authorized voice in the Studio and switch on Save to My Voices.</p>
      </div>`;
    return;
  }
  list.innerHTML = state.savedVoices.map((voice) => {
    const tags = (voice.use_tags || []).map((tag) => `<span>${escapeHtml(tag)}</span>`).join("");
    const used = voice.last_used_at
      ? `Used ${new Date(voice.last_used_at).toLocaleDateString()}`
      : "Ready to use";
    return `
      <article class="saved-voice-card" data-saved-voice-id="${voice.id}">
        <div class="saved-voice-mark">${escapeHtml(voice.name.charAt(0).toUpperCase())}</div>
        <div class="saved-voice-copy">
          <strong>${escapeHtml(voice.name)}</strong>
          <small>${escapeHtml(voice.accent || "Custom")} · ${escapeHtml(languageName(voice.language))} · ${escapeHtml(voice.default_preset)} delivery</small>
          <div class="saved-voice-tags">${tags || "<span>Authorized clone</span>"}</div>
          <p>Consent recorded · ${used}</p>
        </div>
        <div class="saved-voice-actions">
          <button type="button" data-voice-action="use">Use voice</button>
          <button type="button" data-voice-action="preview">▶ Preview sample</button>
          <button type="button" data-voice-action="rename">Rename</button>
          <button type="button" data-voice-action="replace">Replace sample</button>
          <button type="button" class="danger" data-voice-action="delete">Delete</button>
        </div>
      </article>`;
  }).join("");
}

function openVoiceLibrary() {
  renderSavedVoiceLibrary();
  $("#profile-menu").classList.add("hidden");
  $("#voice-library-modal").classList.remove("hidden");
  document.body.classList.add("modal-open");
}

function closeVoiceLibrary() {
  state.savedVoicePreview?.pause();
  $("#voice-library-modal").classList.add("hidden");
  document.body.classList.remove("modal-open");
}

async function createSavedVoiceFromForm() {
  const name = $("#saved-voice-name").value.trim();
  if (!name) throw new Error("Give this saved voice a name.");
  const body = new FormData();
  body.append("reference", state.file);
  body.append("name", name);
  body.append("accent", $("#saved-voice-accent").value.trim() || "Custom");
  body.append("language", $("#saved-voice-language").value || "en");
  body.append("use_tags", $("#saved-voice-tags").value.trim());
  body.append("default_preset", $("#saved-voice-preset").value);
  body.append("consent", "true");
  const response = await apiFetch("/api/voices", { method: "POST", body });
  const result = await response.json();
  if (!response.ok) throw new Error(result.detail || "Could not save this voice");
  await loadSavedVoices({ refreshPicker: false });
  refreshVoiceFilters();
  filterVoices();
  elements.voice.value = `saved:${result.id}`;
  clearFile();
  $("#save-voice-toggle").checked = false;
  $("#save-voice-fields").classList.add("hidden");
  renderVoiceMode();
  toast(`${result.name} was saved privately.`);
  return result;
}

async function handleSavedVoiceAction(event) {
  const button = event.target.closest("[data-voice-action]");
  if (!button) return;
  const card = button.closest("[data-saved-voice-id]");
  const voice = state.savedVoices.find((item) => item.id === card?.dataset.savedVoiceId);
  if (!voice) return;
  const action = button.dataset.voiceAction;
  try {
    if (action === "use") {
      closeVoiceLibrary();
      switchView("studio");
      elements.voiceSearch.value = "";
      elements.voiceAccent.value = "";
      elements.voiceGender.value = "";
      filterVoices();
      elements.voice.value = `saved:${voice.id}`;
      applyStudioPreset(voice.default_preset || "natural");
      renderVoiceMode();
      elements.voice.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }
    if (action === "preview") {
      if (state.savedVoicePreview && state.savedVoicePreview.dataset.voiceId === voice.id) {
        if (state.savedVoicePreview.paused) await state.savedVoicePreview.play();
        else state.savedVoicePreview.pause();
        return;
      }
      state.savedVoicePreview?.pause();
      button.disabled = true;
      const response = await apiFetch(voice.preview_url);
      if (!response.ok) throw new Error("Could not load that private sample");
      const objectUrl = URL.createObjectURL(await response.blob());
      const audio = new Audio(objectUrl);
      audio.dataset.voiceId = voice.id;
      state.savedVoicePreview = audio;
      audio.addEventListener("ended", () => {
        button.textContent = "▶ Preview sample";
        URL.revokeObjectURL(objectUrl);
      }, { once: true });
      audio.addEventListener("pause", () => { button.textContent = "▶ Preview sample"; });
      button.textContent = "❚❚ Pause";
      button.disabled = false;
      await audio.play();
      return;
    }
    if (action === "rename") {
      const name = window.prompt("Name this voice", voice.name)?.trim();
      if (!name || name === voice.name) return;
      const response = await apiFetch(`/api/voices/${voice.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || "Could not rename that voice");
      await loadSavedVoices();
      toast("Voice renamed.");
      return;
    }
    if (action === "replace") {
      const confirmed = window.confirm("Confirm that you own this replacement sample or have the speaker's explicit permission to use it.");
      if (!confirmed) return;
      const input = document.createElement("input");
      input.type = "file";
      input.accept = "audio/*,.wav,.mp3,.m4a,.webm,.flac";
      input.addEventListener("change", async () => {
        const file = input.files?.[0];
        if (!file) return;
        const body = new FormData();
        body.append("reference", file);
        body.append("consent", "true");
        button.disabled = true;
        const response = await apiFetch(`/api/voices/${voice.id}/sample`, { method: "PUT", body });
        const result = await response.json();
        button.disabled = false;
        if (!response.ok) return toast(result.detail || "Could not replace that sample", true);
        await loadSavedVoices();
        toast("Voice sample replaced securely.");
      });
      input.click();
      return;
    }
    if (action === "delete") {
      const confirmed = window.confirm(`Permanently delete ${voice.name} and its stored voice sample? This cannot be undone.`);
      if (!confirmed) return;
      button.disabled = true;
      const response = await apiFetch(`/api/voices/${voice.id}`, { method: "DELETE" });
      if (!response.ok) {
        const result = await response.json();
        throw new Error(result.detail || "Could not delete that voice");
      }
      await loadSavedVoices();
      toast(`${voice.name} was permanently deleted.`);
    }
  } catch (error) {
    button.disabled = false;
    toast(error.message, true);
  }
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
  const variations = Number($("#variations").value || 1);
  elements.count.textContent = length.toLocaleString();
  if (elements.translateMode.checked) {
    const targets = selectedTargetLanguages();
    $("#duration-estimate").textContent = (length * targets.length).toLocaleString();
    $("#estimate-label").textContent = "credits for all outputs";
    $("#translation-cost").textContent = targets.length
      ? `${length.toLocaleString()} characters × ${targets.length} languages = ${(length * targets.length).toLocaleString()} credits.`
      : "Choose output languages to see the credit cost.";
  } else {
    $("#duration-estimate").textContent = (length * variations).toLocaleString();
    $("#estimate-label").textContent = variations > 1
      ? `credits for ${variations} takes`
      : "credits";
  }
}

function isCloneMode() {
  const voice = currentVoice();
  return voice?.engine === "chatterbox";
}

function isNewCloneMode() {
  return elements.voice.value === "clone";
}

function selectedSavedVoice() {
  if (!elements.voice.value.startsWith("saved:")) return null;
  const id = elements.voice.value.slice(6);
  return state.savedVoices.find((voice) => voice.id === id) || null;
}

function savedVoiceOption(voice) {
  return {
    label: voice.name,
    description: "Your private, reusable authorized voice",
    accent: voice.accent || "Custom",
    gender: "Custom",
    style: voice.default_preset || "natural",
    use_cases: voice.use_tags || [],
    engine: "chatterbox",
    languages: state.config.models["multilingual-v3"].languages,
    savedVoice: voice,
  };
}

function currentVoice() {
  const saved = selectedSavedVoice();
  return saved ? savedVoiceOption(saved) : state.config.voices[elements.voice.value];
}

function allVoiceEntries() {
  const saved = state.savedVoices.map((voice) => ({
    value: `saved:${voice.id}`,
    voice: savedVoiceOption(voice),
    source: "saved",
  }));
  const house = Object.entries(state.config.voices).map(([value, voice]) => ({
    value,
    voice,
    source: value === "clone" ? "create" : "house",
  }));
  return [...saved, ...house];
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
  $("#takes-control").classList.toggle("hidden", translating);
  if (translating) $("#variations").value = "1";
  elements.submit.querySelector("span").textContent = translating
    ? "Translate & generate"
    : "Generate voiceover";
  if (translating) {
    const voice = currentVoice();
    if (!voice || !["chatterbox", "chatterbox-default"].includes(voice.engine)) {
      elements.voice.value = "global";
    }
    elements.model.value = "multilingual-v3";
  }
  renderVoiceMode();
  updateScriptMeta();
}

function voiceSearchText(voice) {
  return [voice.label, voice.description, voice.accent, voice.gender, voice.style, ...(voice.use_cases || [])]
    .join(" ")
    .toLowerCase();
}

function refreshVoiceFilters() {
  const entries = allVoiceEntries();
  const previousAccent = elements.voiceAccent.value;
  const previousGender = elements.voiceGender.value;
  const accents = [...new Set(entries.map(({ voice }) => voice.accent).filter(Boolean))].sort();
  const genders = [...new Set(entries.map(({ voice }) => voice.gender).filter(Boolean))].sort();
  elements.voiceAccent.innerHTML = '<option value="">All accents</option>'
    + accents.map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join("");
  elements.voiceGender.innerHTML = '<option value="">All voices</option>'
    + genders.map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join("");
  if (accents.includes(previousAccent)) elements.voiceAccent.value = previousAccent;
  if (genders.includes(previousGender)) elements.voiceGender.value = previousGender;
}

function filterVoices() {
  const query = elements.voiceSearch.value.trim().toLowerCase();
  const accent = elements.voiceAccent.value;
  const gender = elements.voiceGender.value;
  const previous = elements.voice.value;
  const matches = allVoiceEntries().filter(({ voice }) => (
    (!query || voiceSearchText(voice).includes(query))
    && (!accent || voice.accent === accent)
    && (!gender || voice.gender === gender)
  ));
  const recent = matches.filter(({ source, voice }) => source === "saved" && voice.savedVoice.last_used_at).slice(0, 3);
  const recentIds = new Set(recent.map(({ voice }) => voice.savedVoice.id));
  const saved = matches.filter(({ source, voice }) => source === "saved" && !recentIds.has(voice.savedVoice.id));
  const create = matches.filter(({ source }) => source === "create");
  const house = matches.filter(({ source }) => source === "house");
  const group = (label, items) => items.length ? `<optgroup label="${label}">${items.map(({ value, voice }) => (
    `<option value="${value}">${escapeHtml(voice.label)} — ${escapeHtml(voice.accent)} · ${escapeHtml(voice.style)}</option>`
  )).join("")}</optgroup>` : "";
  elements.voice.innerHTML = [
    group("Recently Used", recent),
    group("My Voices", saved),
    group("Create a New Voice", create),
    group("AI Voice HQ Voices", house),
  ].join("");
  $("#voice-count").textContent = `${matches.length} available`;
  if (!matches.length) {
    elements.voice.innerHTML = '<option value="">No matching voices</option>';
    elements.voice.disabled = true;
    elements.submit.disabled = true;
    elements.voiceDescription.textContent = "Try clearing one of the voice filters.";
    return;
  }
  elements.voice.disabled = false;
  elements.submit.disabled = false;
  elements.voice.value = matches.some(({ value }) => value === previous) ? previous : matches[0].value;
  renderVoiceMode();
}

function renderLanguages() {
  const model = state.config.models[elements.model.value];
  const voice = currentVoice();
  if (!model || !voice) return;
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
  const advancedDisabled = !["chatterbox", "chatterbox-default"].includes(voice.engine)
    || elements.model.value !== "multilingual-v3";
  $("#exaggeration").disabled = advancedDisabled;
  $("#cfg-weight").disabled = advancedDisabled;
}

function renderVoiceMode() {
  let voice = currentVoice();
  if (!voice) return;
  if (
    elements.translateMode.checked
    && !["chatterbox", "chatterbox-default"].includes(voice.engine)
  ) {
    elements.voice.value = "global";
    voice = state.config.voices.global;
  }
  const cloning = isCloneMode();
  const newClone = isNewCloneMode();
  const savedVoice = selectedSavedVoice();
  elements.voiceDescription.textContent = `${voice.description} · ${voice.gender} · ${(voice.use_cases || []).join(", ")}`;
  elements.cloneControls.classList.toggle("hidden", !newClone);
  elements.presetReady.classList.toggle("hidden", newClone);
  elements.presetReady.querySelector("strong").textContent = savedVoice ? "Saved voice ready" : "Ready to generate";
  elements.presetReady.querySelector("small").textContent = savedVoice
    ? "Private to your account. No new recording needed."
    : "No recording or voice sample needed.";
  $("#model-control").classList.toggle("hidden", !cloning || elements.translateMode.checked);
  const supportsDirection = ["chatterbox", "chatterbox-default"].includes(voice.engine);
  $("#advanced-controls").classList.toggle("hidden", !supportsDirection);
  if (elements.translateMode.checked) elements.model.value = "multilingual-v3";
  renderLanguages();
}

async function loadConfig() {
  const [configResponse, healthResponse] = await Promise.all([fetch("/api/config"), fetch("/api/health")]);
  state.config = await configResponse.json();
  const health = await healthResponse.json();
  await initAuth();
  initializeBilling();
  elements.model.innerHTML = Object.entries(state.config.models)
    .map(([value, model]) => `<option value="${value}">${model.label}</option>`)
    .join("");
  elements.model.value = health.device === "cpu" ? "nano" : "multilingual-v3";
  await loadSavedVoices({ refreshPicker: false });
  refreshVoiceFilters();
  filterVoices();
  if ([...elements.voice.options].some((option) => option.value === "heart")) elements.voice.value = "heart";
  elements.sourceLanguage.innerHTML = [
    '<option value="auto">Auto-detect</option>',
    ...state.config.translation.source_languages.map(
      (code) => `<option value="${code}">${languageName(code)}</option>`,
    ),
  ].join("");
  $("#saved-voice-language").innerHTML = state.config.translation.target_languages
    .map((code) => `<option value="${code}">${escapeHtml(state.config.languages[code])}</option>`)
    .join("");
  $("#saved-voice-language").value = "en";
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
  await loadProjects();
  maybeOpenPendingCheckout();
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

async function prepareAudio(job, requestedLanguage = null, requestedTake = null) {
  elements.player.classList.remove("hidden");
  elements.progressTrack.classList.add("hidden");
  try {
    const outputs = job.outputs || [];
    const takes = job.takes || [];
    const language = requestedLanguage || outputs[0]?.language || null;
    const take = requestedTake || takes[0]?.take || null;
    elements.outputLanguageControl.classList.toggle("hidden", outputs.length < 2 && takes.length < 2);
    if (outputs.length) {
      elements.outputLanguage.innerHTML = outputs
        .map((output) => `<option value="${output.language}">${escapeHtml(output.language_label)}</option>`)
        .join("");
      elements.outputLanguage.value = language;
      elements.outputLanguage.dataset.mode = "language";
      elements.outputLanguageControl.querySelector("span").textContent = "Playing language";
    } else if (takes.length) {
      elements.outputLanguage.innerHTML = takes
        .map((item) => `<option value="${item.take}">${escapeHtml(item.label)}</option>`)
        .join("");
      elements.outputLanguage.value = String(take);
      elements.outputLanguage.dataset.mode = "take";
      elements.outputLanguageControl.querySelector("span").textContent = "Playing version";
    }
    const access = await getAudioAccess(job.id, false, language, take);
    elements.audio.src = access.url;
    elements.audio.load();
    elements.download.dataset.jobId = job.id;
    elements.download.dataset.language = language || "";
    elements.download.dataset.take = take || "";
    elements.download.href = "#";
    elements.download.download = access.download_name || job.download_name || "voiceover.wav";
  } catch (error) {
    toast(error.message, true);
  }
}

async function getAudioAccess(jobId, download = false, language = null, take = null) {
  const parameters = new URLSearchParams();
  if (download) parameters.set("download", "true");
  if (language) parameters.set("language", language);
  if (take) parameters.set("take", take);
  const query = parameters.toString();
  const response = await apiFetch(`/api/jobs/${jobId}/audio-url${query ? `?${query}` : ""}`);
  if (!response.ok) throw new Error(download
    ? "Could not prepare this download."
    : "Could not prepare this voiceover for playback.");
  return response.json();
}

async function startDownload(jobId, language = null, take = null) {
  const access = await getAudioAccess(jobId, true, language, take);
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
      const outputCount = job.outputs?.length || job.takes?.length || 1;
      elements.resultTitle.textContent = outputCount > 1 ? "All versions ready" : "Voiceover ready";
      elements.resultMessage.textContent = outputCount > 1
        ? `${outputCount} watermarked voiceovers are ready to compare or download.`
        : "Generated securely and watermarked for provenance.";
      elements.resultTime.textContent = outputCount > 1
        ? `${outputCount} outputs · ${job.credits.toLocaleString()} credits`
        : `${job.characters.toLocaleString()} characters`;
      elements.submit.disabled = false;
      await prepareAudio(job);
      await loadHistory();
      await loadAccount();
      await loadProjects();
      if (job.saved_voice_id) await loadSavedVoices();
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
  const newClone = isNewCloneMode();
  const translating = elements.translateMode.checked;
  const targets = selectedTargetLanguages();
  if (newClone && !state.file) return toast("Add or record a reference voice first.", true);
  if (!elements.script.value.trim()) return toast("Write a script to generate.", true);
  if (newClone && !$("#consent").checked) return toast("Please confirm the speaker has consented.", true);
  if (translating && !targets.length) return toast("Choose at least one output language.", true);
  const saveRequested = newClone && $("#save-voice-toggle").checked;
  if (saveRequested && !$("#saved-voice-name").value.trim()) {
    return toast("Give this saved voice a name.", true);
  }
  elements.submit.disabled = true;
  elements.result.classList.remove("hidden");
  elements.resultTitle.textContent = translating
    ? "Preparing translations"
    : cloning
    ? "Preparing reference audio"
    : "Preparing your voice";
  elements.resultMessage.textContent = newClone
    ? "Cleaning and validating your voice sample…"
    : `Loading ${currentVoice().label}…`;
  elements.progress.style.width = "3%";
  elements.player.classList.add("hidden");

  try {
    let savedVoice = selectedSavedVoice();
    if (saveRequested) {
      elements.resultTitle.textContent = "Saving your private voice";
      elements.resultMessage.textContent = "Securing the normalized sample and consent record…";
      savedVoice = await createSavedVoiceFromForm();
      applyStudioPreset(savedVoice.default_preset || "natural");
    }
    const body = new FormData();
    if (newClone && !savedVoice) body.append("reference", state.file);
    body.append("text", elements.script.value.trim());
    body.append("voice", savedVoice ? "clone" : elements.voice.value);
    if (savedVoice) body.append("saved_voice_id", savedVoice.id);
    body.append("model", elements.model.value);
    body.append("language", elements.language.value);
    body.append("exaggeration", $("#exaggeration").value);
    body.append("cfg_weight", $("#cfg-weight").value);
    body.append("temperature", $("#temperature").value);
    body.append("speed", $("#speed").value);
    body.append("variations", translating ? "1" : $("#variations").value);
    body.append("consent", newClone ? "true" : "false");
    body.append("title", $("#task-title").value.trim());
    body.append("project_id", $("#task-project").value);
    if (translating) {
      body.append("source_language", elements.sourceLanguage.value);
      body.append("target_languages", targets.join(","));
    }
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
  const activeProject = state.projects.find((project) => project.id === state.historyProjectId);
  const visibleJobs = state.historyProjectId
    ? jobs.filter((job) => job.project_id === state.historyProjectId)
    : jobs;
  $("#history-title").textContent = activeProject?.name || "All voiceovers";
  $("#history-description").textContent = activeProject
    ? `${visibleJobs.length} voiceover${visibleJobs.length === 1 ? "" : "s"} in this project.`
    : "Private to your account.";
  const container = $("#history-list");
  if (!visibleJobs.length) {
    container.innerHTML = `<div class="empty-state">${activeProject ? "No voiceovers in this project yet." : "No voiceovers yet. Your completed generations will appear here."}</div>`;
    return;
  }
  container.innerHTML = visibleJobs.map((job) => {
    const outputs = job.outputs?.length
      ? job.outputs
      : job.takes?.length
      ? job.takes
      : [{ language: job.language, language_label: state.config.languages[job.language] }];
    const languageSummary = job.outputs?.length
      ? `${job.outputs.length} languages`
      : job.takes?.length > 1
      ? `${job.takes.length} takes`
      : (job.language || "").toUpperCase();
    const outputActions = job.audio_url ? outputs.map((output) => `
      <div class="history-output">
        <b>${escapeHtml(output.language_label || output.label || languageName(output.language))}</b>
        <button type="button" class="history-play" data-job-id="${job.id}" data-language="${output.language || ""}" data-take="${output.take || ""}">▶ Play</button>
        <button type="button" class="history-download" data-job-id="${job.id}" data-language="${output.language || ""}" data-take="${output.take || ""}">Download ↓</button>
        <audio class="history-audio" data-language="${output.language || ""}" data-take="${output.take || ""}" preload="none"></audio>
      </div>`).join("") : "";
    return `
      <article class="history-item">
        <div class="history-icon">♪</div>
        <div class="history-copy">
          <strong>${escapeHtml(job.title || job.text_preview)}</strong>
          <p>${escapeHtml(job.text_preview)}</p>
          <span>${escapeHtml(job.project_name || "Unfiled")} · ${new Date(job.created_at).toLocaleString()} · ${escapeHtml(job.voice_label || "Cloned voice")} · ${languageSummary}</span>
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
  bindPublicSamples();
  bindMarketingPresets();
  renderBillingCycle("annual");
  $$('[data-billing-cycle]').forEach((button) => {
    button.addEventListener("click", () => renderBillingCycle(button.dataset.billingCycle));
  });
  $$('.plan-checkout').forEach((button) => {
    button.addEventListener("click", () => openCheckout(button.dataset.planBase));
  });
  $("#auth-form").addEventListener("submit", (event) => {
    event.preventDefault();
    submitAuth(false);
  });
  $("#signup-button").addEventListener("click", () => submitAuth(true));
  $("#signout-button").addEventListener("click", async () => {
    await state.supabase?.auth.signOut();
    state.session = null;
    state.savedVoices = [];
    $("#signout-button").classList.add("hidden");
    $("#profile-menu").classList.add("hidden");
    renderRoute();
  });
  $("#billing-button").addEventListener("click", async () => {
    if (!state.account?.subscription) {
      window.location.assign("/pricing");
      return;
    }
    const button = $("#billing-button");
    button.disabled = true;
    try {
      const response = await apiFetch("/api/billing/portal", { method: "POST" });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || "Billing portal is unavailable");
      window.location.assign(result.url);
    } catch (error) {
      button.disabled = false;
      toast(error.message, true);
    }
  });
  $("#new-project-button").addEventListener("click", () => {
    const form = $("#new-project-form");
    form.classList.toggle("hidden");
    if (!form.classList.contains("hidden")) $("#new-project-name").focus();
  });
  $("#new-project-form").addEventListener("submit", createProject);
  $("#project-list").addEventListener("click", (event) => {
    const project = event.target.closest("[data-project-id]");
    if (!project) return;
    state.historyProjectId = project.dataset.projectId;
    $("#task-project").value = state.historyProjectId;
    renderProjectList();
    switchView("history");
  });
  $('[data-project-filter="all"]').addEventListener("click", () => {
    state.historyProjectId = null;
    renderProjectList();
    switchView("history");
  });
  [$("#top-profile-button"), $("#sidebar-profile-button")].forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      $("#profile-menu").classList.toggle("hidden");
    });
  });
  $("#profile-menu").addEventListener("click", (event) => event.stopPropagation());
  document.addEventListener("click", () => $("#profile-menu").classList.add("hidden"));
  [$("#manage-voices-button"), $("#profile-voices-button")].forEach((button) => {
    button.addEventListener("click", openVoiceLibrary);
  });
  $("#close-voice-library").addEventListener("click", closeVoiceLibrary);
  $("#voice-library-modal").addEventListener("click", (event) => {
    if (event.target === $("#voice-library-modal")) closeVoiceLibrary();
  });
  $("#voice-library-list").addEventListener("click", handleSavedVoiceAction);
  $("#create-voice-from-library").addEventListener("click", () => {
    closeVoiceLibrary();
    switchView("studio");
    elements.voiceSearch.value = "";
    elements.voiceAccent.value = "";
    elements.voiceGender.value = "";
    filterVoices();
    elements.voice.value = "clone";
    renderVoiceMode();
    elements.drop.scrollIntoView({ behavior: "smooth", block: "center" });
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !$("#voice-library-modal").classList.contains("hidden")) {
      closeVoiceLibrary();
    }
  });
  $("#history-list").addEventListener("click", async (event) => {
    const button = event.target.closest(".history-play, .history-download");
    if (!button) return;
    try {
      if (button.classList.contains("history-download")) {
        button.disabled = true;
        await startDownload(button.dataset.jobId, button.dataset.language || null, button.dataset.take || null);
        button.disabled = false;
        return;
      }
      const audio = button.closest(".history-output").querySelector(".history-audio");
      if (!audio.src) {
        const access = await getAudioAccess(
          button.dataset.jobId,
          false,
          button.dataset.language || null,
          button.dataset.take || null,
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
  $("#save-voice-toggle").addEventListener("change", (event) => {
    $("#save-voice-fields").classList.toggle("hidden", !event.target.checked);
    if (event.target.checked) $("#saved-voice-name").focus();
  });
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
  elements.voice.addEventListener("change", () => {
    const savedVoice = selectedSavedVoice();
    if (savedVoice) applyStudioPreset(savedVoice.default_preset || "natural");
    renderVoiceMode();
  });
  elements.voiceSearch.addEventListener("input", filterVoices);
  elements.voiceAccent.addEventListener("change", filterVoices);
  elements.voiceGender.addEventListener("change", filterVoices);
  $("#variations").addEventListener("change", updateScriptMeta);
  $$(".delivery-preset").forEach((button) => button.addEventListener("click", () => {
    applyStudioPreset(button.dataset.preset);
    if (isNewCloneMode()) $("#saved-voice-preset").value = button.dataset.preset;
  }));
  const requestedPreset = new URLSearchParams(window.location.search).get("preset");
  if (requestedPreset) applyStudioPreset(requestedPreset);
  elements.form.addEventListener("submit", submitGeneration);
  $$(".nav-item[data-view]").forEach((button) => button.addEventListener("click", () => {
    if (button.dataset.view === "history") {
      state.historyProjectId = null;
      renderProjectList();
    }
    switchView(button.dataset.view);
  }));
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
    const mode = elements.outputLanguage.dataset.mode;
    await prepareAudio(
      state.currentJob,
      mode === "language" ? elements.outputLanguage.value : null,
      mode === "take" ? Number(elements.outputLanguage.value) : null,
    );
  });
  elements.download.addEventListener("click", async (event) => {
    event.preventDefault();
    const jobId = elements.download.dataset.jobId;
    if (!jobId) return;
    try {
      await startDownload(
        jobId,
        elements.download.dataset.language || null,
        elements.download.dataset.take || null,
      );
    } catch (error) {
      toast(error.message, true);
    }
  });
}

async function init() {
  bindEvents();
  renderRoute();
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


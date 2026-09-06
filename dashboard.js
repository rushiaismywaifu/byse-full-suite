"use strict";

// Credentials belong to the current browser tab; API keys never enter proxy requests.
const $ = (id) => document.getElementById(id);
const API_ORIGIN = "https://api.byse.sx";
const STORAGE_KEY = "byse_connection";
const TAB_COPY = {
  dashboard: ["工作空間總覽", "整理你的影片，專注下一個好故事。"],
  files: ["影片資料庫", "搜尋、整理與管理你的所有影片。"],
  folders: ["資料夾", "把每個企劃的內容，放在對的位置。"],
  upload: ["上傳中心", "從本機或連結上傳，讓下一支作品準備就緒。"],
  encoding: ["轉碼佇列", "查看處理狀態，管理等待中的影片。"],
  tools: ["播放器與工具", "建立播放器、檢查連線與查看帳號紀錄。"],
};
const state = {
  tab: "dashboard",
  demo: false,
  connected: false,
  health: null,
  config: { mode: "proxy", token: "", key: "" },
  epoch: 0,
  requests: {},
  locks: new Set(),
  queue: [],
  uploading: false,
  fileTotal: null,
  fileHasNext: false,
  previewUrl: null,
  previewFrame: null,
};

class DashboardError extends Error {
  constructor(message, code = "") {
    super(message);
    this.code = code;
  }
}
class StaleRequest extends Error {}

function setText(id, value) {
  if ($(id)) $(id).textContent = value;
}
function value(id) {
  return $(id)?.value.trim() || "";
}
function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = String(text);
  return element;
}
function button(label, action, className = "button small secondary") {
  const element = node("button", className, label);
  element.type = "button";
  element.addEventListener("click", action);
  return element;
}
function replace(id, ...children) {
  $(id)?.replaceChildren(...children);
}
function empty(message, detail) {
  const box = node("div", "empty-state");
  box.append(node("span", "empty-icon", "◇"), node("p", "", message));
  if (detail) box.append(node("span", "muted", detail));
  return box;
}
function showResult(id, data, message) {
  const children = [];
  if (message) children.push(node("p", "result-message", message));
  children.push(
    node(
      "pre",
      "",
      typeof data === "string" ? data : JSON.stringify(data, null, 2),
    ),
  );
  replace(id, ...children);
}
function errorText(error) {
  return error?.message || "發生未知錯誤，請稍後再試。";
}
function showError(id, error) {
  if (error instanceof StaleRequest) return;
  replace(id, node("p", "error-message", errorText(error)));
}
let toastTimer;
function notify(message, type = "info") {
  let toast = $("toast");
  if (!toast) {
    toast = node("div");
    toast.id = "toast";
    document.body.append(toast);
  }
  toast.className = `toast ${type}`;
  toast.setAttribute("role", "status");
  toast.setAttribute("aria-live", "polite");
  toast.textContent = message;
  toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    toast.hidden = true;
  }, 4800);
}
function number(value, fallback = "—") {
  if (
    value === null ||
    value === undefined ||
    value === "" ||
    !Number.isFinite(Number(value))
  )
    return fallback;
  return Number(value).toLocaleString("zh-TW");
}
function duration(input) {
  if (input === null || input === undefined || input === "") return "—";
  if (!Number.isFinite(Number(input))) return String(input);
  const seconds = Math.max(0, Math.floor(Number(input)));
  const h = Math.floor(seconds / 3600),
    m = Math.floor((seconds % 3600) / 60),
    s = seconds % 60;
  return `${h ? `${h}:` : ""}${h ? String(m).padStart(2, "0") : m}:${String(s).padStart(2, "0")}`;
}
function bytes(input) {
  if (!Number.isFinite(Number(input))) return "—";
  const size = Math.max(0, Number(input));
  if (!size) return "0 B";
  const index = Math.min(4, Math.floor(Math.log(size) / Math.log(1024)));
  return `${(size / 1024 ** index).toFixed(index ? 1 : 0)} ${["B", "KB", "MB", "GB", "TB"][index]}`;
}
function arrayFrom(result, keys) {
  if (Array.isArray(result)) return result;
  for (const key of keys) if (Array.isArray(result?.[key])) return result[key];
  return [];
}
function beginRequest(name) {
  const seq = (state.requests[name] || 0) + 1;
  state.requests[name] = seq;
  const epoch = state.epoch;
  return () => state.requests[name] === seq && state.epoch === epoch;
}
function folderId(id) {
  const raw = value(id) || "0";
  if (!/^\d+$/.test(raw) || !Number.isSafeInteger(Number(raw)))
    throw new DashboardError("資料夾 ID 請輸入 0 或正整數。");
  return raw;
}
function fileCode(id, multiple = false) {
  const raw = value(id);
  const codes = multiple ? raw.split(",").map((item) => item.trim()) : [raw];
  if (!raw || codes.some((code) => !/^[a-zA-Z0-9_-]{1,100}$/.test(code))) {
    $(id)?.focus();
    throw new DashboardError(
      multiple
        ? "請輸入有效的影片代碼；多筆代碼請用逗號分隔。"
        : "請輸入有效的影片代碼（英數字、底線或連字號）。",
    );
  }
  return codes.join(",");
}
function httpUrl(raw, label = "網址") {
  let url;
  try {
    url = new URL(raw);
  } catch {
    throw new DashboardError(`${label}請填寫完整的 http:// 或 https:// 網址。`);
  }
  if (
    !["http:", "https:"].includes(url.protocol) ||
    url.username ||
    url.password
  )
    throw new DashboardError(`${label}僅接受不含帳密的 HTTP 或 HTTPS 網址。`);
  return url.href;
}
function embedOrigin(raw) {
  const input = raw || "byse.sx";
  let url;
  try {
    url = new URL(input.includes("://") ? input : `https://${input}`);
  } catch {
    throw new DashboardError("播放器網域格式不正確，例如 byse.sx。");
  }
  if (
    url.protocol !== "https:" ||
    url.username ||
    url.password ||
    url.search ||
    url.hash ||
    url.pathname !== "/" ||
    !/^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,63}$/i.test(
      url.hostname,
    ) ||
    url.port
  ) {
    throw new DashboardError(
      "播放器網域請使用有效的 HTTPS 網域，不要包含路徑、參數或連接埠。",
    );
  }
  return url.origin;
}

function apiFailure(data, httpStatus = 200) {
  const object =
    data && typeof data === "object" && !Array.isArray(data) ? data : {};
  const rawStatus = object.status;
  const numericStatus =
    rawStatus !== undefined &&
    rawStatus !== null &&
    rawStatus !== "" &&
    Number.isFinite(Number(rawStatus))
      ? Number(rawStatus)
      : null;
  const rawMessage =
    object.msg ||
    object.message ||
    (typeof object.error === "string" ? object.error : object.error?.message) ||
    "";
  const message =
    typeof rawMessage === "string" ? rawMessage : JSON.stringify(rawMessage);
  if (
    /wrong auth|invalid api key|unauthorized|invalid.*token/i.test(message) ||
    [401, 403].includes(httpStatus) ||
    [401, 403].includes(numericStatus)
  ) {
    return new DashboardError(
      "驗證未通過，請檢查連線設定中的代理 Token 或 API Key。",
      "AUTH",
    );
  }
  if (/invalid operation/i.test(message))
    return new DashboardError(
      "此帳號或 API 不支援這項操作。",
      "INVALID_OPERATION",
    );
  if (httpStatus === 429 || numericStatus === 429)
    return new DashboardError("請求過於頻繁，請稍候再試。", "RATE_LIMIT");
  if (httpStatus === 413)
    return new DashboardError("檔案超過伺服器允許的上傳大小。", "TOO_LARGE");
  if (
    httpStatus >= 400 ||
    (numericStatus !== null && numericStatus !== 200) ||
    object.error ||
    /^(error|failed|fail)$/i.test(String(rawStatus)) ||
    /^(error|failed|fail)(:|\b)/i.test(message)
  ) {
    return new DashboardError(
      message
        ? `操作未完成：${message}`
        : `服務回應錯誤（${numericStatus || httpStatus}），請稍後再試。`,
      String(numericStatus || httpStatus),
    );
  }
  return null;
}
function buildUrl(path, params = {}, config = state.config) {
  const clean = new URLSearchParams();
  Object.entries(params).forEach(([key, item]) => {
    if (key !== "key" && item !== null && item !== undefined && item !== "")
      clean.set(key, String(item));
  });
  if (config.mode === "direct") clean.set("key", config.key);
  const suffix = clean.toString();
  const base = config.mode === "proxy" ? "/api" : API_ORIGIN;
  return `${base}/${path.replace(/^\//, "")}${suffix ? `?${suffix}` : ""}`;
}
function ensureConnected() {
  if (state.locks.has("connection"))
    throw new DashboardError("正在驗證連線，請稍候再執行操作。", "CONNECTING");
  if (!state.connected)
    throw new DashboardError(
      "請先完成連線設定，再載入你的資料。",
      "DISCONNECTED",
    );
}
function invalidateConnection() {
  state.connected = false;
  state.epoch++;
  resetDataViews();
  clearPreview();
  updateConnectionUI("驗證已失效，請重新檢查連線設定。");
}
async function fetchJson(path, params = {}, options = {}) {
  if (state.demo && !options.config) return demoResponse(path, params);
  if (!options.config) ensureConnected();
  const config = options.config || state.config;
  const epoch = state.epoch;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 25000);
  try {
    const headers = { Accept: "application/json" };
    if (config.mode === "proxy" && config.token)
      headers.Authorization = `Bearer ${config.token}`;
    const response = await fetch(buildUrl(path, params, config), {
      headers,
      signal: controller.signal,
      cache: "no-store",
    });
    const raw = await response.text();
    if (epoch !== state.epoch) throw new StaleRequest();
    let data;
    try {
      data = JSON.parse(raw);
    } catch {
      if ([401, 403].includes(response.status))
        throw apiFailure({}, response.status);
      throw new DashboardError(
        response.ok
          ? "服務未傳回可辨識的資料，請檢查代理網址。"
          : `連線失敗（HTTP ${response.status}），請檢查伺服器狀態。`,
      );
    }
    const failure = apiFailure(data, response.status);
    if (failure) throw failure;
    return data;
  } catch (error) {
    if (epoch !== state.epoch) throw new StaleRequest();
    if (error.code === "AUTH" && !options.config) invalidateConnection();
    if (error.name === "AbortError")
      throw new DashboardError("連線逾時，請檢查網路後再試。", "TIMEOUT");
    if (error instanceof TypeError)
      throw new DashboardError(
        "無法連線到服務，請確認伺服器與網路狀態。直接連線也可能受到跨來源限制。",
        "NETWORK",
      );
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}
async function inspectHealth() {
  if (!["http:", "https:"].includes(location.protocol)) return null;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 6000);
  try {
    const response = await fetch("/health", {
      signal: controller.signal,
      cache: "no-store",
    });
    if (!response.ok) return null;
    const data = await response.json();
    return data?.service === "byse-proxy" ? data : null;
  } catch {
    return null;
  } finally {
    clearTimeout(timeout);
  }
}
function updateConnectionUI(message = "") {
  const label = state.demo
    ? "示範模式"
    : state.connected
      ? "已連線"
      : "尚未連線";
  setText("keyStatus", label);
  if ($("keyStatus"))
    $("keyStatus").dataset.state = state.demo
      ? "demo"
      : state.connected
        ? "connected"
        : "disconnected";
  const summary = state.demo
    ? "正在瀏覽範例資料，所有寫入操作已停用。"
    : state.connected
      ? state.config.mode === "proxy"
        ? "透過安全代理連線 · 金鑰由伺服器保管"
        : "直接連線 · 金鑰僅暫存於目前分頁"
      : "連線後即可管理你的影片與查看即時數據。";
  setText("connectionSummary", summary);
  setText(
    "connectionBannerText",
    message ||
      (state.demo
        ? "示範模式：這些是範例資料，不代表你的帳號。"
        : state.health && !state.health.configured
          ? "代理已啟動，尚未設定伺服器 API Key。你也可以先探索示範模式。"
          : summary),
  );
  if ($("connectionBanner")) {
    $("connectionBanner").hidden = state.connected && !state.demo && !message;
    $("connectionBanner").dataset.mode = state.demo ? "demo" : "disconnected";
  }
  document
    .querySelectorAll("[data-demo-toggle], #demoToggle")
    .forEach((element) => {
      element.textContent = state.demo ? "離開示範" : "探索示範";
      element.setAttribute("aria-pressed", String(state.demo));
    });
}
function openSettings() {
  if (state.uploading) return notify("上傳進行中，請完成後再更換連線。");
  if ($("connectionMode")) $("connectionMode").value = state.config.mode;
  if ($("proxyToken")) $("proxyToken").value = state.config.token;
  if ($("directApiKey")) $("directApiKey").value = state.config.key;
  setText("connectionMessage", "");
  updateConnectionFields();
  if (!$("connectionDialog")?.open) $("connectionDialog")?.showModal();
}
function closeSettings() {
  $("connectionDialog")?.close();
}
function updateConnectionFields() {
  const direct = value("connectionMode") === "direct";
  if ($("proxyToken")) $("proxyToken").disabled = direct;
  if ($("directApiKey")) $("directApiKey").disabled = !direct;
  document.querySelectorAll("[data-connection-mode]").forEach((element) => {
    element.hidden =
      element.dataset.connectionMode !== (direct ? "direct" : "proxy");
  });
}
async function saveConnection(event) {
  event?.preventDefault();
  if (state.locks.has("connection") || state.uploading) return;
  const config = {
    mode: value("connectionMode") === "direct" ? "direct" : "proxy",
    token: value("proxyToken"),
    key: value("directApiKey"),
  };
  const epoch = ++state.epoch;
  state.locks.add("connection");
  const submit = $("connectionForm")?.querySelector('[type="submit"]');
  if (submit) submit.disabled = true;
  setText("connectionMessage", "正在驗證連線…");
  try {
    if (config.mode === "direct" && !config.key)
      throw new DashboardError("請輸入 API Key。");
    if (config.mode === "proxy") {
      const health = await inspectHealth();
      if (epoch !== state.epoch) throw new StaleRequest();
      state.health = health;
      if (!state.health)
        throw new DashboardError(
          "目前沒有可用的本機代理。請啟動 server.py，或選擇直接連線。",
        );
      if (!state.health.configured)
        throw new DashboardError(
          "伺服器尚未設定 BYSE_API_KEY，請先完成伺服器設定。",
        );
      if (state.health.requires_token && !config.token)
        throw new DashboardError(
          "此代理需要 Token，請輸入伺服器設定的存取 Token。",
        );
    }
    await fetchJson("account/info", {}, { config });
    if (epoch !== state.epoch) throw new StaleRequest();
    state.config = config;
    state.demo = false;
    state.connected = true;
    state.epoch++;
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(config));
    } catch {
      /* Storage can be unavailable in private browsing. */
    }
    closeSettings();
    resetDataViews();
    clearPreview();
    updateConnectionUI();
    notify("連線成功，正在更新你的資料。", "success");
    state.locks.delete("connection");
    await refreshCurrent();
  } catch (error) {
    if (!(error instanceof StaleRequest))
      setText("connectionMessage", errorText(error));
  } finally {
    state.locks.delete("connection");
    if (submit) submit.disabled = false;
  }
}
function resetDataViews() {
  for (const id of [
    "metricFiles",
    "metricViews",
    "metricStorage",
    "metricBalance",
  ])
    setText(id, "—");
  setText("metricStorageFootnote", "連線後顯示儲存用量");
  replace("accountInfo", empty("尚未連線", "設定連線後，即可查看帳號資訊。"));
  replace(
    "accountStats",
    empty("你的觀看趨勢將顯示在這裡", "連線後查看近 7 天的觀看數據。"),
  );
  tableMessage(
    "recentFiles",
    4,
    "準備好你的第一支影片",
    "連線後會在這裡顯示最近的影片。",
  );
  tableMessage("fileTable", 5, "尚未載入影片", "設定連線，或探索示範資料。");
  replace("folderList", empty("尚未載入資料夾"));
  replace("encodingList", empty("尚未載入轉檔佇列"));
  setText("activitySummary", "連線後掌握最新動態");
  setText("fileCount", "尚未載入");
  setText("filePagination", "第 1 頁");
  state.fileTotal = null;
  state.fileHasNext = false;
  if ($("filePage")) $("filePage").value = "1";
  if ($("prevPage")) $("prevPage").disabled = true;
  if ($("nextPage")) $("nextPage").disabled = true;
  for (const id of [
    "fileOpResult",
    "folderCreateResult",
    "remoteResult",
    "encResult",
    "deletedResult",
    "dmcaResult",
    "testAllResult",
    "embedDomainResult",
    "toolResult",
  ])
    setText(id, "選擇操作後，結果會顯示在這裡。");
}
async function toggleDemo() {
  if (state.uploading || state.locks.has("connection"))
    return notify("目前有作業進行中，請完成後再切換模式。");
  state.demo = !state.demo;
  state.epoch++;
  if ($("filePage")) $("filePage").value = "1";
  clearPreview();
  resetDataViews();
  updateConnectionUI();
  await refreshCurrent();
}
function switchTab(name, updateHash = true) {
  if (!Object.hasOwn(TAB_COPY, name)) name = "dashboard";
  state.tab = name;
  document.querySelectorAll(".tab").forEach((element) => {
    element.hidden = element.id !== `tab-${name}`;
  });
  document.querySelectorAll("nav [data-tab]").forEach((element) => {
    const active = element.dataset.tab === name;
    element.classList.toggle("active", active);
    if (active) element.setAttribute("aria-current", "page");
    else element.removeAttribute("aria-current");
  });
  setText("pageTitle", TAB_COPY[name][0]);
  setText("pageDescription", TAB_COPY[name][1]);
  if (updateHash && location.hash !== `#${name}`)
    history.replaceState(null, "", `#${name}`);
  void refreshCurrent();
}
async function refreshCurrent() {
  if (!state.connected && !state.demo) return;
  if (state.tab === "dashboard") return loadDashboard();
  if (state.tab === "files") return loadFileList();
  if (state.tab === "folders") return loadFolderList();
  if (state.tab === "encoding") return loadEncodingList();
}

const DEMO_FILES = [
  {
    file_code: "demo_summer01",
    title: "夏日提案・品牌形象影片.mp4",
    length: 148,
    views: 2846,
    canplay: 1,
    fld_id: "0",
    tone: "sand",
  },
  {
    file_code: "demo_city02",
    title: "城市漫遊｜台北的一天.mp4",
    length: 326,
    views: 1924,
    canplay: 1,
    fld_id: "0",
    tone: "city",
  },
  {
    file_code: "demo_studio03",
    title: "Studio Notes — 幕後花絮.mp4",
    length: 214,
    views: 860,
    canplay: 1,
    fld_id: "1",
    tone: "studio",
  },
  {
    file_code: "demo_ocean04",
    title: "海岸線：週末影像紀錄.mov",
    length: 182,
    views: 0,
    canplay: 0,
    fld_id: "0",
    tone: "ocean",
  },
  {
    file_code: "demo_product05",
    title: "秋季新品・15 秒精華.mp4",
    length: 15,
    views: 3120,
    canplay: 1,
    fld_id: "2",
    tone: "product",
  },
  {
    file_code: "demo_morning06",
    title: "Morning Light — 生活提案.mp4",
    length: 94,
    views: 638,
    canplay: 1,
    fld_id: "1",
    tone: "morning",
  },
];
function demoResponse(path, params) {
  const ok = (result) => ({ status: 200, msg: "示範資料", result });
  if (path === "account/info")
    return ok({
      email: "studio@example.com",
      files_total: 24,
      balance: "128.40",
      storage_used_bytes: 12.8 * 1024 ** 3,
      storage_total_bytes: 100 * 1024 ** 3,
      account_type: "創作者方案（示範）",
    });
  if (path === "account/stats")
    return ok(
      [480, 720, 560, 1080, 890, 1420, 1260].map((views, index) => {
        const date = new Date();
        date.setDate(date.getDate() - (6 - index));
        return {
          day: `${date.getMonth() + 1}/${date.getDate()}`,
          views,
          downloads: Math.round(views / 40),
          profit: (views * 0.003).toFixed(2),
        };
      }),
    );
  if (path === "file/list") {
    const keyword = String(params.title || "").toLocaleLowerCase();
    const files = DEMO_FILES.filter(
      (file) =>
        (!params.fld_id ||
          String(params.fld_id) === "0" ||
          file.fld_id === String(params.fld_id)) &&
        file.title.toLocaleLowerCase().includes(keyword),
    );
    const per = Number(params.per_page) || 20,
      page = Number(params.page) || 1;
    return ok({
      files: files.slice((page - 1) * per, page * per),
      total: files.length,
    });
  }
  if (path === "folder/list")
    return ok({
      folders:
        String(params.fld_id || 0) === "0"
          ? [
              { fld_id: 1, name: "品牌企劃", files: 8 },
              { fld_id: 2, name: "產品影片", files: 6 },
              { fld_id: 3, name: "日常紀錄", files: 10 },
            ]
          : [],
    });
  if (path === "encoding/list")
    return ok([
      {
        file_code: "demo_ocean04",
        title: "海岸線：週末影像紀錄.mov",
        status: "encoding",
        progress: 64,
      },
    ]);
  if (path === "encoding/status")
    return ok({
      file_code: params.file_code,
      status: "encoding",
      progress: 64,
    });
  if (path === "file/info")
    return ok(
      DEMO_FILES.filter((file) =>
        String(params.file_code).split(",").includes(file.file_code),
      ),
    );
  if (path === "remote/status")
    return ok({
      file_code: params.file_code,
      status: "waiting",
      note: "這是示範資料。",
    });
  if (path === "upload/server") return ok("示範模式不會連線到上傳伺服器");
  if (path === "files/deleted" || path === "files/dmca") return ok([]);
  if (path.includes("domain")) return ok(["byse.sx"]);
  if (path.startsWith("images/"))
    return ok({
      file_code: params.file_code,
      note: "示範影片沒有實際圖片網址。",
    });
  if (
    [
      "file/hls",
      "file/premium_link",
      "file/direct_link",
      "account/hls",
    ].includes(path)
  )
    return ok({ note: "示範模式不提供實際播放連結。" });
  throw new DashboardError(
    "示範模式僅供瀏覽，請連線後再執行這項操作。",
    "DEMO",
  );
}

async function loadDashboard() {
  await Promise.allSettled([
    loadAccountInfo(),
    loadAccountStats(),
    loadRecentFiles(),
  ]);
}
async function loadAccountInfo() {
  const current = beginRequest("account");
  replace("accountInfo", node("p", "muted", "正在載入帳號資訊…"));
  try {
    const data = await fetchJson("account/info");
    if (!current()) return;
    const account = data.result;
    if (!account || typeof account !== "object" || Array.isArray(account)) {
      replace("accountInfo", empty("尚無帳號資訊"));
      return;
    }
    setText("metricFiles", number(account.files_total ?? account.files));
    setText("metricBalance", number(account.balance));
    if (account.storage_used_bytes !== undefined) {
      setText("metricStorage", bytes(account.storage_used_bytes));
      setText(
        "metricStorageFootnote",
        account.storage_total_bytes !== undefined
          ? `總容量 ${bytes(account.storage_total_bytes)}`
          : "已使用容量",
      );
    } else {
      setText("metricStorage", number(account.storage_used ?? account.storage));
      setText("metricStorageFootnote", "服務未提供儲存單位");
    }
    const details = node("dl", "account-details");
    [
      ["帳號", account.email ?? account.login],
      ["方案", account.account_type ?? account.type],
      ["影片數量", number(account.files_total ?? account.files)],
      ["到期日", account.premium_expire ?? account.premium_expiry],
    ].forEach(([label, content]) => {
      if (content !== undefined && content !== null && content !== "")
        details.append(node("dt", "", label), node("dd", "", content));
    });
    replace(
      "accountInfo",
      details.children.length
        ? details
        : empty("帳號已連線", "服務未提供其他帳號資訊。"),
    );
  } catch (error) {
    if (current()) {
      showError("accountInfo", error);
      for (const id of ["metricFiles", "metricStorage", "metricBalance"])
        setText(id, "—");
      setText("metricStorageFootnote", "暫時無法取得儲存用量");
    }
  }
}
async function loadAccountStats() {
  const current = beginRequest("stats");
  replace("accountStats", node("p", "muted", "正在載入觀看趨勢…"));
  try {
    const data = await fetchJson("account/stats", { last: 7 });
    if (!current()) return;
    const rows = arrayFrom(data.result, ["stats"]);
    const isNumber = (amount) =>
      amount !== undefined &&
      amount !== null &&
      amount !== "" &&
      Number.isFinite(Number(amount));
    const viewsAvailable = rows.some((row) => isNumber(row?.views));
    const downloadsAvailable = rows.some((row) => isNumber(row?.downloads));
    const chartField = viewsAvailable
      ? "views"
      : downloadsAvailable
        ? "downloads"
        : "profit";
    const chartLabel = viewsAvailable
      ? "觀看次數"
      : downloadsAvailable
        ? "下載次數"
        : "收益";
    const stats = rows
      .map((row) => ({
        label: row?.day ?? row?.date,
        amount:
          chartField === "profit"
            ? (row?.profit ?? row?.earnings)
            : row?.[chartField],
      }))
      .filter(
        (row) =>
          row.label !== undefined &&
          isNumber(row.amount) &&
          Number(row.amount) >= 0,
      )
      .slice(-7);
    if (!stats.length) {
      const noStats = empty("尚無觀看數據", "有觀看紀錄後，這裡就會顯示趨勢。");
      if (
        data.result &&
        (Array.isArray(data.result)
          ? data.result.length
          : Object.keys(data.result).length)
      ) {
        const details = node("details");
        details.append(
          node("summary", "", "檢視服務回傳資料"),
          node("pre", "", JSON.stringify(data.result, null, 2)),
        );
        replace("accountStats", noStats, details);
      } else replace("accountStats", noStats);
      setText("metricViews", "—");
      return;
    }
    const total = stats.reduce((sum, item) => sum + Number(item.amount), 0);
    setText("metricViews", viewsAvailable ? number(total) : "—");
    const summary = node("div", "stat-summary");
    summary.append(
      node("strong", "", number(total)),
      node("span", "muted", `近 7 天${chartLabel}`),
    );
    const earnings = rows
      .map((row) => row?.profit ?? row?.earnings)
      .filter(isNumber);
    if (earnings.length && chartField !== "profit")
      summary.append(
        node(
          "span",
          "muted",
          `收益 ${number(earnings.reduce((sum, amount) => sum + Number(amount), 0))}`,
        ),
      );
    const chart = node("div", "chart-bars");
    chart.setAttribute("role", "img");
    chart.setAttribute(
      "aria-label",
      stats
        .map((item) => `${item.label}：${number(item.amount)} ${chartLabel}`)
        .join("；"),
    );
    const maximum = Math.max(...stats.map((item) => Number(item.amount)), 1);
    stats.forEach((item) => {
      const column = node("div", "chart-column");
      const bar = node("div", "chart-bar");
      bar.style.height = `${(Number(item.amount) / maximum) * 100}%`;
      bar.title = `${item.label} · ${number(item.amount)} ${chartLabel}`;
      const label = String(item.label)
        .replace(/^\d{4}-/, "")
        .replaceAll("-", "/");
      column.append(bar, node("span", "chart-label", label));
      chart.append(column);
    });
    replace("accountStats", summary, chart);
  } catch (error) {
    if (current()) {
      showError("accountStats", error);
      setText("metricViews", "—");
    }
  }
}
function tableMessage(id, columns, message, detail) {
  const row = node("tr"),
    cell = node("td");
  cell.colSpan = columns;
  cell.append(empty(message, detail));
  row.append(cell);
  replace(id, row);
}
function statusPill(file) {
  const ready = Number(file.canplay) === 1 || file.status === "ready";
  const failed = ["error", "failed"].includes(
    String(file.status).toLowerCase(),
  );
  return node(
    "span",
    `status-pill ${ready ? "ready" : failed ? "error" : "pending"}`,
    ready ? "可播放" : failed ? "處理失敗" : "處理中",
  );
}
function titleCell(file) {
  const cell = node("td");
  const wrapper = node("div", "cell-title");
  const thumbnail = node(
    "span",
    `mini-thumb${state.demo && file.tone ? ` ${file.tone}` : ""}`,
    "▶",
  );
  thumbnail.setAttribute("aria-hidden", "true");
  const text = node("div");
  text.append(
    node("span", "file-name", file.title || file.file_title || "未命名影片"),
    node(
      "span",
      "file-code",
      file.file_code || file.filecode || "未提供影片代碼",
    ),
  );
  wrapper.append(thumbnail, text);
  cell.append(wrapper);
  return cell;
}
function renderFileRows(id, files, recent = false) {
  const rows = files
    .filter((file) => file && typeof file === "object")
    .map((file) => {
      const row = node("tr"),
        code = String(file.file_code || file.filecode || "");
      row.append(titleCell(file));
      if (!recent)
        row.append(
          node("td", "muted", duration(file.length ?? file.file_length)),
        );
      if (recent) {
        const status = node("td");
        status.append(statusPill(file));
        row.append(status);
      }
      row.append(node("td", "", number(file.views ?? file.file_views, "0")));
      if (!recent) {
        const status = node("td");
        status.append(statusPill(file));
        row.append(status);
      }
      const actions = node("td"),
        group = node("div", "row-actions");
      if (code) {
        group.append(
          button(recent ? "管理 ↗" : "管理", () => {
            if (state.tab !== "files") switchTab("files");
            setOpCode(code);
          }),
        );
        if (!recent) group.append(button("詳情", () => quickInfo(code)));
      } else group.append(node("span", "muted", "—"));
      actions.append(group);
      row.append(actions);
      return row;
    });
  replace(id, ...rows);
}
async function loadRecentFiles() {
  const current = beginRequest("recent");
  tableMessage("recentFiles", 4, "正在載入最近的影片…");
  try {
    const data = await fetchJson("file/list", {
      fld_id: 0,
      per_page: 4,
      page: 1,
    });
    if (!current()) return;
    const files = arrayFrom(data.result, ["files"]).slice(0, 4);
    if (files.length) renderFileRows("recentFiles", files, true);
    else
      tableMessage(
        "recentFiles",
        4,
        "你的下一個作品，從這裡開始",
        "前往上傳中心新增第一支影片。",
      );
    setText(
      "activitySummary",
      state.demo
        ? "範例資料 · 最近 4 支影片"
        : files.length
          ? `已更新 · ${new Date().toLocaleTimeString("zh-TW", { hour: "2-digit", minute: "2-digit" })}`
          : "目前沒有影片",
    );
  } catch (error) {
    if (current() && !(error instanceof StaleRequest)) {
      tableMessage("recentFiles", 4, "無法載入影片", errorText(error));
      setText("activitySummary", "更新失敗，請重新整理");
    }
  }
}
async function loadFileList() {
  const current = beginRequest("files");
  tableMessage("fileTable", 5, "正在載入影片…");
  if ($("prevPage")) $("prevPage").disabled = true;
  if ($("nextPage")) $("nextPage").disabled = true;
  try {
    const per = Math.max(1, Math.min(100, Number(value("filePerPage")) || 20));
    const page = Math.max(1, Number(value("filePage")) || 1);
    const data = await fetchJson("file/list", {
      fld_id: folderId("fileFldId"),
      per_page: per,
      page,
      title: value("fileTitle"),
    });
    if (!current()) return;
    const files = arrayFrom(data.result, ["files"]);
    const totalRaw = data.result?.total ?? data.total;
    state.fileTotal =
      totalRaw !== undefined &&
      totalRaw !== null &&
      totalRaw !== "" &&
      Number.isFinite(Number(totalRaw))
        ? Number(totalRaw)
        : null;
    state.fileHasNext =
      state.fileTotal !== null
        ? page * per < state.fileTotal
        : files.length === per;
    if (files.length) renderFileRows("fileTable", files);
    else
      tableMessage(
        "fileTable",
        5,
        value("fileTitle") ? "找不到符合的影片" : "這裡還沒有影片",
        value("fileTitle")
          ? "試試不同的關鍵字，或清除搜尋條件。"
          : "上傳影片，或查看其他資料夾。",
      );
    setText(
      "fileCount",
      state.fileTotal !== null
        ? `${number(state.fileTotal)} 支影片`
        : `本頁 ${number(files.length)} 支影片`,
    );
    setText(
      "filePagination",
      state.fileTotal !== null
        ? `第 ${page} / ${Math.max(1, Math.ceil(state.fileTotal / per))} 頁`
        : `第 ${page} 頁`,
    );
    if ($("prevPage")) $("prevPage").disabled = page <= 1;
    if ($("nextPage")) $("nextPage").disabled = !state.fileHasNext;
  } catch (error) {
    if (current() && !(error instanceof StaleRequest)) {
      tableMessage("fileTable", 5, "無法載入影片", errorText(error));
      setText("fileCount", "載入失敗");
    }
  }
}
function searchFiles(event) {
  event?.preventDefault();
  if ($("filePage")) $("filePage").value = "1";
  return loadFileList();
}
function changeFilePage(delta) {
  if (delta > 0 && !state.fileHasNext) return;
  if ($("filePage"))
    $("filePage").value = String(
      Math.max(1, (Number(value("filePage")) || 1) + delta),
    );
  return loadFileList();
}
function setOpCode(code) {
  for (const id of ["opFileCode", "toolFileCode", "encFileCode"])
    if ($(id)) $(id).value = code;
  if ($("fileOperations")) {
    $("fileOperations").open = true;
    $("fileOperations").scrollIntoView({
      behavior: "smooth",
      block: "nearest",
    });
  }
  $("opFileCode")?.focus({ preventScroll: true });
}
function quickInfo(code) {
  setOpCode(code);
  return doFileInfo();
}

function allowWrite() {
  if (state.demo)
    throw new DashboardError(
      "示範模式僅供瀏覽。連線到你的帳號後，就能執行此操作。",
      "DEMO",
    );
  ensureConnected();
}
async function operation(id, action, options = {}) {
  const lock = options.lock || id;
  if (state.locks.has(lock)) return;
  const epoch = state.epoch;
  try {
    if (options.write) allowWrite();
    state.locks.add(lock);
    setText(id, "處理中…");
    const data = await action();
    if (epoch !== state.epoch) throw new StaleRequest();
    showResult(id, data, options.message);
    if (options.message) notify(options.message, "success");
    if (options.refresh) await options.refresh();
    return data;
  } catch (error) {
    if (epoch !== state.epoch) return;
    showError(id, error);
    if (!(error instanceof StaleRequest)) notify(errorText(error), "error");
  } finally {
    state.locks.delete(lock);
  }
}
function doFileInfo() {
  return operation("fileOpResult", () =>
    fetchJson("file/info", { file_code: fileCode("opFileCode", true) }),
  );
}
function doFileClone() {
  return operation(
    "fileOpResult",
    () => fetchJson("file/clone", { file_code: fileCode("opFileCode") }),
    { write: true, message: "影片已複製。", refresh: loadFileList },
  );
}
function doFileEditTitle() {
  return operation(
    "fileOpResult",
    () => {
      const title = value("opNewTitle");
      if (!title) {
        $("opNewTitle")?.focus();
        throw new DashboardError("請輸入新的影片名稱。");
      }
      return fetchJson("file/edit", {
        file_code: fileCode("opFileCode"),
        file_title: title,
      });
    },
    { write: true, message: "影片名稱已更新。", refresh: loadFileList },
  );
}
function doFileEditPublic(pub) {
  return operation(
    "fileOpResult",
    () =>
      fetchJson("file/edit", {
        file_code: fileCode("opFileCode"),
        file_public: pub ? 1 : 0,
      }),
    {
      write: true,
      message: pub ? "影片已設為公開。" : "影片已設為私人。",
      refresh: loadFileList,
    },
  );
}
function doThumb() {
  return operation("fileOpResult", () =>
    fetchJson("images/thumb", { file_code: fileCode("opFileCode") }),
  );
}
function doSplash() {
  return operation("fileOpResult", () =>
    fetchJson("images/splash", { file_code: fileCode("opFileCode") }),
  );
}
function doPreview() {
  return operation("fileOpResult", () =>
    fetchJson("images/preview", { file_code: fileCode("opFileCode") }),
  );
}
function iframeMarkup(url) {
  return `<iframe src="${url.replaceAll("&", "&amp;").replaceAll('"', "&quot;")}" title="影片播放器" width="640" height="360" style="border:0" allow="fullscreen; picture-in-picture" allowfullscreen></iframe>`;
}
function doGenerateEmbed() {
  try {
    const url = `${embedOrigin(value("toolDomain"))}/e/${fileCode("opFileCode")}`;
    showResult(
      "fileOpResult",
      `播放網址\n${url}\n\n嵌入程式碼\n${iframeMarkup(url)}`,
    );
    notify("嵌入程式碼已產生。", "success");
  } catch (error) {
    showError("fileOpResult", error);
  }
}
async function copyResult(id) {
  const text = $(id)?.textContent.trim();
  if (!text) return notify("目前沒有可複製的內容。");
  try {
    await navigator.clipboard.writeText(text);
    notify("已複製到剪貼簿。", "success");
  } catch {
    const range = document.createRange();
    range.selectNodeContents($(id));
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    notify("瀏覽器限制剪貼簿存取，已選取內容，請按 Ctrl/Cmd + C 複製。");
  }
}

async function loadFolderList() {
  const current = beginRequest("folders");
  replace("folderList", node("p", "muted", "正在載入資料夾…"));
  try {
    const data = await fetchJson("folder/list", {
      fld_id: folderId("folderParentId"),
    });
    if (!current()) return;
    const folders = arrayFrom(data.result, ["folders"]);
    if (!folders.length) {
      replace(
        "folderList",
        empty("還沒有資料夾", "建立資料夾，讓影片更有條理。"),
      );
      return;
    }
    const grid = node("div", "folder-grid");
    folders
      .filter((folder) => folder && typeof folder === "object")
      .forEach((folder) => {
        const id = String(folder.fld_id ?? folder.folder_id ?? folder.id ?? "");
        const card = node("article", "folder-item");
        card.append(
          node("span", "empty-icon", "▱"),
          node("h3", "", folder.name || folder.fld_name || "未命名資料夾"),
          node(
            "p",
            "muted",
            `資料夾 ID ${id || "—"}${folder.files !== undefined ? ` · ${number(folder.files)} 支影片` : ""}`,
          ),
        );
        const actions = node("div", "row-actions");
        if (/^\d+$/.test(id)) {
          actions.append(
            button("查看影片", () => {
              $("fileFldId").value = id;
              $("filePage").value = "1";
              $("fileTitle").value = "";
              switchTab("files");
            }),
          );
          actions.append(
            button("子資料夾", () => {
              $("folderParentId").value = id;
              $("newFolderParent").value = id;
              void loadFolderList();
            }),
          );
        }
        card.append(actions);
        grid.append(card);
      });
    replace("folderList", grid);
  } catch (error) {
    if (current()) showError("folderList", error);
  }
}
function createFolder() {
  return operation(
    "folderCreateResult",
    () => {
      const name = value("newFolderName");
      if (!name) {
        $("newFolderName")?.focus();
        throw new DashboardError("請輸入資料夾名稱。");
      }
      return fetchJson("folder/create", {
        name,
        parent_id: folderId("newFolderParent"),
        descr: value("newFolderDescr"),
      });
    },
    {
      write: true,
      message: "資料夾已建立。",
      refresh: () => {
        $("folderParentId").value = value("newFolderParent") || "0";
        $("newFolderName").value = "";
        return loadFolderList();
      },
    },
  );
}

const VIDEO_EXTENSIONS = new Set([
  "mp4",
  "mkv",
  "avi",
  "webm",
  "mov",
  "wmv",
  "flv",
  "m4v",
  "mpeg",
  "mpg",
  "3gp",
  "ts",
]);
function selectFiles(files) {
  if (state.uploading) return notify("上傳進行中，請完成後再新增檔案。");
  let rejected = 0,
    duplicates = 0;
  for (const file of files) {
    if (!VIDEO_EXTENSIONS.has(file.name.split(".").pop().toLowerCase())) {
      rejected++;
      continue;
    }
    if (
      state.queue.some(
        (item) =>
          item.file.name === file.name &&
          item.file.size === file.size &&
          item.file.lastModified === file.lastModified,
      )
    ) {
      duplicates++;
      continue;
    }
    state.queue.push({
      file,
      status: "pending",
      progress: 0,
      message: "等待上傳",
    });
  }
  renderQueue();
  if (rejected)
    notify(
      `${rejected} 個檔案格式不支援，請選擇 MP4、MOV、MKV 等影片格式。`,
      "error",
    );
  else if (duplicates) notify(`已略過 ${duplicates} 個重複檔案。`);
}
function renderQueue() {
  const rows = state.queue.map((item) => {
    const row = node("div", "queue-item");
    const info = node("div", "queue-info");
    info.append(
      node("div", "queue-name", item.file.name),
      node(
        "div",
        `queue-status${item.status === "error" ? " error-message" : ""}`,
        `${bytes(item.file.size)} · ${item.message}`,
      ),
    );
    const track = node("div", "progress-track");
    const fill = node("div", "progress-fill");
    fill.style.width = `${item.progress}%`;
    track.append(fill);
    track.setAttribute("role", "progressbar");
    track.setAttribute("aria-label", `${item.file.name} 上傳進度`);
    track.setAttribute("aria-valuemin", "0");
    track.setAttribute("aria-valuemax", "100");
    track.setAttribute("aria-valuenow", String(Math.round(item.progress)));
    info.append(track);
    row.append(info);
    const remove = button("移除", () => {
      state.queue = state.queue.filter((entry) => entry !== item);
      renderQueue();
    });
    remove.setAttribute("aria-label", `移除 ${item.file.name}`);
    remove.disabled = state.uploading;
    row.append(remove);
    return row;
  });
  replace("uploadQueue", ...rows);
  if ($("uploadStart")) {
    $("uploadStart").disabled =
      state.uploading ||
      !state.queue.some((item) => ["pending", "error"].includes(item.status));
    $("uploadStart").textContent = state.uploading
      ? "上傳中…"
      : state.queue.some((item) => item.status === "error")
        ? "重試未完成檔案"
        : "開始上傳";
  }
  if ($("localFile")) $("localFile").disabled = state.uploading;
  if (!state.uploading && !state.queue.length)
    setText("uploadProgress", "選擇檔案後，會先加入上傳佇列。");
}
function uploadCode(data) {
  const candidates = data?.files ?? data?.result ?? data;
  const entries = Array.isArray(candidates) ? candidates : [candidates];
  for (const entry of entries) {
    if (
      typeof entry === "string" &&
      /^[a-zA-Z0-9_-]+$/.test(entry) &&
      !/^(ok|success|error|failed)$/i.test(entry)
    )
      return entry;
    if (!entry || typeof entry !== "object") continue;
    const failure = apiFailure(entry);
    if (failure) throw failure;
    if (
      entry.status !== undefined &&
      !/^(ok|success|200)$/i.test(String(entry.status))
    )
      throw new DashboardError(`上傳未完成：${String(entry.status)}`);
    const code = entry.filecode ?? entry.file_code;
    if (typeof code === "string" && /^[a-zA-Z0-9_-]+$/.test(code)) return code;
  }
  throw new DashboardError("服務未確認上傳成功，請檢查影片資料庫後再重試。");
}
function sendUpload(item, target, form, config) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", target);
    xhr.timeout = 15 * 60 * 1000;
    if (config.mode === "proxy" && config.token)
      xhr.setRequestHeader("Authorization", `Bearer ${config.token}`);
    xhr.upload.onprogress = (event) => {
      if (!event.lengthComputable) return;
      const sent = Math.min(100, (event.loaded / event.total) * 100);
      item.progress = Math.min(99, sent);
      item.message =
        sent >= 100
          ? "伺服器處理中，等待確認…"
          : `傳送至${config.mode === "proxy" ? "代理" : "上傳伺服器"} ${Math.floor(sent)}%`;
      renderQueue();
    };
    xhr.upload.onload = () => {
      item.progress = 99;
      item.message = "伺服器處理中，等待確認…";
      renderQueue();
    };
    xhr.onload = () => {
      try {
        if ([401, 403].includes(xhr.status)) throw apiFailure({}, xhr.status);
        let data;
        try {
          data = JSON.parse(xhr.responseText);
        } catch {
          throw new DashboardError(
            `上傳回應無法辨識（HTTP ${xhr.status}），請稍後確認影片資料庫。`,
          );
        }
        const failure = apiFailure(data, xhr.status);
        if (failure) throw failure;
        resolve(uploadCode(data));
      } catch (error) {
        reject(error);
      }
    };
    xhr.onerror = () =>
      reject(new DashboardError("上傳連線中斷，請檢查網路後重試。"));
    xhr.ontimeout = () =>
      reject(
        new DashboardError(
          "上傳等待逾時，請確認影片是否已入庫，再決定是否重試。",
        ),
      );
    xhr.onabort = () => reject(new DashboardError("上傳已取消。"));
    xhr.send(form);
  });
}
async function uploadLocalFiles() {
  if (state.uploading) return;
  try {
    allowWrite();
    folderId("uploadFolderId");
  } catch (error) {
    notify(errorText(error), "error");
    return;
  }
  const pending = state.queue.filter((item) =>
    ["pending", "error"].includes(item.status),
  );
  if (!pending.length) return notify("請先選擇要上傳的影片。");
  state.uploading = true;
  const epoch = state.epoch;
  const config = { ...state.config };
  const targetFolder = folderId("uploadFolderId");
  let completed = 0;
  renderQueue();
  setText("uploadProgress", `準備上傳 ${pending.length} 個檔案…`);
  try {
    let target = "/upload";
    if (config.mode === "direct") {
      const data = await fetchJson("upload/server");
      target = httpUrl(
        typeof data.result === "string"
          ? data.result
          : data.result?.url || data.result?.server,
        "上傳伺服器網址",
      );
      if (!target.startsWith("https://"))
        throw new DashboardError("上傳伺服器必須使用 HTTPS。");
    }
    for (const item of pending) {
      if (epoch !== state.epoch || !state.connected) break;
      item.status = "uploading";
      item.progress = 0;
      item.message = "正在連線…";
      renderQueue();
      try {
        const form = new FormData();
        form.append("file", item.file);
        if (config.mode === "direct") form.append("key", config.key);
        if (targetFolder !== "0") form.append("fld_id", targetFolder);
        const code = await sendUpload(item, target, form, config);
        item.status = "success";
        item.progress = 100;
        item.message = `上傳完成 · ${code}`;
        completed++;
      } catch (error) {
        item.status = "error";
        item.message = errorText(error);
        if (error.code === "AUTH") invalidateConnection();
      }
      renderQueue();
    }
    setText(
      "uploadProgress",
      `已完成 ${completed} / ${pending.length} 個檔案${completed < pending.length ? "。未完成的檔案可重試。" : "。影片可能仍需等待轉檔。"}`,
    );
    notify(
      completed === pending.length
        ? "上傳完成。"
        : "部分檔案未完成，請查看佇列中的說明。",
      completed === pending.length ? "success" : "error",
    );
  } catch (error) {
    setText("uploadProgress", errorText(error));
    notify(errorText(error), "error");
  } finally {
    state.uploading = false;
    renderQueue();
  }
}
function remoteUpload() {
  return operation(
    "remoteResult",
    async () => {
      const url = httpUrl(value("remoteUrl"), "影片連結");
      const fld_id = folderId("remoteFolderId");
      let data;
      try {
        data = await fetchJson("remote/add", { url, fld_id });
      } catch (error) {
        if (error.code !== "INVALID_OPERATION") throw error;
        data = await fetchJson("upload/url", { url, fld_id });
      }
      const code =
        typeof data.result === "string"
          ? data.result
          : (data.result?.filecode ?? data.result?.file_code);
      if (
        typeof code === "string" &&
        /^[a-zA-Z0-9_-]+$/.test(code) &&
        $("remoteFileCode")
      )
        $("remoteFileCode").value = code;
      return data;
    },
    { write: true, message: "遠端上傳已加入佇列。" },
  );
}
function loadRemoteStatusPrompt() {
  return operation("remoteResult", () =>
    fetchJson("remote/status", { file_code: fileCode("remoteFileCode") }),
  );
}
async function removeRemotePrompt() {
  let code;
  try {
    allowWrite();
    code = fileCode("remoteFileCode");
  } catch (error) {
    showError("remoteResult", error);
    return;
  }
  if (
    !(await confirmAction(
      "移除遠端上傳？",
      `將移除影片 ${code} 的遠端上傳工作。`,
    ))
  )
    return;
  return operation(
    "remoteResult",
    () => fetchJson("remote/remove", { file_code: code }),
    { write: true, message: "已移除遠端上傳工作。" },
  );
}
function confirmAction(title, message) {
  const dialog = $("confirmActionDialog");
  if (!dialog || typeof dialog.showModal !== "function")
    return Promise.resolve(window.confirm(`${title}\n${message}`));
  if (dialog.open) return Promise.resolve(false);
  setText("confirmActionTitle", title);
  setText("confirmActionText", message);
  dialog.returnValue = "";
  return new Promise((resolve) => {
    const submit = $("confirmActionSubmit");
    const approve = (event) => {
      event.preventDefault();
      dialog.close("confirm");
    };
    const closed = () => {
      submit?.removeEventListener("click", approve);
      resolve(dialog.returnValue === "confirm");
    };
    submit?.addEventListener("click", approve);
    dialog.addEventListener("close", closed, { once: true });
    dialog.showModal();
  });
}

async function loadEncodingList() {
  const current = beginRequest("encoding");
  replace("encodingList", node("p", "muted", "正在載入轉檔佇列…"));
  try {
    const data = await fetchJson("encoding/list");
    if (!current()) return;
    const entries = arrayFrom(data.result, ["files", "queue", "encoding"]);
    if (!entries.length) {
      replace(
        "encodingList",
        empty("所有工作都已就緒", "目前沒有等待轉檔的影片。"),
      );
      return;
    }
    const rows = entries
      .filter((entry) => entry && typeof entry === "object")
      .map((entry) => {
        const row = node("div", "list-row");
        const info = node("div");
        const code = String(entry.file_code || entry.filecode || "");
        info.append(
          node(
            "strong",
            "",
            entry.title || entry.file_title || code || "未命名影片",
          ),
          node("div", "muted", code),
        );
        const status = String(entry.status || "等待處理");
        const labels = {
          encoding: "轉檔中",
          pending: "等待中",
          waiting: "等待中",
          done: "已完成",
          ready: "已完成",
          error: "失敗",
          failed: "失敗",
        };
        const suffix =
          entry.progress !== undefined &&
          Number.isFinite(Number(entry.progress))
            ? ` · ${Math.max(0, Math.min(100, Number(entry.progress)))}%`
            : "";
        row.append(
          info,
          node(
            "span",
            `status-pill ${["error", "failed"].includes(status) ? "error" : ["ready", "done"].includes(status) ? "ready" : "pending"}`,
            `${labels[status] || status}${suffix}`,
          ),
        );
        if (code)
          row.append(
            button("查看狀態", () => {
              $("encFileCode").value = code;
              $("encFileCode").focus();
              void loadEncStatus();
            }),
          );
        return row;
      });
    replace("encodingList", ...rows);
  } catch (error) {
    if (current()) showError("encodingList", error);
  }
}
function loadEncStatus() {
  return operation("encResult", () =>
    fetchJson("encoding/status", { file_code: fileCode("encFileCode") }),
  );
}
function encRestart() {
  return operation(
    "encResult",
    () => fetchJson("encoding/restart", { file_code: fileCode("encFileCode") }),
    { write: true, message: "已送出重新轉檔要求。", refresh: loadEncodingList },
  );
}
async function encDelete() {
  let code;
  try {
    allowWrite();
    code = fileCode("encFileCode");
  } catch (error) {
    showError("encResult", error);
    return;
  }
  if (
    !(await confirmAction(
      "刪除轉檔工作？",
      `將刪除 ${code} 的轉檔工作。請確認你不再需要這項工作。`,
    ))
  )
    return;
  return operation(
    "encResult",
    () => fetchJson("encoding/delete", { file_code: code }),
    { write: true, message: "轉檔工作已刪除。", refresh: loadEncodingList },
  );
}
function loadDeleted() {
  return operation("deletedResult", async () => {
    const data = await fetchJson("files/deleted");
    return Array.isArray(data.result) && !data.result.length
      ? "目前沒有已刪除的影片紀錄。"
      : data;
  });
}
function loadDMCA() {
  return operation("dmcaResult", async () => {
    const data = await fetchJson("files/dmca");
    return Array.isArray(data.result) && !data.result.length
      ? "目前沒有版權通知紀錄。"
      : data;
  });
}
function loadEmbedDomains() {
  return operation("embedDomainResult", async () => {
    const results = [];
    for (const path of [
      "account/embed_domains",
      "file/embed_domains",
      "account/custom_domain",
    ]) {
      try {
        const data = await fetchJson(path);
        results.push(
          `${path}\n${JSON.stringify(data.result ?? data, null, 2)}`,
        );
      } catch (error) {
        if (error instanceof StaleRequest) throw error;
        results.push(`${path}\n${errorText(error)}`);
        if (["AUTH", "DISCONNECTED"].includes(error.code)) break;
      }
    }
    return results.join("\n\n");
  });
}
async function testAll() {
  switchTab("tools");
  return operation("testAllResult", async () => {
    const epoch = state.epoch;
    const endpoints = [
      "account/info",
      "account/stats",
      "upload/server",
      "file/list",
      "folder/list",
      "files/deleted",
      "files/dmca",
      "encoding/list",
    ];
    const results = [];
    for (const path of endpoints) {
      try {
        await fetchJson(
          path,
          path === "file/list"
            ? { fld_id: 0, per_page: 1 }
            : path === "account/stats"
              ? { last: 7 }
              : {},
        );
        results.push(`✓ ${path} · ${state.demo ? "示範回應" : "連線正常"}`);
      } catch (error) {
        if (error instanceof StaleRequest) throw error;
        results.push(`× ${path} · ${errorText(error)}`);
      }
      if (epoch !== state.epoch) throw new StaleRequest();
      setText("testAllResult", results.join("\n"));
    }
    return results.join("\n");
  });
}
function clearPreview() {
  replace("toolIframePreview");
  state.previewFrame = null;
  state.previewUrl = null;
  clearProgressEvents();
}
function buildAdvancedEmbed() {
  const code = fileCode("toolFileCode");
  const url = new URL(`${embedOrigin(value("toolDomain"))}/e/${code}`);
  if (value("toolSubUrl")) {
    url.searchParams.set("c1_file", httpUrl(value("toolSubUrl"), "字幕網址"));
    url.searchParams.set("c1_label", value("toolSubLabel") || "字幕");
  }
  if (value("toolPoster"))
    url.searchParams.set("poster", httpUrl(value("toolPoster"), "封面網址"));
  if (value("toolLogo"))
    url.searchParams.set("logo", httpUrl(value("toolLogo"), "Logo 網址"));
  return url.href;
}
function generateEmbedAdvanced() {
  try {
    const url = buildAdvancedEmbed();
    clearPreview();
    state.previewUrl = url;
    showResult(
      "toolResult",
      `播放網址\n${url}\n\n嵌入程式碼\n${iframeMarkup(url)}`,
    );
    notify("嵌入程式碼已產生，可複製或開啟播放器預覽。", "success");
  } catch (error) {
    clearPreview();
    showError("toolResult", error);
  }
}
function previewEmbed() {
  if (state.demo)
    return notify("示範影片沒有實際播放內容。你可以產生與複製嵌入程式碼。");
  try {
    const url = buildAdvancedEmbed();
    clearPreview();
    state.previewUrl = url;
    const iframe = node("iframe");
    iframe.title = "影片播放器預覽";
    iframe.src = url;
    iframe.allow = "fullscreen; picture-in-picture";
    iframe.allowFullscreen = true;
    iframe.referrerPolicy = "strict-origin-when-cross-origin";
    iframe.setAttribute(
      "sandbox",
      "allow-scripts allow-same-origin allow-presentation",
    );
    state.previewFrame = iframe;
    replace("toolIframePreview", iframe);
  } catch (error) {
    showError("toolResult", error);
  }
}
function tryPremiumHls() {
  return operation("toolResult", async () => {
    const code = fileCode("toolFileCode");
    const ip = value("toolIp");
    const ua = value("toolUa");
    if (!ip || !ua) throw new DashboardError("請填寫觀看者 IP 與 User-Agent。");
    const output = [];
    for (const path of [
      "file/hls",
      "file/premium_link",
      "file/direct_link",
      "account/hls",
    ]) {
      try {
        const data = await fetchJson(path, { file_code: code, ip, ua });
        output.push(`${path}\n${JSON.stringify(data.result ?? data, null, 2)}`);
      } catch (error) {
        if (error instanceof StaleRequest) throw error;
        output.push(`${path}\n${errorText(error)}`);
        if (["AUTH", "DISCONNECTED"].includes(error.code)) break;
      }
    }
    return output.join("\n\n");
  });
}
function clearProgressEvents() {
  setText("progressEvents", "開啟播放器預覽後，播放進度會顯示在這裡。");
}
window.addEventListener("message", (event) => {
  if (
    !state.previewFrame ||
    event.source !== state.previewFrame.contentWindow ||
    !state.previewUrl ||
    event.origin !== new URL(state.previewUrl).origin
  )
    return;
  const data = event.data;
  if (
    !data ||
    typeof data !== "object" ||
    data.type !== "byse-progress" ||
    typeof data.progress !== "number" ||
    !Number.isFinite(data.progress) ||
    data.progress < 0 ||
    data.progress > 100
  )
    return;
  if (
    data.timestamp !== undefined &&
    (typeof data.timestamp !== "number" ||
      !Number.isFinite(data.timestamp) ||
      data.timestamp < 0)
  )
    return;
  if (
    data.duration !== undefined &&
    (typeof data.duration !== "number" ||
      !Number.isFinite(data.duration) ||
      data.duration < 0)
  )
    return;
  const log = $("progressEvents");
  if (log)
    log.textContent = `[${new Date().toLocaleTimeString("zh-TW")}] ${data.progress.toFixed(1)}%${data.timestamp !== undefined && data.duration !== undefined ? ` · ${duration(data.timestamp)} / ${duration(data.duration)}` : ""}\n${log.textContent.slice(0, 2500)}`;
});

async function initialize() {
  const initialEpoch = state.epoch;
  try {
    localStorage.removeItem("byse_api_key");
  } catch {
    /* Do not retain the previous persistent API key. */
  }
  try {
    const saved = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || "null");
    if (saved && ["proxy", "direct"].includes(saved.mode))
      state.config = {
        mode: saved.mode,
        token: typeof saved.token === "string" ? saved.token : "",
        key: typeof saved.key === "string" ? saved.key : "",
      };
  } catch {
    /* An invalid saved setting can be replaced from the connection dialog. */
  }
  resetDataViews();
  updateConnectionUI();
  document.addEventListener("click", (event) => {
    const target = event.target.closest("[data-tab]");
    if (target && !target.hasAttribute("onclick")) {
      event.preventDefault();
      switchTab(target.dataset.tab);
    }
  });
  window.addEventListener("hashchange", () =>
    switchTab(location.hash.slice(1), false),
  );
  $("connectionMode")?.addEventListener("change", updateConnectionFields);
  if (!$("connectionForm")?.hasAttribute("onsubmit"))
    $("connectionForm")?.addEventListener("submit", saveConnection);
  $("localFile")?.addEventListener("change", (event) => {
    selectFiles(event.target.files);
    event.target.value = "";
  });
  const drop = $("drop");
  drop?.addEventListener("dragover", (event) => {
    event.preventDefault();
    if (!state.uploading) drop.classList.add("drag");
  });
  drop?.addEventListener("dragleave", (event) => {
    if (!drop.contains(event.relatedTarget)) drop.classList.remove("drag");
  });
  drop?.addEventListener("drop", (event) => {
    event.preventDefault();
    drop.classList.remove("drag");
    selectFiles(event.dataTransfer.files);
  });
  renderQueue();
  switchTab(location.hash.slice(1) || "dashboard", false);
  const health = await inspectHealth();
  if (state.demo || state.epoch !== initialEpoch) return;
  state.health = health;
  if (!state.health && state.config.mode === "proxy")
    state.config.mode = "direct";
  updateConnectionUI();
  const canConnect =
    state.config.mode === "direct"
      ? Boolean(state.config.key)
      : state.health?.configured &&
        (!state.health.requires_token || state.config.token);
  if (canConnect) {
    try {
      await fetchJson("account/info", {}, { config: state.config });
      if (state.epoch !== initialEpoch) return;
      state.connected = true;
      updateConnectionUI();
      await refreshCurrent();
    } catch (error) {
      if (state.epoch === initialEpoch) {
        state.connected = false;
        updateConnectionUI(errorText(error));
      }
    }
  }
}
void initialize();

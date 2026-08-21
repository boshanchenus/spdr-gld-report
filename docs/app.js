const state = { reports: [] };
const latest = document.querySelector("#latest");
const history = document.querySelector("#history");
const statusBox = document.querySelector("#status");
const refreshButton = document.querySelector("#refreshButton");
const reportCount = document.querySelector("#reportCount");
const template = document.querySelector("#reportTemplate");
const dialog = document.querySelector("#imageDialog");
const dialogImage = document.querySelector("#dialogImage");
const dialogCaption = document.querySelector("#dialogCaption");

function formatDate(value) {
  const date = new Date(`${value}T00:00:00`);
  return new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "long", day: "numeric" }).format(date);
}

function signed(value) {
  const number = Number(value || 0);
  return `${number >= 0 ? "+" : ""}${number.toFixed(2)} 吨`;
}

function reportCard(report) {
  const card = template.content.firstElementChild.cloneNode(true);
  const image = card.querySelector(".report-image");
  image.src = report.image;
  image.alt = `SPDR GLD ${formatDate(report.source_date)} 报告`;
  card.querySelector(".report-date").textContent = `数据截至 ${formatDate(report.source_date)}`;
  card.querySelector(".report-meta").textContent = `最新持仓 ${Number(report.ending_tonnes).toFixed(2)} 吨`;
  const change = card.querySelector(".change-pill");
  change.textContent = signed(report.latest_change);
  change.classList.add(Number(report.latest_change) >= 0 ? "positive" : "negative");
  card.querySelector(".image-button").addEventListener("click", () => {
    dialogImage.src = report.image;
    dialogCaption.textContent = `${formatDate(report.source_date)} · 最新周变化 ${signed(report.latest_change)}`;
    dialog.showModal();
  });
  return card;
}

function render() {
  latest.replaceChildren();
  history.replaceChildren();
  if (!state.reports.length) {
    latest.hidden = true;
    statusBox.textContent = "还没有报告。云端任务首次运行后会自动显示。";
    return;
  }
  statusBox.textContent = "";
  const label = document.createElement("p");
  label.className = "latest-label";
  label.textContent = "最新报告";
  latest.append(label, reportCard(state.reports[0]));
  latest.hidden = false;
  state.reports.slice(1).forEach((report) => history.append(reportCard(report)));
  reportCount.textContent = `共 ${state.reports.length} 份`;
}

async function loadReports() {
  refreshButton.classList.add("loading");
  statusBox.classList.remove("error");
  try {
    const response = await fetch(`reports.json?t=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    state.reports = Array.isArray(data.reports) ? data.reports : [];
    render();
  } catch (error) {
    statusBox.textContent = navigator.onLine
      ? `暂时无法读取报告：${error.message}`
      : "当前处于离线状态；连接网络后点右上角刷新。";
    statusBox.classList.add("error");
  } finally {
    refreshButton.classList.remove("loading");
  }
}

refreshButton.addEventListener("click", loadReports);
document.querySelector("#closeDialog").addEventListener("click", () => dialog.close());
dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });

const installTip = document.querySelector("#installTip");
const standalone = window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone;
if (!standalone && /iPhone|iPad|iPod/.test(navigator.userAgent) && localStorage.getItem("installTipClosed") !== "yes") {
  installTip.hidden = false;
}
document.querySelector("#closeInstallTip").addEventListener("click", () => {
  installTip.hidden = true;
  localStorage.setItem("installTipClosed", "yes");
});

if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js");
loadReports();

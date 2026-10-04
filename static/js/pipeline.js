(() => {
  const $ = id => document.getElementById(id);
  let timer, latestPipeline;
  const labels = {
    QUEUED: "Queued", RUNNING: "In progress", SUCCEEDED: "Completed",
    FAILED: "Needs attention", CANCELLED: "Cancelled", PENDING: "Pending", STOPPED: "Stopped"
  };
  const chip = status => {
    const span = document.createElement("span");
    span.className = `status-chip status-${String(status || "unknown").toLowerCase()}`;
    span.textContent = labels[status] || status || "Unknown";
    return span;
  };
  function showError(error) { $("pipeline-error").textContent = error.message || "The pipeline request failed."; }
  function renderSummary(data) {
    const host = $("pipeline-summary");
    const statusCount = (status) => (data.stages || []).filter(stage => stage.status === status).length;
    const blocks = [
      ["Date range", `${data.start_date || data.as_of_date} – ${data.end_date || data.as_of_date}`],
      ["Strategies", (data.strategies || []).join(", ") || "—"],
      ["Stages complete", `${statusCount("SUCCEEDED")} of ${(data.stages || []).length}`]
    ];
    if (data.market_data) blocks.push(["Market bars", `${data.market_data.succeeded} ready · ${data.market_data.pending} pending · ${data.market_data.failed} failed`]);
    host.replaceChildren(...blocks.map(([label, value]) => {
      const item = document.createElement("div"); item.className = "pipeline-stat";
      const caption = document.createElement("span"); caption.textContent = label;
      const strong = document.createElement("strong"); strong.textContent = value;
      item.append(caption, strong); return item;
    }));
  }
  function render(data) {
    latestPipeline = data;
    $("pipeline-id").value = data.pipeline_id || $("pipeline-id").value;
    $("cancel-pipeline").disabled = !["RUNNING", "QUEUED"].includes(data.status);
    const state = $("pipeline-state"); state.replaceChildren(chip(data.status));
    renderSummary(data);
    $("stages").replaceChildren(...(data.stages || []).map(stage => {
      const retry = document.createElement("button"); retry.textContent = "Retry stage"; retry.className = "secondary";
      retry.disabled = stage.status !== "FAILED" && stage.status !== "CANCELLED";
      retry.onclick = () => request(`/api/pipelines/research/${encodeURIComponent(data.pipeline_id)}/stages/${encodeURIComponent(stage.name)}/retry`, {method:"POST"});
      const name = document.createElement("strong"); name.textContent = stage.name.replaceAll(":", " · ");
      const id = document.createElement("code"); id.textContent = stage.job_id;
      return Screener.row([name, chip(stage.status), id, retry]);
    }));
    if (!(data.stages || []).length) $("stages").innerHTML = '<tr><td colspan="4" class="workflow-empty">No stages have been created for this run yet.</td></tr>';
    clearTimeout(timer);
    if (["RUNNING", "QUEUED"].includes(data.status)) timer = setTimeout(load, 2500);
  }
  async function request(path, options) {
    try { $("pipeline-error").textContent = ""; render(await Screener.api(path, options)); }
    catch (error) { showError(error); }
  }
  async function load() {
    const id = $("pipeline-id").value.trim(); if (!id) { showError(new Error("Enter a pipeline ID to load a run.")); return; }
    await request(`/api/pipelines/research/${encodeURIComponent(id)}`);
  }
  function renderWorker(data) {
    const running = Boolean(data.running);
    const state = $("worker-state"); state.replaceChildren(chip(running ? "RUNNING" : "STOPPED"));
    const host = $("worker"), stats = [
      ["Worker", running ? "Running" : "Stopped"],
      ["Active jobs", String((data.active_jobs || []).length)],
      ["Queued jobs", Object.values(data.queued_by_kind || {}).reduce((sum, count) => sum + count, 0)]
    ];
    host.replaceChildren(...stats.map(([label, value]) => {
      const item = document.createElement("div"); item.className = "worker-stat";
      const caption = document.createElement("span"); caption.textContent = label;
      const strong = document.createElement("strong"); strong.textContent = value;
      item.append(caption, strong); return item;
    }));
    if ((data.active_jobs || []).length) {
      const list = document.createElement("ul"); list.className = "worker-job-list";
      data.active_jobs.forEach(job => { const item = document.createElement("li"); item.textContent = `Job ${job.job_id} · ${job.kind} · ${labels[job.status] || job.status}`; list.append(item); });
      host.append(list);
    }
  }
  async function workerAction(action) {
    try {
      const result = await Screener.api(`/api/operations/worker/${action === "status" ? "status" : action}`, {method: action === "status" ? "GET" : "POST"});
      if (action === "work-once") {
        if (result.job) renderWorker({...(await Screener.api("/api/operations/worker/status")), last_job: result.job});
        else { renderWorker(await Screener.api("/api/operations/worker/status")); $("pipeline-error").textContent = "No queued job was available to run."; }
        if (latestPipeline) await load();
      } else renderWorker(result);
    } catch (error) { showError(error); }
  }
  document.addEventListener("DOMContentLoaded", () => {
    $("submit-pipeline").onclick = () => request("/api/pipelines/research", {method:"POST",body:JSON.stringify({start_date:$("start").value,end_date:$("end").value,orchestrate_data:$("data").checked})});
    $("load-pipeline").onclick = load;
    $("pipeline-id").addEventListener("keydown", event => { if (event.key === "Enter") load(); });
    $("cancel-pipeline").onclick = () => request(`/api/pipelines/research/${encodeURIComponent($("pipeline-id").value)}/cancel`, {method:"POST"});
    document.querySelectorAll("[data-worker]").forEach(button => button.onclick = () => workerAction(button.dataset.worker));
    $("worker-status").onclick = () => workerAction("status");
    workerAction("status");
  });
  window.addEventListener("pagehide", () => clearTimeout(timer));
})();

"use strict";

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const state = {
  token: null,
  connected: false,
  active: null,
  selected: null,
  busy: false,
  samples: [],
  events: [],
  sequence: 0,
  gap: false,
  target: "",
  lastRunVersion: "",
  instanceToken: "",
  pendingNoticeRun: null,
  sampleRevision: 0,
};
const suites = {
  smoke: "Smoke tests",
  link: "Link tests",
  thermal: "Thermal tests",
  fault: "Fault tests",
  recovery: "Recovery tests",
  full: "Full validation",
};
const clock = (value) =>
  new Date(value).toLocaleTimeString([], { hour12: false });
const dateTime = (value) =>
  new Date(value).toLocaleString([], { hour12: false });

function notify(message, error = false) {
  const node = $("#notice");
  node.hidden = false;
  node.textContent = message;
  node.classList.toggle("error", error);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    signal: AbortSignal.timeout(5000),
    cache: "no-store",
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-Halt-Token": state.token || "",
      ...options.headers,
    },
  });
  const body = await response.json();
  if (!response.ok) {
    const detail = body.detail;
    throw new Error(
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((item) => item.msg).join("; ")
          : `${detail?.code || response.status}: ${detail?.message || "Request failed"}`,
    );
  }
  return body;
}

function lockControls() {
  const locked = !state.connected || state.busy || !!state.active;
  $$(".control, [data-suite]").forEach((control) => {
    control.disabled = locked;
  });
  $("#lease-banner").hidden = !state.active;
  $("#nav-running").hidden = !state.active;
}

async function action(path, body, message) {
  state.busy = true;
  lockControls();
  try {
    const result = await api(path, {
      method: "POST",
      body: JSON.stringify(body),
    });
    if (message) notify(message);
    return result;
  } catch (error) {
    notify(error.message, true);
    throw error;
  } finally {
    try {
      await refreshSnapshot();
    } catch {
      // The command's own result stays visible; freshness is reported separately.
    }
    state.busy = false;
    lockControls();
  }
}

async function refreshSnapshot() {
  const revision = ++state.sampleRevision;
  try {
    const data = await api("/api/state");
    if (revision === state.sampleRevision) showSnapshot(data);
  } catch (error) {
    if (revision === state.sampleRevision) disconnected(error);
    throw error;
  }
}

function statusText(selector, text, tone = "") {
  const element = $(selector);
  element.textContent = text;
  element.classList.remove("good", "bad", "warning");
  if (tone) element.classList.add(tone);
}

function showSnapshot(data) {
  state.connected = true;
  state.active = data.active_run;
  $("#connection").textContent = `${state.target} · connected`;
  $("#connection").className = "connection online";
  $("#sample-time").textContent = clock(data.sampled_at);
  const status = data.status;
  statusText(
    "#device-state",
    status.state,
    status.state === "READY"
      ? "good"
      : status.state === "FAULT"
        ? "bad"
        : "warning",
  );
  statusText(
    "#link-state",
    status.link_up ? "UP" : "DOWN",
    status.link_up ? "good" : "warning",
  );
  statusText("#device-mode", status.mode);
  statusText(
    "#fault-state",
    status.fault,
    status.fault === "NONE" ? "" : "bad",
  );
  statusText("#uptime", `${(status.uptime_ms / 1000).toFixed(1)} s`);
  $("#tx-state").textContent = status.tx_enabled ? "TX ENABLED" : "TX DISABLED";
  statusText(
    "#alarms",
    status.alarms.length ? status.alarms.join(" / ") : "None asserted",
    status.alarms.length ? "bad" : "good",
  );
  $$("[data-field]").forEach((cell) => {
    const value = data.telemetry?.[cell.dataset.field];
    cell.textContent = typeof value === "number" ? value.toFixed(2) : "—";
  });
  if (data.telemetry_error) {
    statusText("#telemetry-valid", data.telemetry_error.code, "bad");
    $("#telemetry-valid").title = data.telemetry_error.message;
  } else {
    statusText(
      "#telemetry-valid",
      data.telemetry?.valid ? "VALID SAMPLE" : "INVALID TELEMETRY",
      data.telemetry?.valid ? "good" : "bad",
    );
    $("#telemetry-valid").title = "";
  }
  const rx = data.telemetry?.rx_power_dbm;
  state.samples.push(
    data.telemetry?.valid && typeof rx === "number" ? rx : null,
  );
  if (state.samples.length > 90) state.samples.shift();
  // Separate polylines at missing samples; never bridge a transport failure with fabricated data.
  $$("#trace .sample-segment").forEach((node) => node.remove());
  let points = [];
  const flush = () => {
    if (!points.length) return;
    const line = document.createElementNS(
      "http://www.w3.org/2000/svg",
      "polyline",
    );
    line.setAttribute("points", points.join(" "));
    line.setAttribute("class", "sample-segment");
    $("#trace").append(line);
    points = [];
  };
  state.samples.forEach((value, index) => {
    if (value === null) {
      flush();
      return;
    }
    const x = 48 + (index * 596) / 89;
    const y = 16 + (Math.max(0, Math.min(65, -value)) / 65) * 118;
    points.push(`${x.toFixed(2)},${y.toFixed(2)}`);
  });
  flush();
  $("#trace-empty").setAttribute(
    "visibility",
    state.samples.some((value) => value !== null) ? "hidden" : "visible",
  );
  const margin =
    typeof rx === "number" && data.telemetry?.valid ? rx + 20 : null;
  $("#rx-margin").textContent =
    margin === null
      ? "No valid RX sample"
      : `${margin >= 0 ? "+" : ""}${margin.toFixed(2)} dB to LOS`;
  lockControls();
}

function disconnected(error) {
  state.connected = false;
  $("#connection").textContent = "Device unavailable";
  $("#connection").className = "connection offline";
  $("#sample-time").textContent = "No current sample";
  $("#connection").title = error.message;
  [
    "#device-state",
    "#link-state",
    "#device-mode",
    "#uptime",
    "#fault-state",
  ].forEach((id) => statusText(id, "—"));
  $$("[data-field]").forEach((cell) => {
    cell.textContent = "—";
  });
  statusText("#telemetry-valid", "UNAVAILABLE", "bad");
  statusText("#alarms", "Unknown — device unreachable", "warning");
  $("#tx-state").textContent = "TX UNKNOWN";
  $("#rx-margin").textContent = "No current sample";
  state.samples.push(null);
  if (state.samples.length > 90) state.samples.shift();
  lockControls();
}

function renderEvents() {
  const log = $("#event-log");
  const level = $("#log-level").value;
  const position = log.scrollTop;
  const fragment = document.createDocumentFragment();
  state.events
    .filter((event) => level === "all" || event.level === level)
    .forEach((event) => {
      const row = document.createElement("div");
      row.className = `event-line ${event.level === "WARN" ? "warn" : ""}`;
      [
        clock(event.timestamp),
        event.level,
        event.component,
        event.message,
      ].forEach((value) => {
        const span = document.createElement("span");
        span.textContent = value;
        row.append(span);
      });
      fragment.append(row);
    });
  log.replaceChildren(fragment);
  log.scrollTop = $("#log-follow").checked ? log.scrollHeight : position;
  $("#log-meta").textContent =
    `${state.events.length} retained events · device sequence ${state.sequence} · times shown locally${state.gap ? " · older server events were overwritten" : ""}`;
}

async function pollEvents() {
  const data = await api(`/api/events?after=${state.sequence}`);
  if (data.gap) state.gap = true;
  if (data.events.length) {
    state.events.push(...data.events);
    state.events = state.events.slice(-512);
    state.sequence = data.events.at(-1).sequence;
    renderEvents();
  }
}

function navigate() {
  const page =
    location.pathname === "/validation"
      ? "validation"
      : location.pathname === "/architecture"
        ? "architecture"
        : "workbench";
  $$("[data-page]").forEach((element) => {
    element.hidden = element.dataset.page !== page;
  });
  $$("[data-route]").forEach((element) => {
    const active = element.dataset.route === page;
    element.classList.toggle("active", active);
    if (active) element.setAttribute("aria-current", "page");
    else element.removeAttribute("aria-current");
  });
  document.title = `HALt · ${page[0].toUpperCase() + page.slice(1)}`;
}

function renderRun(run) {
  $("#run-empty").hidden = true;
  $("#run-content").hidden = false;
  statusText(
    "#run-badge",
    run.state.toUpperCase(),
    run.state === "passed"
      ? "good"
      : ["failed", "error"].includes(run.state)
        ? "bad"
        : "warning",
  );
  $("#run-title").textContent = suites[run.suite];
  $("#run-time").textContent =
    `${dateTime(run.started_at)} · ${run.id.slice(0, 8)}${run.duration_ms !== null ? ` · ${(run.duration_ms / 1000).toFixed(2)} s` : ""}`;
  $("#run-progress").textContent =
    run.total === null
      ? run.state === "running"
        ? "Collecting…"
        : "No cases completed"
      : `${run.completed} / ${run.total} complete`;
  $("#run-bar").max = run.total || 1;
  $("#run-bar").value = run.completed;
  $("#cancel-run").hidden = run.state !== "running";
  $("#cancel-run").disabled = false;
  $("#cancel-run").textContent = "Cancel run";
  $("#run-counts").replaceChildren(
    ...Object.entries(run.counts).map(([name, count]) => {
      const span = document.createElement("span");
      span.textContent = `${count} ${name.toUpperCase()}`;
      span.className =
        name === "passed"
          ? "good"
          : name === "failed" || name === "error"
            ? "bad"
            : "quiet";
      return span;
    }),
  );
  const errors = [run.error, ...run.collection_errors]
    .filter(Boolean)
    .join("\n");
  $("#run-error").textContent = errors;
  $("#run-error").hidden = !errors;
  const version = `${run.id}:${run.state}:${JSON.stringify(run.cases)}`;
  if (version !== state.lastRunVersion) {
    const rows = run.cases.map((test) => {
      const row = document.createElement("tr");
      const outcome = document.createElement("td");
      outcome.textContent = test.outcome.toUpperCase();
      outcome.className =
        test.outcome === "passed"
          ? "good"
          : ["failed", "error"].includes(test.outcome)
            ? "bad"
            : "quiet";
      const name = document.createElement("td");
      const label = test.name.split("::").slice(1).join("::") || test.name;
      if (test.detail) {
        const details = document.createElement("details");
        const summary = document.createElement("summary");
        summary.textContent = label;
        const pre = document.createElement("pre");
        pre.textContent = test.detail;
        details.append(summary, pre);
        name.append(details);
      } else name.textContent = label;
      name.title = test.name;
      const duration = document.createElement("td");
      duration.textContent = `${test.duration_ms.toFixed(1)} ms`;
      row.append(outcome, name, duration);
      return row;
    });
    $("#test-results").replaceChildren(...rows);
    state.lastRunVersion = version;
  }
  $("#artifacts").replaceChildren(
    ...run.artifacts.map((name) => {
      const link = document.createElement("a");
      link.textContent = name;
      link.href = `/api/runs/${run.id}/artifacts/${name}`;
      return link;
    }),
  );
  const provenance = {
    "Run ID": run.id,
    "gRPC target": run.target,
    "Started (UTC)": run.started_at,
    "Finished (UTC)": run.finished_at || "In progress",
    "Process exit code": run.exit_code ?? "Not exited",
    Python: run.python,
    "Source SHA-256": run.source_sha256,
    "Executable SHA-256": run.binary_sha256,
    "Protocol SHA-256": run.proto_sha256,
  };
  $("#run-provenance").replaceChildren(
    ...Object.entries(provenance).flatMap(([key, value]) => {
      const term = document.createElement("dt"),
        definition = document.createElement("dd");
      term.textContent = key;
      definition.textContent = value;
      return [term, definition];
    }),
  );
}

async function pollRuns() {
  const data = await api("/api/runs");
  state.active = data.active_run;
  if (!state.selected && data.runs.length) state.selected = data.runs[0].id;
  const selected = data.runs.find((run) => run.id === state.selected);
  const completed = data.runs.find(
    (run) => run.id === state.pendingNoticeRun && run.state !== "running",
  );
  if (completed) {
    notify(
      `${suites[completed.suite]} ${completed.state}: ${completed.counts.passed} passed, ${completed.counts.failed + completed.counts.error} failed/errors. Manual controls released.`,
      ["failed", "error", "interrupted"].includes(completed.state),
    );
    state.pendingNoticeRun = null;
  }
  if (selected) renderRun(selected);
  if (data.runs.length)
    $("#run-history").replaceChildren(
      ...data.runs.map((run) => {
        const button = document.createElement("button");
        button.className = `history-entry ${run.id === state.selected ? "selected" : ""}`;
        const top = document.createElement("strong");
        const name = document.createElement("span"),
          badge = document.createElement("span");
        name.textContent = suites[run.suite];
        badge.textContent = run.state.toUpperCase();
        badge.className =
          run.state === "passed"
            ? "good"
            : ["failed", "error"].includes(run.state)
              ? "bad"
              : "quiet";
        top.append(name, badge);
        const subtitle = document.createElement("small");
        subtitle.textContent = `${dateTime(run.started_at)} · ${run.id.slice(0, 8)}`;
        button.append(top, subtitle);
        button.addEventListener("click", () => {
          state.selected = run.id;
          renderRun(run);
        });
        return button;
      }),
    );
  lockControls();
}

$$("[data-command]").forEach((button) =>
  button.addEventListener("click", () => {
    action(
      "/api/command",
      { action: button.dataset.command },
      `${button.textContent} command accepted.`,
    ).catch(() => {});
  }),
);
$$("[data-mode]").forEach((button) =>
  button.addEventListener("click", () => {
    action(
      "/api/command",
      { action: "mode", mode: button.dataset.mode },
      `Mode set to ${button.dataset.mode}.`,
    ).catch(() => {});
  }),
);
["attenuation", "temperature"].forEach((name) => {
  $(`#${name}-form`).addEventListener("submit", (event) => {
    event.preventDefault();
    const value = Number($(`#${name}`).value);
    action(
      "/api/command",
      { action: name, value },
      `${name === "attenuation" ? "Attenuation" : "Temperature"} set to ${value} ${name === "attenuation" ? "dB" : "°C"}.`,
    ).catch(() => {});
  });
});
$("#fault-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const fault = $("#fault").value;
  action(
    "/api/command",
    { action: "inject_fault", fault },
    `Injected ${fault}. Inspect the device state and alarms.`,
  ).catch(() => {});
});
$("#meter-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("#meter-reading").textContent = "Measuring…";
  try {
    const result = await action("/api/measure", {
      channel: $("#meter-channel").value,
      noise: Number($("#meter-noise").value),
      simulate_timeout: $("#meter-behavior").value === "timeout",
      simulate_error: $("#meter-behavior").value === "error",
    });
    $("#meter-reading").textContent =
      `${result.channel} ${result.power_dbm.toFixed(3)} dBm · ${clock(result.at)}`;
  } catch (error) {
    $("#meter-reading").textContent = error.message;
  }
});
$$("[data-suite]").forEach((button) =>
  button.addEventListener("click", async () => {
    try {
      const run = await action(
        "/api/runs",
        { suite: button.dataset.suite },
        "Validation started on the workbench device. Manual controls are locked.",
      );
      state.selected = run.id;
      state.active = run.id;
      state.pendingNoticeRun = run.id;
      renderRun(run);
      lockControls();
    } catch {
      /* action() displays the actual server error. */
    }
  }),
);
$("#cancel-run").addEventListener("click", async () => {
  try {
    await action(
      `/api/runs/${state.selected}/cancel`,
      {},
      "Cancellation requested. Partial evidence will be retained.",
    );
    $("#cancel-run").disabled = true;
    $("#cancel-run").textContent = "Cancelling…";
  } catch {
    /* Already completed or unavailable; leave the evidence visible. */
  }
});
$("#log-level").addEventListener("change", renderEvents);
$("#download-events").addEventListener("click", () => {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(state.events, null, 2)], {
      type: "application/json",
    }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = "halt-visible-events.json";
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
document.addEventListener("click", (event) => {
  const link = event.target.closest("a[href]");
  if (
    !link ||
    event.ctrlKey ||
    event.metaKey ||
    event.shiftKey ||
    event.altKey ||
    event.button !== 0
  )
    return;
  if (
    ["/", "/validation", "/architecture"].includes(link.getAttribute("href"))
  ) {
    event.preventDefault();
    history.pushState({}, "", link.getAttribute("href"));
    navigate();
    window.scrollTo(0, 0);
  }
});
window.addEventListener("popstate", navigate);

async function poll() {
  try {
    if (!state.token) {
      const session = await api("/api/session");
      if (state.instanceToken && state.instanceToken !== session.token) {
        state.samples = [];
        state.events = [];
        state.sequence = 0;
        state.gap = false;
        renderEvents();
      }
      state.instanceToken = session.token;
      state.token = session.token;
      state.target = session.target;
      if (session.source_url) {
        const link = document.createElement("a");
        link.href = session.source_url;
        link.textContent = "GitHub source ↗";
        link.target = "_blank";
        link.rel = "noopener";
        $("#source-link").replaceChildren(link);
      }
    }
    await refreshSnapshot();
    await Promise.all([pollEvents(), pollRuns()]);
  } catch (error) {
    disconnected(error);
    state.token = null; // Re-establish a session after a local API restart.
  } finally {
    setTimeout(poll, 1000);
  }
}
navigate();
lockControls();
poll();

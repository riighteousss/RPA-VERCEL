const EXAMPLE_PAYLOAD = {
  movimientos: [
    {
      id_transaccion: "15835",
      fecha: "2026-09-08T01:40:00",
      cuenta_id: "800011",
      accion: "Deposit",
      monto_num: 1234,
      titular: null,
      tipo_cuenta: null,
      estado_cuenta: null,
      limite_monto: null,
      en_maestro: false,
      errores_negocio: "cuenta no registrada en el maestro",
      sugerencia: "Revisar de quien es la cuenta y agregarla al maestro",
      estado: "REVISAR"
    },
    {
      id_transaccion: "15834",
      fecha: "2026-09-08T01:37:00",
      cuenta_id: "800002",
      accion: "Withdrawal",
      monto_num: -250,
      titular: "John Smith",
      tipo_cuenta: "Savings",
      estado_cuenta: "Activa",
      limite_monto: 10000,
      en_maestro: true,
      errores_negocio: "",
      sugerencia: "",
      estado: "OK"
    }
  ]
};

const form = document.querySelector("#alert-form");
const secretInput = document.querySelector("#secret");
const payloadInput = document.querySelector("#payload");
const submitButton = document.querySelector("#submit-button");
const buttonLabel = document.querySelector("#button-label");
const result = document.querySelector("#result");
const resultIcon = document.querySelector("#result-icon");
const resultTitle = document.querySelector("#result-title");
const resultDetail = document.querySelector("#result-detail");
const dashboard = document.querySelector("#dashboard");
const movementFilter = document.querySelector("#movement-filter");
const fileInput = document.querySelector("#report-file");
const dropZone = document.querySelector("#drop-zone");
const fileStatus = document.querySelector("#file-status");
const apiSettings = document.querySelector("#api-settings");
let analyzedMovements = [];

document.querySelector("#load-example").addEventListener("click", () => {
  payloadInput.value = JSON.stringify(EXAMPLE_PAYLOAD, null, 2);
  setFileStatus("Datos de demostración cargados. Analízalos para ver el panel.");
  fileInput.value = "";
});

document.querySelector("#analyze-button").addEventListener("click", () => {
  try {
    showDashboard(parseMovements(payloadInput.value));
    showResult("Análisis local listo.", "Los datos se procesaron en este navegador; no se enviaron a la API.", false);
    dashboard.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    showResult("No se pudieron analizar los datos.", error.message, true);
  }
});

document.querySelector("#api-toggle").addEventListener("click", () => {
  apiSettings.hidden = !apiSettings.hidden;
  document.querySelector("#api-toggle").setAttribute("aria-expanded", String(!apiSettings.hidden));
  if (!apiSettings.hidden) secretInput.focus();
});

fileInput.addEventListener("change", () => {
  if (fileInput.files.length) loadReportFiles(Array.from(fileInput.files));
});

dropZone.addEventListener("dragover", (event) => {
  event.preventDefault();
  dropZone.classList.add("dragging");
});
dropZone.addEventListener("dragleave", () => dropZone.classList.remove("dragging"));
dropZone.addEventListener("drop", (event) => {
  event.preventDefault();
  dropZone.classList.remove("dragging");
  if (event.dataTransfer.files.length) loadReportFiles(Array.from(event.dataTransfer.files));
});

movementFilter.addEventListener("change", renderMovementTable);

function setFileStatus(message, isError = false) {
  fileStatus.textContent = message;
  fileStatus.classList.toggle("file-status-error", isError);
}

async function loadReportFiles(files) {
  try {
    if (files.some((file) => file.size > 5 * 1024 * 1024)) {
      throw new Error("Cada archivo debe pesar como máximo 5 MB.");
    }

    const reports = await Promise.all(files.map(async (file, index) => {
      const extension = file.name.split(".").pop().toLowerCase();
      const text = await file.text();
      let movements;
      if (extension === "csv") {
        movements = parseCsvMovements(text);
      } else if (extension === "json") {
        movements = parseMovements(text);
      } else {
        throw new Error(`El archivo "${file.name}" no es CSV ni JSON.`);
      }
      const reportName = `${index + 1}. ${file.name}`;
      return movements.map((movement) => ({ ...movement, _informe: reportName }));
    }));
    const movements = reports.flat();
    payloadInput.value = JSON.stringify({ movimientos: movements }, null, 2);
    setFileStatus(`${formatNumber(files.length)} informe(s) · ${formatNumber(movements.length)} movimientos listos para consolidar.`);
    fileInput.value = "";
    showDashboard(movements);
    showResult("Informes consolidados.", "Se analizaron en este navegador; no se enviaron al servidor.", false);
    dashboard.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    setFileStatus(error instanceof Error ? error.message : "No se pudo leer el archivo.", true);
    showResult("No se pudo cargar el informe.", error instanceof Error ? error.message : "Revisa el archivo e inténtalo de nuevo.", true);
    payloadInput.value = "";
    fileInput.value = "";
  }
}

function parseCsvMovements(value) {
  const text = value.replace(/^\uFEFF/, "");
  const rows = [];
  let row = [];
  let cell = "";
  let quoted = false;

  for (let index = 0; index < text.length; index += 1) {
    const character = text[index];
    if (quoted) {
      if (character === '"' && text[index + 1] === '"') {
        cell += '"';
        index += 1;
      } else if (character === '"') {
        quoted = false;
      } else {
        cell += character;
      }
    } else if (character === '"' && cell.length === 0) {
      quoted = true;
    } else if (character === ",") {
      row.push(cell);
      cell = "";
    } else if (character === "\n" || character === "\r") {
      row.push(cell);
      if (row.some((value) => value !== "")) rows.push(row);
      row = [];
      cell = "";
      if (character === "\r" && text[index + 1] === "\n") index += 1;
    } else {
      cell += character;
    }
  }

  if (quoted) throw new Error("El CSV contiene una celda con comillas sin cerrar.");
  row.push(cell);
  if (row.some((value) => value !== "")) rows.push(row);
  if (rows.length < 2) throw new Error("El CSV debe incluir encabezados y al menos un movimiento.");

  const headers = rows[0].map((header) => header.trim());
  const requiredHeaders = ["id_transaccion", "fecha", "cuenta_id", "monto_num", "estado"];
  const missingHeaders = requiredHeaders.filter((header) => !headers.includes(header));
  if (missingHeaders.length) {
    throw new Error(`No reconozco este CSV del robot EV2: faltan ${missingHeaders.join(", ")}.`);
  }

  return rows.slice(1).map((cells, index) => {
    if (cells.length !== headers.length) {
      throw new Error(`La fila ${index + 2} del CSV tiene un número de columnas distinto al encabezado.`);
    }
    const movement = {};
    headers.forEach((header, index) => {
      const value = (cells[index] ?? "").trim();
      if (value === "") {
        movement[header] = null;
      } else if (["monto_num", "limite_monto"].includes(header) && Number.isFinite(Number(value))) {
        movement[header] = Number(value);
      } else if (header === "en_maestro" && /^(true|false)$/i.test(value)) {
        movement[header] = value.toLowerCase() === "true";
      } else if (header === "estado") {
        movement[header] = value.toUpperCase();
      } else {
        movement[header] = value;
      }
    });
    return movement;
  });
}

function showResult(title, detail, isError = false) {
  result.hidden = false;
  result.classList.toggle("error", isError);
  resultIcon.textContent = isError ? "!" : "✓";
  resultTitle.textContent = title;
  resultDetail.textContent = detail;
}

function parseMovements(value) {
  const payload = JSON.parse(value);
  if (!payload || !Array.isArray(payload.movimientos)) {
    throw new Error("El JSON debe incluir una lista 'movimientos'.");
  }
  if (payload.movimientos.some((movement) => !movement || typeof movement !== "object" || Array.isArray(movement))) {
    throw new Error("Cada movimiento debe ser un objeto JSON.");
  }
  if (payload.movimientos.length === 0) {
    throw new Error("El informe no contiene movimientos para analizar.");
  }
  return payload.movimientos;
}

function hasAccountMissingFromMaster(movement) {
  const isMissing = movement.en_maestro === false
    || String(movement.en_maestro).trim().toLowerCase() === "false";
  const reportedText = `${movement.observaciones || ""};${movement.errores_negocio || ""}`
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
  return isMissing || reportedText.includes("cuenta no registrada en el maestro");
}

function getMovementIssues(movements) {
  const idCounts = new Map();
  for (const movement of movements) {
    const report = movement._informe || "Informe actual";
    const id = String(movement.id_transaccion ?? "").trim();
    const idKey = JSON.stringify([report, id]);
    if (id) idCounts.set(idKey, (idCounts.get(idKey) || 0) + 1);
  }

  return movements.map((movement) => {
    const normalizeIssue = (issue) => issue.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
    const issues = [];
    const observations = String(movement.observaciones || "")
      .split(";")
      .map((issue) => issue.trim())
      .filter(Boolean);
    const reportedIssues = String(movement.errores_negocio || "")
      .split(";")
      .map((issue) => issue.trim())
      .filter(Boolean);
    let ignoredLowConfidenceDuplicate = false;
    const addIssue = (issue) => {
      if (!issues.some((existing) => normalizeIssue(existing) === normalizeIssue(issue))) issues.push(issue);
    };
    const addObservation = (issue) => {
      if (!observations.some((existing) => normalizeIssue(existing) === normalizeIssue(issue))) observations.push(issue);
    };

    for (const issue of reportedIssues) {
      const normalized = normalizeIssue(issue);
      if (normalized === "posible movimiento duplicado") {
        ignoredLowConfidenceDuplicate = true;
      } else if (normalized === "cuenta no registrada en el maestro") {
        addObservation(issue);
      } else {
        addIssue(issue);
      }
    }

    const id = String(movement.id_transaccion ?? "").trim();
    const report = movement._informe || "Informe actual";
    const idKey = JSON.stringify([report, id]);
    if (id && idCounts.get(idKey) > 1) addIssue("id de transacción duplicado");

    if (movement.cuenta_id === null || movement.cuenta_id === undefined || !String(movement.cuenta_id).trim()) {
      addIssue("cuenta ausente");
    }
    const accountNotInMaster = hasAccountMissingFromMaster(movement);
    if (accountNotInMaster) addObservation("cuenta no registrada en el maestro");
    const accountState = String(movement.estado_cuenta ?? "").trim().toLowerCase();
    if (!accountNotInMaster && accountState && accountState !== "activa") {
      addIssue("cuenta inactiva en el maestro");
    }

    const amount = Number(movement.monto_num);
    if (movement.monto_num !== null && movement.monto_num !== "" && typeof movement.monto_num !== "boolean" && Number.isFinite(amount)) {
      const hasConfiguredLimit = movement.limite_monto !== null && movement.limite_monto !== "";
      const configuredLimit = Number(movement.limite_monto);
      const validLimit = !hasConfiguredLimit || (typeof movement.limite_monto !== "boolean" && Number.isFinite(configuredLimit));
      const limit = hasConfiguredLimit && validLimit ? configuredLimit : 5000;
      if (!validLimit) addIssue("límite inválido");
      if (Math.abs(amount) > limit) addIssue("monto sobre el límite");
      else if (Math.abs(amount) < 0.01) addIssue("monto en cero");

      const action = String(movement.accion || "").trim().toLowerCase();
      if ((action === "deposit" && amount < 0) || (action === "withdrawal" && amount > 0)) {
        addIssue("signo no coincide con la acción");
      }
    } else if (movement.monto_num !== null && movement.monto_num !== undefined && movement.monto_num !== "") {
      addIssue("monto inválido");
    }

    const date = movement.fecha ? new Date(movement.fecha) : null;
    if (date && !Number.isFinite(date.getTime())) {
      addIssue("fecha inválida");
    } else if (date) {
      date.setHours(0, 0, 0, 0);
      const today = new Date();
      today.setHours(0, 0, 0, 0);
      if (date > today) addIssue("fecha futura");
    } else {
      addIssue("fecha ausente");
    }
    if (movement.estado === "REVISAR" && issues.length === 0
      && observations.length === 0 && !ignoredLowConfidenceDuplicate) {
      addIssue("marcado REVISAR por el robot");
    }
    if (movement.estado !== "OK" && movement.estado !== "REVISAR") addIssue("estado inválido o ausente");

    return { issues, observations };
  });
}

function formatNumber(value) {
  return new Intl.NumberFormat("es", { maximumFractionDigits: 2 }).format(value);
}

function parseAmount(value) {
  if (value === null || value === undefined || value === "" || typeof value === "boolean") return null;
  const amount = Number(value);
  return Number.isFinite(amount) ? amount : null;
}

function showDashboard(movements) {
  const movementIssues = getMovementIssues(movements);
  analyzedMovements = movements.map((movement, index) => ({
    movement,
    issues: movementIssues[index].issues,
    observations: movementIssues[index].observations,
    flagged: movementIssues[index].issues.length > 0
  }));
  dashboard.hidden = false;

  const flagged = analyzedMovements.filter((item) => item.flagged);
  const observedOnly = analyzedMovements.filter((item) => !item.flagged && item.observations.length > 0);
  const totalAmount = movements.reduce((sum, movement) => {
    const amount = parseAmount(movement.monto_num);
    return amount === null ? sum : sum + amount;
  }, 0);
  const accounts = new Set(movements.map((movement) => movement.cuenta_id).filter((account) => account !== null && account !== undefined && String(account).trim()));
  const unregisteredAccounts = new Set(movements
    .filter(hasAccountMissingFromMaster)
    .map((movement) => String(movement.cuenta_id ?? "").trim())
    .filter((account) => account !== null && account !== undefined && String(account).trim()));
  const reports = new Set(movements.map((movement) => movement._informe || "Informe actual"));

  document.querySelector("#metric-reports").textContent = formatNumber(reports.size);
  document.querySelector("#metric-total").textContent = formatNumber(movements.length);
  document.querySelector("#metric-review").textContent = formatNumber(flagged.length);
  document.querySelector("#metric-amount").textContent = formatNumber(totalAmount);
  document.querySelector("#metric-accounts").textContent = formatNumber(accounts.size);
  document.querySelector("#metric-unregistered").textContent = formatNumber(unregisteredAccounts.size);
  document.querySelector("#dashboard-count").textContent = `${formatNumber(flagged.length)} de ${formatNumber(movements.length)} para revisar · ${formatNumber(reports.size)} informe(s)`;
  document.querySelector("#review-count").textContent = `${formatNumber(flagged.length)} hallazgo(s) crítico(s)`;

  renderBarChart(document.querySelector("#status-chart"), [
    { label: "OK", value: movements.length - flagged.length - observedOnly.length, className: "bar-ok" },
    { label: "Observación", value: observedOnly.length, className: "bar-info" },
    { label: "Para revisar", value: flagged.length, className: "bar-warning" }
  ]);
  const reasonCounts = new Map();
  for (const item of analyzedMovements) {
    for (const issue of new Set(item.issues)) reasonCounts.set(issue, (reasonCounts.get(issue) || 0) + 1);
  }
  renderBarChart(
    document.querySelector("#reason-chart"),
    [...reasonCounts].sort((a, b) => b[1] - a[1]).slice(0, 6)
      .map(([label, value]) => ({ label, value, className: "bar-warning" }))
  );
  renderAccountObservations(movements);
  renderMovementTable();
  renderReviewTable();
}

function renderAccountObservations(movements) {
  const counts = new Map();
  for (const movement of movements) {
    const notInMaster = hasAccountMissingFromMaster(movement);
    const account = String(movement.cuenta_id ?? "").trim();
    if (!notInMaster || !account) continue;
    counts.set(account, (counts.get(account) || 0) + 1);
  }

  const panel = document.querySelector("#account-observations");
  const list = document.querySelector("#account-observations-list");
  list.replaceChildren();
  panel.hidden = counts.size === 0;
  if (!counts.size) return;

  const movementCount = [...counts.values()].reduce((sum, count) => sum + count, 0);
  document.querySelector("#account-observations-count").textContent =
    `${formatNumber(counts.size)} cuenta(s) · ${formatNumber(movementCount)} movimiento(s)`;
  document.querySelector("#account-observations-summary").textContent =
    "Confirma si estas cuentas deben incorporarse al maestro. Se muestran como observación informativa y no cuentan como alertas críticas por sí solas.";
  for (const [account, count] of [...counts].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))) {
    const item = document.createElement("li");
    item.textContent = `Cuenta ${account}: ${formatNumber(count)} movimiento(s)`;
    list.append(item);
  }
}

function renderBarChart(container, items) {
  container.replaceChildren();
  if (!items.length || items.every((item) => item.value === 0)) {
    const empty = document.createElement("p");
    empty.className = "chart-empty";
    empty.textContent = "Sin datos para mostrar.";
    container.append(empty);
    return;
  }

  const max = Math.max(...items.map((item) => item.value), 1);
  for (const item of items) {
    const row = document.createElement("div");
    row.className = "bar-row";
    const label = document.createElement("span");
    label.className = "bar-label";
    label.textContent = item.label;
    const track = document.createElement("div");
    track.className = "bar-track";
    const bar = document.createElement("span");
    bar.className = `bar-fill ${item.className}`;
    bar.style.width = `${Math.max((item.value / max) * 100, item.value > 0 ? 3 : 0)}%`;
    track.append(bar);
    const value = document.createElement("strong");
    value.className = "bar-value";
    value.textContent = formatNumber(item.value);
    row.append(label, track, value);
    container.append(row);
  }
}

function appendCell(row, value, className = "") {
  const cell = document.createElement("td");
  if (className) cell.className = className;
  cell.textContent = value === null || value === undefined ? "—" : String(value);
  row.append(cell);
  return cell;
}

function renderMovementTable() {
  const rows = document.querySelector("#movement-rows");
  rows.replaceChildren();
  const filter = movementFilter.value;
  for (const item of analyzedMovements) {
    if (filter === "review" && !item.flagged) continue;
    if (filter === "observations" && (!item.observations.length || item.flagged)) continue;
    if (filter === "ok" && (item.flagged || item.observations.length)) continue;
    const row = document.createElement("tr");
    if (item.flagged) row.className = "flagged-row";
    else if (item.observations.length) row.className = "observation-row";
    appendCell(row, item.movement.id_transaccion);
    appendCell(row, item.movement._informe || "Informe actual");
    appendCell(row, item.movement.fecha);
    appendCell(row, item.movement.cuenta_id);
    appendCell(row, item.movement.accion);
    const amount = parseAmount(item.movement.monto_num);
    appendCell(row, amount === null ? item.movement.monto_num : formatNumber(amount), "numeric-cell");
    const stateLabel = item.flagged ? "REVISAR" : item.observations.length ? "OBSERVAR" : "OK";
    const state = appendCell(row, stateLabel);
    state.className = `status-cell ${item.flagged ? "status-review" : item.observations.length ? "status-info" : "status-ok"}`;
    appendCell(row, [...item.issues, ...item.observations].join("; ") || "—");
    rows.append(row);
  }
  if (!rows.children.length) {
    const row = document.createElement("tr");
    const cell = appendCell(row, "No hay movimientos para este filtro.");
    cell.colSpan = 8;
    cell.className = "empty-cell";
    rows.append(row);
  }
}

function renderReviewTable() {
  const flagged = analyzedMovements.filter((item) => item.flagged);
  const rows = document.querySelector("#review-rows");
  const empty = document.querySelector("#review-empty");
  const table = document.querySelector("#review-table-wrap");
  rows.replaceChildren();
  empty.hidden = flagged.length > 0;
  table.hidden = flagged.length === 0;
  for (const item of flagged) {
    const row = document.createElement("tr");
    appendCell(row, item.movement.id_transaccion);
    appendCell(row, item.movement._informe || "Informe actual");
    appendCell(row, item.movement.cuenta_id);
    const amount = parseAmount(item.movement.monto_num);
    appendCell(row, amount === null ? item.movement.monto_num : formatNumber(amount), "numeric-cell");
    appendCell(row, item.issues.join("; "));
    appendCell(row, item.movement.sugerencia || "Revisar el movimiento con el responsable de la cuenta.");
    rows.append(row);
  }
}

function downloadCsv(blob) {
  const file = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = file;
  link.download = "reporte_movimientos_ev2.csv";
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(file), 1000);
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  result.hidden = true;
  if (!secretInput.value.trim()) {
    showResult("Falta el secreto de la API.", "Ábrelo en “Generar CSV en Vercel” e ingresa ALERT_API_SECRET. Para revisar datos no necesitas el secreto.", true);
    return;
  }

  let payload;

  try {
    payload = { movimientos: parseMovements(payloadInput.value) };
    showDashboard(parseMovements(payloadInput.value));
  } catch (error) {
    showResult(
      "El informe no es válido.",
      error instanceof Error ? error.message : "Revisa el formato del contenido e inténtalo de nuevo.",
      true
    );
    return;
  }

  submitButton.disabled = true;
  buttonLabel.textContent = "Procesando reporte...";

  try {
    const response = await fetch("/api/alerta", {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${secretInput.value}`,
        "Content-Type": "application/json"
      },
      body: JSON.stringify(payload)
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.error || `La API respondió con HTTP ${response.status}.`);
    }

    const blob = await response.blob();
    downloadCsv(blob);
    showResult("Reporte CSV generado y descargado.", "El CSV se generó en Vercel. La revisión de datos permanece en este panel.");
  } catch (error) {
    showResult(
      "No se pudo generar el CSV.",
      error instanceof Error ? error.message : "Error inesperado al conectar con la API. El análisis local sigue disponible.",
      true
    );
  } finally {
    submitButton.disabled = false;
    buttonLabel.textContent = "Generar CSV";
  }
});

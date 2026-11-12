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
const emailForm = document.querySelector("#partner-email-form");
let analyzedMovements = [];

document.querySelector("#load-example").addEventListener("click", () => {
  payloadInput.value = JSON.stringify(EXAMPLE_PAYLOAD, null, 2);
  payloadInput.focus();
});

document.querySelector("#analyze-button").addEventListener("click", () => {
  try {
    showDashboard(parseMovements(payloadInput.value));
    showResult("Análisis local listo.", "Los datos se procesaron en este navegador; no se enviaron a la API.", false);
  } catch (error) {
    showResult("No se pudieron analizar los datos.", error.message, true);
  }
});

movementFilter.addEventListener("change", renderMovementTable);
emailForm.addEventListener("submit", preparePartnerEmail);

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
  return payload.movimientos;
}

function getMovementIssues(movements) {
  const idCounts = new Map();
  const duplicateCounts = new Map();
  for (const movement of movements) {
    const id = String(movement.id_transaccion ?? "").trim();
    if (id) idCounts.set(id, (idCounts.get(id) || 0) + 1);
    const key = JSON.stringify([
      movement.fecha,
      movement.cuenta_id,
      movement.accion,
      movement.monto_num
    ]);
    duplicateCounts.set(key, (duplicateCounts.get(key) || 0) + 1);
  }

  return movements.map((movement) => {
    const issues = String(movement.errores_negocio || "")
      .split(";")
      .map((issue) => issue.trim())
      .filter(Boolean);
    const normalizeIssue = (issue) => issue.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
    const addIssue = (issue) => {
      if (!issues.some((existing) => normalizeIssue(existing) === normalizeIssue(issue))) issues.push(issue);
    };

    const id = String(movement.id_transaccion ?? "").trim();
    if (id && idCounts.get(id) > 1) addIssue("id de transacción duplicado");
    const duplicateKey = JSON.stringify([
      movement.fecha,
      movement.cuenta_id,
      movement.accion,
      movement.monto_num
    ]);
    if (duplicateCounts.get(duplicateKey) > 1) addIssue("posible movimiento duplicado");

    if (movement.cuenta_id === null || movement.cuenta_id === undefined || !String(movement.cuenta_id).trim()) {
      addIssue("cuenta ausente");
    }
    if (movement.en_maestro === false) {
      addIssue("cuenta no registrada en el maestro");
    } else if (String(movement.estado_cuenta ?? "").trim().toLowerCase() !== "activa") {
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
    if (movement.estado === "REVISAR" && issues.length === 0) addIssue("marcado REVISAR por el robot");
    if (movement.estado !== "OK" && movement.estado !== "REVISAR") addIssue("estado inválido o ausente");

    return issues;
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
    issues: movementIssues[index],
    flagged: movementIssues[index].length > 0 || movement.estado === "REVISAR"
  }));
  dashboard.hidden = false;

  const flagged = analyzedMovements.filter((item) => item.flagged);
  const totalAmount = movements.reduce((sum, movement) => {
    const amount = parseAmount(movement.monto_num);
    return amount === null ? sum : sum + amount;
  }, 0);
  const accounts = new Set(movements.map((movement) => movement.cuenta_id).filter((account) => account !== null && account !== undefined && String(account).trim()));

  document.querySelector("#metric-total").textContent = formatNumber(movements.length);
  document.querySelector("#metric-review").textContent = formatNumber(flagged.length);
  document.querySelector("#metric-amount").textContent = formatNumber(totalAmount);
  document.querySelector("#metric-accounts").textContent = formatNumber(accounts.size);
  document.querySelector("#dashboard-count").textContent = `${formatNumber(flagged.length)} de ${formatNumber(movements.length)} para revisar`;
  document.querySelector("#review-count").textContent = `${formatNumber(flagged.length)} hallazgo(s)`;

  renderBarChart(document.querySelector("#status-chart"), [
    { label: "OK", value: movements.length - flagged.length, className: "bar-ok" },
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
  renderMovementTable();
  renderReviewTable();
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
    if (filter === "ok" && item.flagged) continue;
    const row = document.createElement("tr");
    if (item.flagged) row.className = "flagged-row";
    appendCell(row, item.movement.id_transaccion);
    appendCell(row, item.movement.fecha);
    appendCell(row, item.movement.cuenta_id);
    appendCell(row, item.movement.accion);
    const amount = parseAmount(item.movement.monto_num);
    appendCell(row, amount === null ? item.movement.monto_num : formatNumber(amount), "numeric-cell");
    const state = appendCell(row, item.flagged ? "REVISAR" : "OK");
    state.className = item.flagged ? "status-cell status-review" : "status-cell status-ok";
    appendCell(row, item.issues.join("; ") || "—");
    rows.append(row);
  }
  if (!rows.children.length) {
    const row = document.createElement("tr");
    const cell = appendCell(row, "No hay movimientos para este filtro.");
    cell.colSpan = 7;
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
    appendCell(row, item.movement.cuenta_id);
    const amount = parseAmount(item.movement.monto_num);
    appendCell(row, amount === null ? item.movement.monto_num : formatNumber(amount), "numeric-cell");
    appendCell(row, item.issues.join("; "));
    appendCell(row, item.movement.sugerencia || "Revisar el movimiento con el responsable de la cuenta.");
    rows.append(row);
  }
}

function preparePartnerEmail(event) {
  event.preventDefault();
  const status = document.querySelector("#email-result");
  const recipients = document.querySelector("#partner-emails").value
    .split(/[;,\s]+/)
    .map((email) => email.trim())
    .filter(Boolean);
  const validEmail = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  if (!recipients.length || recipients.some((email) => !validEmail.test(email))) {
    status.textContent = "Ingresa uno o más correos válidos, separados por coma o punto y coma.";
    status.classList.add("email-error");
    return;
  }

  const flagged = analyzedMovements.filter((item) => item.flagged);
  const shortValue = (value) => String(value ?? "—").replace(/[\r\n]+/g, " ").slice(0, 80);
  const detailLines = flagged.slice(0, 15).map(({ movement, issues }) =>
    `- ID ${shortValue(movement.id_transaccion)} | cuenta ${shortValue(movement.cuenta_id)} | monto ${shortValue(movement.monto_num)} | ${shortValue(issues.join("; "))}`
  );
  const omittedCount = flagged.length - detailLines.length;
  if (omittedCount > 0) {
    detailLines.push(`- y ${omittedCount} movimiento(s) adicional(es); consulta el reporte completo.`);
  }
  const note = document.querySelector("#follow-up-note").value.trim();
  const body = [
    "Hola,",
    "",
    note || "Solicito revisar los movimientos señalados y confirmar los próximos pasos.",
    "",
    `Resumen EV2: ${flagged.length} de ${analyzedMovements.length} movimiento(s) requieren revisión.`,
    ...(detailLines.length ? ["", ...detailLines] : ["", "No hay hallazgos detectados; solicito confirmar si hace falta algún seguimiento."]),
    "",
    "Este borrador fue preparado desde el panel EV2."
  ].join("\n");
  const subject = `Solicitud de revisión/seguimiento EV2 (${flagged.length} hallazgo(s))`;
  const mailto = `mailto:${recipients.map(encodeURIComponent).join(",")}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
  status.classList.remove("email-error");
  status.textContent = "Se solicitará a tu aplicación de correo que abra un borrador; el mensaje no se envía automáticamente.";
  window.location.href = mailto;
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
  let payload;

  try {
    payload = JSON.parse(payloadInput.value);
    showDashboard(parseMovements(payloadInput.value));
  } catch (error) {
    showResult(
      "El JSON no es válido.",
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
    const email = response.headers.get("X-Alert-Email");
    showResult(
      "Reporte CSV generado y descargado.",
      email === "enviado"
        ? "Se detectaron movimientos REVISAR y la API confirmó el envío de la alerta configurada."
        : "La API no recibió movimientos con estado REVISAR; no envió alertas automáticas. Revisa también los hallazgos del análisis local."
    );
  } catch (error) {
    showResult(
      "No se pudo procesar el reporte.",
      error instanceof Error ? error.message : "Error inesperado al conectar con la API. El análisis local sigue disponible.",
      true
    );
  } finally {
    submitButton.disabled = false;
    buttonLabel.textContent = "Analizar y generar reporte";
  }
});

payloadInput.value = JSON.stringify(EXAMPLE_PAYLOAD, null, 2);

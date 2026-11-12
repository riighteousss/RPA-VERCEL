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

document.querySelector("#load-example").addEventListener("click", () => {
  payloadInput.value = JSON.stringify(EXAMPLE_PAYLOAD, null, 2);
  payloadInput.focus();
});

function showResult(title, detail, isError = false) {
  result.hidden = false;
  result.classList.toggle("error", isError);
  resultIcon.textContent = isError ? "!" : "✓";
  resultTitle.textContent = title;
  resultDetail.textContent = detail;
}

function downloadCsv(response, blob) {
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
  } catch {
    showResult("El JSON no es valido.", "Revisa el formato del contenido e intentalo de nuevo.", true);
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
      throw new Error(error.error || `La API respondio con HTTP ${response.status}.`);
    }

    const blob = await response.blob();
    downloadCsv(response, blob);
    const email = response.headers.get("X-Alert-Email");
    showResult(
      "Reporte CSV generado y descargado.",
      email === "enviado"
        ? "Se detectaron movimientos REVISAR y se envio la alerta por correo."
        : "No hay movimientos REVISAR; no se envio ningun correo."
    );
  } catch (error) {
    showResult(
      "No se pudo procesar el reporte.",
      error instanceof Error ? error.message : "Error inesperado al conectar con la API.",
      true
    );
  } finally {
    submitButton.disabled = false;
    buttonLabel.textContent = "Analizar y generar reporte";
  }
});

payloadInput.value = JSON.stringify(EXAMPLE_PAYLOAD, null, 2);

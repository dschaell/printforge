const $ = (id) => document.getElementById(id);
let file,
  previewUrl,
  health,
  plan,
  busy = false;
const presets = {
  A0: [84.1, 118.9],
  A1: [59.4, 84.1],
  A2: [42, 59.4],
  A3: [29.7, 42],
  A4: [21, 29.7],
  A5: [14.8, 21],
};
const status = (message) => {
  $("status").textContent = message;
};
function invalidate() {
  if (file)
    status("Einstellungen geändert. Druckfähigkeit erneut analysieren.");
  plan = null;
  $("download").disabled = true;
  $("metrics").hidden = true;
  $("warnings").replaceChildren();
  $("paper").style.aspectRatio = `${$("width").value}/${$("height").value}`;
  $("preview").style.objectFit = $("fit").value;
}
function setBusy(value) {
  busy = value;
  $("analyze").disabled = value;
  $("download").disabled = value || !plan;
  for (const el of document.querySelectorAll("input,select,#rotate"))
    el.disabled = value;
}
$("file").addEventListener("change", () => {
  file = $("file").files[0];
  invalidate();
  if (previewUrl) URL.revokeObjectURL(previewUrl);
  if (file) {
    previewUrl = URL.createObjectURL(file);
    $("preview").src = previewUrl;
    $("preview").hidden = false;
    status("Motiv geladen. Druckfähigkeit analysieren.");
  }
});
$("preset").addEventListener("change", () => {
  const size = presets[$("preset").value];
  if (size) {
    [$("width").value, $("height").value] = size;
  }
  invalidate();
});
for (const id of ["width", "height", "ppi", "fit", "format"])
  $(id).addEventListener("input", () => {
    if (["width", "height"].includes(id)) $("preset").value = "custom";
    invalidate();
  });
$("rotate").addEventListener("click", () => {
  [$("width").value, $("height").value] = [$("height").value, $("width").value];
  invalidate();
});
async function request(action) {
  const params = new URLSearchParams({
    width_cm: $("width").value,
    height_cm: $("height").value,
    ppi: $("ppi").value,
    fit: $("fit").value,
    output_format: $("format").value,
  });
  const response = await fetch(`/api/${action}?${params}`, {
    method: "POST",
    headers: { "Content-Type": "application/octet-stream" },
    body: file,
  });
  if (!response.ok) {
    let message = "Verarbeitung fehlgeschlagen.";
    try {
      const error = await response.json();
      message =
        typeof error.detail === "string"
          ? error.detail
          : "Bitte Druckmaße und Datei prüfen.";
    } catch {}
    throw new Error(message);
  }
  return response;
}
$("settings").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!file || busy) {
    status("Bitte zuerst ein Bild wählen.");
    return;
  }
  invalidate();
  setBusy(true);
  status("Bild und Druckmaß werden geprüft …");
  try {
    const data = await (await request("plan")).json();
    plan = data.plan;
    const metrics = [
      ["Original", `${plan.source_width} × ${plan.source_height} px`],
      ["Druckdatei", `${plan.target_width} × ${plan.target_height} px`],
      ["Original am Druckmaß", `${plan.source_ppi} PPI`],
      ["Vergrößerung", `${plan.required_scale.toFixed(2)}×`],
      ["Beschnitt", `${plan.crop_percent} %`],
      ["Zielauflösung", `${$("ppi").value} PPI`],
    ];
    $("metrics").replaceChildren();
    for (const [label, value] of metrics) {
      const div = document.createElement("div"),
        dt = document.createElement("dt"),
        dd = document.createElement("dd");
      dt.textContent = label;
      dd.textContent = value;
      div.append(dt, dd);
      $("metrics").append(div);
    }
    $("metrics").hidden = false;
    for (const warning of plan.warnings) {
      const li = document.createElement("li");
      li.textContent = warning;
      $("warnings").append(li);
    }
    const allowed =
      plan.required_scale <= 4 &&
      (!plan.ai_passes ||
        (health?.upscayl_available &&
          plan.source_width * plan.source_height * 16 <= 120000000));
    status(
      allowed
        ? "Berechnung fertig. Druckdatei kann erstellt werden."
        : "Export aktuell blockiert: Upscayl-Konfiguration oder Größenlimit prüfen.",
    );
    if (!allowed) plan = null;
  } catch (error) {
    status(error.message);
    plan = null;
  } finally {
    setBusy(false);
  }
});
$("download").addEventListener("click", async () => {
  if (!file || !plan || busy) return;
  setBusy(true);
  status("Druckdatei wird erstellt. Upscayl kann mehrere Minuten benötigen …");
  try {
    const response = await request("render");
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = `printforge-${$("ppi").value}ppi.${$("format").value}`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
    status(
      "Druckdatei heruntergeladen. Vor dem Druck tatsächliche Größe wählen.",
    );
  } catch (error) {
    status(error.message);
  } finally {
    setBusy(false);
  }
});
fetch("/api/health")
  .then((r) => r.json())
  .then((data) => {
    health = data;
    $("engine").textContent = data.upscayl_available
      ? "● Upscayl verbunden"
      : "○ Upscayl nicht konfiguriert";
  })
  .catch(() => {
    $("engine").textContent = "○ Server nicht erreichbar";
  });
invalidate();

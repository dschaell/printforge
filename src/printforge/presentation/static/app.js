const $ = (id) => document.getElementById(id);
let file,
  previewUrl,
  health,
  plan,
  busy = false,
  compareUrls = [];
const number = new Intl.NumberFormat("de-DE", { maximumFractionDigits: 2 });
const status = (message) => {
  $("status").textContent = message;
};

/** Pure: true when the paper must be turned to match the image orientation. */
function needsRotation(imageW, imageH, paperW, paperH) {
  if (imageW === imageH || paperW === paperH) return false;
  return imageW > imageH !== paperW > paperH;
}
window.printforge = { needsRotation };

function swapPaper() {
  [$("width").value, $("height").value] = [$("height").value, $("width").value];
}
function setPpi(value) {
  const text = String(value);
  if (![...$("ppi").options].some((o) => o.value === text || o.text === text)) {
    const option = new Option(text, text);
    const next = [...$("ppi").options].find((o) => Number(o.value) > value);
    $("ppi").add(option, next ?? null);
  }
  $("ppi").value = text;
}
function clearCompare() {
  for (const url of compareUrls) URL.revokeObjectURL(url);
  compareUrls = [];
  $("compare-out").replaceChildren();
  $("compare-out").hidden = true;
}
function hideSuggestion() {
  $("suggest").hidden = true;
  delete $("suggest").dataset.ppi;
}
function suggest(ppi) {
  $("suggest").dataset.ppi = ppi;
  $("suggest").textContent = `Auf ${ppi} PPI setzen und neu analysieren`;
  $("suggest").hidden = false;
}
function invalidate() {
  if (file)
    status("Einstellungen geändert. Druckfähigkeit erneut analysieren.");
  plan = null;
  $("download").disabled = true;
  $("compare").disabled = true;
  $("metrics").hidden = true;
  $("quality").hidden = true;
  $("warnings").replaceChildren();
  hideSuggestion();
  clearCompare();
  $("paper").style.aspectRatio = `${$("width").value}/${$("height").value}`;
  $("preview").style.objectFit = $("fit").value;
}
function setBusy(value) {
  busy = value;
  $("analyze").disabled = value;
  $("download").disabled = value || !plan;
  $("compare").disabled = value || !plan;
  $("suggest").disabled = value;
  for (const el of document.querySelectorAll("input,select,#rotate"))
    el.disabled = value;
}

function loadFile(selected) {
  file = selected;
  invalidate();
  if (previewUrl) URL.revokeObjectURL(previewUrl);
  if (!file) {
    $("filename").textContent = "Noch keine Datei gewählt";
    return;
  }
  $("filename").textContent =
    `${file.name} · ${number.format(file.size / 1048576)} MiB`;
  previewUrl = URL.createObjectURL(file);
  $("preview").src = previewUrl;
  $("preview").hidden = false;
  status("Motiv geladen. Druckfähigkeit analysieren.");
}
$("preview").addEventListener("load", () => {
  const { naturalWidth: w, naturalHeight: h } = $("preview");
  if (needsRotation(w, h, +$("width").value, +$("height").value)) {
    swapPaper();
    invalidate();
    status(
      `Papier ins ${h > w ? "Hoch" : "Quer"}format gedreht, passend zum Bild. ⇄ dreht zurück.`,
    );
  }
});
$("file").addEventListener("change", () => loadFile($("file").files[0]));

const drop = $("drop");
for (const type of ["dragenter", "dragover"])
  drop.addEventListener(type, (event) => {
    event.preventDefault();
    drop.classList.add("over");
  });
for (const type of ["dragleave", "drop"])
  drop.addEventListener(type, () => drop.classList.remove("over"));
drop.addEventListener("drop", (event) => {
  event.preventDefault();
  if (busy) return;
  const dropped = event.dataTransfer?.files?.[0];
  if (!dropped || !dropped.type.startsWith("image/")) {
    status("Bitte eine Bilddatei (JPEG, PNG, WebP oder TIFF) ablegen.");
    return;
  }
  const transfer = new DataTransfer();
  transfer.items.add(dropped);
  $("file").files = transfer.files;
  loadFile(dropped);
});

function fillPresets(presets) {
  const custom = $("preset").querySelector('option[value="custom"]');
  for (const [name, [w, h]] of Object.entries(presets)) {
    const size = `${number.format(w)} × ${number.format(h)} cm`;
    const label = name.includes("×") ? `Poster ${size}` : `${name} — ${size}`;
    const option = new Option(label, name);
    $("preset").insertBefore(option, custom);
  }
  health.presets = presets;
  if (presets.A4) {
    $("preset").value = "A4";
    if (!file) [$("width").value, $("height").value] = presets.A4;
    invalidate();
  }
}
$("preset").addEventListener("change", () => {
  const size = health?.presets?.[$("preset").value];
  if (size) {
    // Keep the current orientation (landscape stays landscape).
    const landscape = +$("width").value > +$("height").value;
    const [short, long] = [...size].sort((a, b) => a - b);
    [$("width").value, $("height").value] = landscape
      ? [long, short]
      : [short, long];
  }
  invalidate();
});
for (const id of ["width", "height", "ppi", "fit", "format", "bleed"])
  $(id).addEventListener("input", () => {
    if (["width", "height"].includes(id)) $("preset").value = "custom";
    invalidate();
  });
$("rotate").addEventListener("click", () => {
  swapPaper();
  invalidate();
});

async function request(action, extra = {}) {
  const params = new URLSearchParams({
    width_cm: $("width").value,
    height_cm: $("height").value,
    ppi: $("ppi").value,
    fit: $("fit").value,
    output_format: $("format").value,
    bleed_mm: $("bleed").value || "0",
    ...extra,
  });
  const response = await fetch(`/api/${action}?${params}`, {
    method: "POST",
    headers: { "Content-Type": "application/octet-stream" },
    body: file,
  });
  if (!response.ok) {
    let message = "Verarbeitung fehlgeschlagen.";
    let suggestedPpi;
    try {
      const error = await response.json();
      message =
        typeof error.detail === "string"
          ? error.detail
          : "Bitte Druckmaße und Datei prüfen.";
      suggestedPpi = error.suggested_ppi;
    } catch {}
    throw Object.assign(new Error(message), { suggestedPpi });
  }
  return response;
}
function showMetrics() {
  const bleed = +$("bleed").value || 0;
  const metrics = [
    ["Original", `${plan.source_width} × ${plan.source_height} px`],
    ["Druckdatei", `${plan.target_width} × ${plan.target_height} px`],
    ["Original am Druckmaß", `${plan.source_ppi} PPI`],
    ["Vergrößerung", `${plan.required_scale.toFixed(2)}×`],
    ["Bildanteil abgeschnitten", `${plan.crop_percent} %`],
    ["Zielauflösung", `${$("ppi").value} PPI`],
  ];
  if (bleed > 0)
    metrics.push([
      "Gesamtmaß inkl. Anschnitt",
      `${number.format(+$("width").value + bleed / 5)} × ${number.format(+$("height").value + bleed / 5)} cm`,
    ]);
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
  $("quality").dataset.level = plan.quality;
  const badge = document.createElement("strong");
  badge.textContent = `Qualität: ${plan.quality}`;
  const text = document.createElement("span");
  text.textContent = plan.quality_text;
  $("quality").replaceChildren(badge, text);
  $("quality").hidden = false;
  for (const warning of plan.warnings) {
    const li = document.createElement("li");
    li.textContent = warning;
    $("warnings").append(li);
  }
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
    showMetrics();
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
    if (plan.suggested_ppi) suggest(plan.suggested_ppi);
    if (!allowed) plan = null;
  } catch (error) {
    status(error.message);
    if (error.suggestedPpi) suggest(error.suggestedPpi);
    plan = null;
  } finally {
    setBusy(false);
  }
});
$("suggest").addEventListener("click", () => {
  const ppi = Number($("suggest").dataset.ppi);
  if (!ppi || busy) return;
  setPpi(ppi);
  $("settings").requestSubmit();
});

async function sample(method, caption) {
  const blob = await (await request("sample", { method })).blob();
  const url = URL.createObjectURL(blob);
  compareUrls.push(url);
  const figure = document.createElement("figure"),
    img = document.createElement("img"),
    figcaption = document.createElement("figcaption");
  img.src = url;
  img.alt = `100-%-Ausschnitt: ${caption}`;
  figcaption.textContent = caption;
  figure.append(img, figcaption);
  $("compare-out").append(figure);
  $("compare-out").hidden = false;
}
$("compare").addEventListener("click", async () => {
  if (!file || !plan || busy) return;
  const useAi = health?.upscayl_available && plan.ai_passes;
  const kept = plan;
  clearCompare();
  setBusy(true);
  status("Detailvergleich wird berechnet …");
  try {
    await sample("plain", "Interpolation (ohne KI)");
    if (useAi) await sample("ai", "Upscayl (KI)");
    else {
      const note = document.createElement("p");
      note.textContent = kept.ai_passes
        ? "Upscayl nicht verfügbar: nur Interpolation gezeigt."
        : "Keine Vergrößerung nötig: kein KI-Vergleich.";
      $("compare-out").append(note);
    }
    status("Detailvergleich fertig. Ausschnitt in tatsächlicher Pixelgröße.");
  } catch (error) {
    status(error.message);
  } finally {
    plan = kept;
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
    fillPresets(data.presets);
    $("engine").textContent = data.upscayl_available
      ? "● Upscayl verbunden"
      : "○ Upscayl nicht konfiguriert";
  })
  .catch(() => {
    $("engine").textContent = "○ Server nicht erreichbar";
  });
invalidate();

import * as OBC from "@thatopen/components";
import * as OBF from "@thatopen/components-front";
import * as THREE from "three";
import "./style.css";

const params = new URLSearchParams(location.search);
const projectId = Number(params.get("project_id"));
const identity = params.get("identity");
const slots = (params.get("models") || "").split(",").filter(Boolean).map((token) => {
  const separator = token.indexOf(":");
  return { state: token.slice(0, separator), kind: token.slice(separator + 1) };
});
const status = document.getElementById("status");
const selection = document.getElementById("selection");
const legend = document.getElementById("legend");
const progress = document.getElementById("cde-progress");
const container = document.getElementById("viewer");
const colors = { ARC: "#60a5fa", STR: "#f59e0b", MEP: "#10b981" };
const clashTargets = [params.get("clash_a"), params.get("clash_b")]
  .filter(Boolean)
  .map((value) => {
    const separator = value.indexOf(":");
    return { kind: value.slice(0, separator), globalId: value.slice(separator + 1) };
  });

progress.innerHTML = ["WIP", "Shared", "Published", "Archived"].map((state) =>
  `<span class="${state === slots[0]?.state ? "active" : ""}">${state}</span>`
).join("");

legend.innerHTML = slots.map(({ kind, state }) =>
  `<span><i class="dot" style="background:${colors[kind]}"></i>${kind} · ${state}</span>`
).join("");

function firstSelected(map) {
  for (const [modelId, localIds] of Object.entries(map)) {
    for (const localId of localIds) return { modelId, localId: Number(localId) };
  }
  return null;
}

async function load() {
  if (!projectId || !identity || !slots.length) throw new Error("Missing Viewer parameters");
  const components = new OBC.Components();
  const world = components.get(OBC.Worlds).create();
  world.scene = new OBC.SimpleScene(components);
  world.scene.setup();
  world.renderer = new OBC.SimpleRenderer(components, container);
  world.camera = new OBC.OrthoPerspectiveCamera(components);
  components.init();
  components.get(OBC.Grids).create(world);
  const fragments = components.get(OBC.FragmentsManager);
  fragments.init(new URL("/fragments-worker.mjs", location.origin).href);
  const highlighter = components.get(OBF.Highlighter);
  highlighter.setup({ world });
  highlighter.styles.set("clash", {
    color: new THREE.Color("#ef4444"),
    opacity: 1,
    transparent: false,
  });
  const loaded = [];
  const slotByModelId = new Map();
  for (const { kind, state } of slots) {
    status.textContent = `Loading ${kind} ${state}…`;
    const response = await fetch(
      `/fragment?project_id=${projectId}&kind=${kind}&state=${encodeURIComponent(state)}`,
      { cache: "no-store" }
    );
    if (!response.ok) throw new Error(await response.text());
    const modelId = `${state}-${kind}-${projectId}`;
    const model = await fragments.core.load(await response.arrayBuffer(), {
      modelId,
      camera: world.camera.three,
    });
    model.useCamera(world.camera.three);
    model.object.userData.kind = kind;
    model.object.userData.state = state;
    world.scene.three.add(model.object);
    loaded.push(model);
    slotByModelId.set(modelId, { kind, state });
  }
  const combined = loaded[0].box.clone();
  for (const model of loaded.slice(1)) combined.union(model.box);
  await world.camera.controls.fitToBox(combined, false, {
    paddingTop: .7, paddingRight: .7, paddingBottom: .7, paddingLeft: .7,
  });
  await fragments.core.update(true);
  const clashMap = {};
  for (const target of clashTargets) {
    const modelId = [...slotByModelId].find(([, slot]) => slot.kind === target.kind)?.[0];
    if (!modelId) continue;
    const model = fragments.list.get(modelId);
    if (!model) continue;
    const [localId] = await model.getLocalIdsByGuids([target.globalId]);
    if (localId !== undefined) {
      (clashMap[modelId] ??= new Set()).add(localId);
    }
  }
  if (Object.keys(clashMap).length) {
    await highlighter.highlightByID("clash", clashMap, true, true);
    selection.hidden = false;
    selection.textContent = "Clash elements highlighted";
  }
  world.camera.controls.addEventListener("update", () => void fragments.core.update());
  highlighter.events.select.onHighlight.add(async (map) => {
    const selected = firstSelected(map);
    if (!selected) return;
    const model = fragments.list.get(selected.modelId);
    const { kind, state } = slotByModelId.get(selected.modelId);
    const [globalId] = await model.getGuidsByLocalIds([selected.localId]);
    const payload = { project_id: projectId, identity, kind, state };
    if (globalId) payload.global_id = globalId;
    else payload.step_id = selected.localId;
    const response = await fetch("/selection", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const entity = await response.json();
    selection.hidden = false;
    selection.textContent = response.ok
      ? `${kind} · ${entity.ifc_type} #${entity.step_id}${entity.name ? ` — ${entity.name}` : ""}`
      : "Unable to save the current selection";
  });
  status.textContent = `Loaded ${slots.length} model slot(s)`;
  setTimeout(() => status.remove(), 1800);
}

load().catch((error) => {
  status.textContent = `Viewer failed: ${error.message}`;
  console.error(error);
});

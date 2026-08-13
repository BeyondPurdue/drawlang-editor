const FRAMES = [
  "BM-Global-V1-clean-sheet",
  "BM-Global-V1-dots",
  "BM-Global-V1-milimeter-grid",
  "a3-bm-global",
  "a3-bm-global-1",
  "a3-empty",
  "a3-grid",
  "a3-panglima",
];
const log = document.getElementById("log");
function line(s) { log.textContent += "\n" + s; console.log(s); }

async function run() {
  document.getElementById("go").disabled = true;
  log.textContent = "Starting...";

  // 1) whoami
  let me;
  try {
    me = await (await fetch("/api/auth/me")).json();
    line("Logged in as: " + (me.user?.email || "?") + " (role=" + (me.user?.role || "?") + ")");
  } catch (e) { line("auth check failed: " + e); return; }

  if (!me.user || me.user.role !== "admin") {
    line("ERROR: not admin. This account cannot PATCH frames.");
    line("Log in as an admin user, then reload this page.");
    return;
  }

  // 2) Clean frames
  line("\nCleaning frames:");
  for (const fid of FRAMES) {
    try {
      const dl = await (await fetch("/static/_cleanup_data/" + encodeURIComponent(fid) + ".txt")).text();
      const raw = await (await fetch("/api/frames/" + encodeURIComponent(fid) + "/raw")).json();
      const body = { name: raw.name, drawlang: dl, fields: raw.fields || [] };
      const r = await fetch("/api/frames/" + encodeURIComponent(fid), {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      line("  " + fid + ": " + (r.ok ? "OK (" + dl.split("\n").length + " lines)" : "FAIL " + r.status));
    } catch (e) { line("  " + fid + ": ERR " + e); }
  }

  // 3) Delete every canvas the admin owns (DELETE endpoint enforces ownership)
  try {
    const list = await (await fetch("/api/canvases")).json();
    line("\nDeleting canvases:");
    if (!list.canvases || !list.canvases.length) {
      line("  (none listed)");
    }
    for (const c of (list.canvases || [])) {
      const r = await fetch("/api/canvases/" + c.id, { method: "DELETE" });
      line("  #" + c.id + " \"" + (c.name || c.slug) + "\" (slug=" + c.slug + "): " + (r.ok ? "OK" : "FAIL " + r.status));
    }
  } catch (e) { line("canvas delete failed: " + e); }

  line("\nDone.");
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("go").addEventListener("click", run);
});

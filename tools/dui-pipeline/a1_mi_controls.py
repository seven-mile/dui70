"""MI-specific A1 negative controls (paired tamper tests for the
per-base vftable split in slot_abi_audit.py).

W6 port: REPO now resolves to THIS checkout (parents[2] of the
script) -- previously hardcoded to an external worktree
(Z:\repos\DirectUI-w5-clean) that can drift stale and must never
be treated as a gate input.

Run standalone (python tools/dui-pipeline/a1_mi_controls.py) after
changing the audit's probe logic: every control must print CAUGHT.
Validated design (v4); see the v2/v3 learnings below for why the other
mutation points are not load-bearing.

v2/v3 learnings (recorded for the audit trail):
  * Mutating the generated pattern-IFACE decl order (mi-tables primary
    slots 3+) is not load-bearing: under Option D the SDK
    UIAutomationCore.h interface owns the name and the vtable order.
  * Mutating the concrete class's base-list order is not load-bearing:
    MSVC canonicalizes the primary subobject for this family (probe
    tables identical after the swap).
  * The emitter is fail-closed on shape violations (IUnknown trio,
    GetProxyCreator secondary, _E secondary): those mutations produce no
    interface header at all.
  * LOAD-BEARING path: the PatternProvider template's member declarations
    (they become the RefcountBase secondary table's slots) -- v4 MI-1
    below.

MI-1 (template secondary mutation): remove PatternProvider<InvokeProvider,
IInvokeProvider, 0>'s Init declaration from the regenerated template
header. The probe's RefcountBase secondary table then misses the Init
slot -> the audit's secondary-table check must FAIL.

MI-2 (concrete signature mutation): change InvokeProvider's concrete
override get_Value... InvokeProvider has Invoke only; instead alter
Invoke's PARAMETER TYPE in the concrete header (long Invoke(void) ->
long Invoke(int)) -- the override stops matching the SDK base's slot
signature, and the probe's primary slot 3 must fail identity against the
DLL's ?Invoke@InvokeProvider@@UEAAJXZ.
"""
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

# repo-local: resolve the checkout this file lives in -- the controls
# exercise THIS tree's emitter/audit, not a stale external worktree
REPO = pathlib.Path(__file__).resolve().parents[2]
PY = sys.executable
W = pathlib.Path(tempfile.mkdtemp(prefix="a1-mi-ctl4-"))


def setup(mut_name: str) -> pathlib.Path:
    mut = W / mut_name
    mut.mkdir()
    for f in (REPO / "pinned").iterdir():
        if f.suffix == ".json":
            shutil.copy(f, mut / f.name)
    return mut


def regen(mut: pathlib.Path):
    subprocess.run([PY, str(REPO / "tools/dui-pipeline/emit_headers.py"),
                    "--pinned", str(mut), "--out", str(mut / "hdrs")],
                   capture_output=True, text=True)


def run_audit(mut: pathlib.Path, cls: str) -> dict:
    subprocess.run(
        [PY, str(REPO / "tools/dui-pipeline/slot_abi_audit.py"),
         "--pinned", str(mut), "--include", str(mut / "hdrs"),
         "--workdir", str(mut / "work"), "--classes", cls,
         "--json-out", str(mut / "a1.json")],
        capture_output=True, text=True)
    return json.loads((mut / "a1.json").read_text(encoding="utf-8"))


print("MI A1 negative controls v4 (probe-fix cannot false-PASS):")

# ---- MI-1: template Init removal (secondary table content) -----------
mut = setup("ctl-mi1")
regen(mut)
tpl = mut / "hdrs" / "PatternProvider_InvokeProvider_IInvokeProvider_0.h"
text = tpl.read_text(encoding="utf-8")
new = re.sub(r"\s*virtual void Init\(ElementProvider\*\);", "", text)
assert "Init(ElementProvider*)" not in new, "Init decl not removed"
tpl.write_text(new, encoding="utf-8")
res = run_audit(mut, "InvokeProvider")
caught = res["failed"] > 0
det = "; ".join(d["errors"][:110] for d in res["failed_detail"])
print(f"  MI-1 template-Init removal: {'CAUGHT' if caught else 'MISSED!!'} -- {det[:150]}")
ok1 = caught

# ---- MI-2: concrete override signature mutation (primary slot) -------
mut = setup("ctl-mi2")
regen(mut)
sh = mut / "hdrs" / "InvokeProvider.h"
text = sh.read_text(encoding="utf-8")
new = text.replace("virtual long Invoke(void) override;",
                   "virtual long Invoke(int) override;")
assert new != text, "Invoke override decl not found"
sh.write_text(new, encoding="utf-8")
res = run_audit(mut, "InvokeProvider")
caught = res["failed"] > 0
det = "; ".join(d["errors"][:110] for d in res["failed_detail"])
print(f"  MI-2 Invoke signature mutation: {'CAUGHT' if caught else 'MISSED!!'} -- {det[:150]}")
ok2 = caught

print("MI CONTROLS:", "PASS" if (ok1 and ok2) else "FAIL")
sys.exit(0 if (ok1 and ok2) else 1)


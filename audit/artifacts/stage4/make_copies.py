# Stage 4a: build isolated HEAD and working-tree copies of the repo under
# audit/artifacts/stage4/. Reads the repo; writes only under stage4/.
import os, sys, shutil, subprocess, tarfile, io, filecmp, hashlib

REPO = sys.argv[1]
ST4 = os.path.join(REPO, "audit", "artifacts", "stage4")
HEAD_DIR = os.path.join(ST4, "head_src")
WT_DIR = os.path.join(ST4, "wt_src")

for d in (HEAD_DIR, WT_DIR):
    if os.path.exists(d):
        shutil.rmtree(d)
    os.makedirs(d)

# a. HEAD via git archive (Python tarfile extraction)
tar_bytes = subprocess.run(["git", "-C", REPO, "archive", "HEAD"], check=True,
                           capture_output=True).stdout
with tarfile.open(fileobj=io.BytesIO(tar_bytes)) as tf:
    tf.extractall(HEAD_DIR, filter="data")

# b. working tree: tracked + untracked source files, minus exclusions
EXCL_DIRS = {".git", ".venv", "audit", "__pycache__", ".claude", "logs"}
def wt_ignore(dirpath, names):
    rel = os.path.relpath(dirpath, REPO).replace("\\", "/")
    out = set()
    for n in names:
        if n in EXCL_DIRS:
            out.add(n)
        if rel == "dashboard" and n.endswith(".html"):
            out.add(n)
        if rel == "data" and n == "raw":
            out.add(n)          # copied separately in step c
    return out
for n in os.listdir(REPO):
    src = os.path.join(REPO, n)
    if n in EXCL_DIRS:
        continue
    dst = os.path.join(WT_DIR, n)
    if os.path.isdir(src):
        shutil.copytree(src, dst, ignore=wt_ignore)
    else:
        shutil.copy2(src, dst)

# c. data/raw into both copies
for d in (HEAD_DIR, WT_DIR):
    dst = os.path.join(d, "data", "raw")
    if os.path.exists(dst):
        shutil.rmtree(dst)
    shutil.copytree(os.path.join(REPO, "data", "raw"), dst)

# d. verification
def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()
bad = 0; n = 0
for root, dirs, files in os.walk(WT_DIR):
    rel_root = os.path.relpath(root, WT_DIR)
    if rel_root.replace("\\", "/").startswith("data/raw"):
        continue
    for f in files:
        rel = os.path.normpath(os.path.join(rel_root, f))
        n += 1
        if not filecmp.cmp(os.path.join(WT_DIR, rel), os.path.join(REPO, rel), shallow=False):
            bad += 1; print("WT MISMATCH", rel)
print(f"wt_src source files compared byte-for-byte: {n}, mismatches: {bad}")
raw_n = sum(len(fs) for _, _, fs in os.walk(os.path.join(REPO, "data", "raw")))
for d in (HEAD_DIR, WT_DIR):
    m = 0; c = 0
    for root, _, fs in os.walk(os.path.join(REPO, "data", "raw")):
        for f in fs:
            p = os.path.join(root, f); rel = os.path.relpath(p, REPO)
            c += 1
            if not filecmp.cmp(p, os.path.join(d, rel), shallow=False):
                m += 1
    print(f"{os.path.basename(d)} data/raw files: {c} compared, mismatches: {m}")
MOD = ["PROJECT_STATE.md", "backtest/engine.py", "scripts/audit_oos_split.py",
       "scripts/audit_walkforward.py", "scripts/sector_decay.py", "signals/position_sizer.py"]
for p in MOD:
    head_bytes = subprocess.run(["git", "-C", REPO, "show", f"HEAD:{p}"], check=True,
                                capture_output=True).stdout
    ok = open(os.path.join(HEAD_DIR, p), "rb").read() == head_bytes
    differs_wt = open(os.path.join(WT_DIR, p), "rb").read() != head_bytes
    print(f"head_src {p} == git show HEAD:{p}: {ok}; wt_src differs from HEAD: {differs_wt}")

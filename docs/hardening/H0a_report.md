# H0a report: return main to the audited baseline

Date: 2026-10-13. Stage H0, part a. Inputs read first: audit/00_STATUS.md,
audit/01_inventory.md sections 1 and 11, audit/04a_backtest_mechanics.md
sections 6 and 8.

## Outcome summary

| item | result |
|---|---|
| Snapshot branch | `wip/pre-audit-snapshot` at `48279a3`. Holds the 12 modified files (+480 / -218) plus `outputs/sector_decay_analysis_real.md`. Not pushed. |
| main source | Byte-identical to 4a42db0 for every pre-existing path. `KELLY_FILTER_BYPASS` appears 0 times in tracked source. |
| .gitignore | Removed the BOM, fixed the UTF-16LE `.claude/` line and normalised one CRLF line. Appended 4 entries. Ignore status changed only for the intended paths. |
| audit/ | Committed: 177 files, 3.93 MB. Secret scan was clean. No files from head_src, wt_src or yf_cache were included. |
| data/raw inputs | All 1,667 input files are byte-identical to the 2026-10-10 copy. No extra files and no missing files. |
| data/raw artifacts | 26 canonical files are in place (20 changed, 6 were already identical). The originals are archived with a manifest. |
| Scheduled task | `OptionsSentimentPipeline` is **still enabled**: `Disable-ScheduledTask` returned Access denied. Thomas must run the admin command in step 8. |
| Classification | 56 hunks, one row each: 4 BYPASS, 26 BEHAVIOR-CHANGING, 1 BEHAVIOR-NEUTRAL, 25 GENERATED-OUTPUT. |

Deviations from the prompt (each is explained in its step):
- Step 9 uses the diff base `4a42db0` rather than `HEAD`.
- Commit messages carry a `Co-Authored-By` trailer.
- A 4th main commit records the final verification (step 11).

## 1. Preflight

Commands run: `git rev-parse HEAD`, `git branch --show-current`,
`git status --porcelain`, `git diff --stat`, `git config core.autocrlf`,
`git branch -a`, `git ls-files audit`.

- HEAD = `4a42db0faebd9b36b9f11d726a954e4703cb35cf`. PASS
- Branch = `main`, up to date with `origin/main`. PASS
- `git diff --stat`: 12 files changed, 480 insertions(+), 218 deletions(-). PASS
- Porcelain: the 12 ` M` paths, plus `?? .claude/`, `?? audit/` and `?? outputs/sector_decay_analysis_real.md`.
- `core.autocrlf` = `true`. Git warned "LF will be replaced by CRLF" for 6 working-tree files: the working-tree copies were LF.
- `wip/pre-audit-snapshot` did not exist locally or under `remotes/origin`. Only `main` and `remotes/origin/main` existed. No network query was made: `git branch -a` reflects the last fetch.
- audit/ was untracked (`git ls-files audit` returned nothing).

## 2. Snapshot branch

Commands run:
- `git switch -c wip/pre-audit-snapshot`
- `git add -u`
- `git add outputs/sector_decay_analysis_real.md`
- `git commit -m "WIP: pre-audit working tree incl. KELLY_FILTER_BYPASS (preserved, not for merge)"`

The commit is `48279a3`, with parent `4a42db0`.

Checks:
- `git diff --stat HEAD~1 HEAD` shows the same 12 files with the same per-file counts (PROJECT_STATE +112, engine +1, position_sizer 14, audit_oos_split 126, audit_walkforward 197, sector_decay 17, six outputs), plus `outputs/sector_decay_analysis_real.md` +189. The total is 13 files, +669 / -218: the original +480 / -218 plus the 189-line new file. PASS
- `git diff HEAD~1 HEAD -- <12 paths>` is byte-identical to the pre-switch `git diff` patch, checked with `diff -q`. PASS
- `git show --name-only HEAD` lists no `audit/` or `.claude/` path. PASS

## 3. Return to main

Command run: `git switch main`.

- `git status --porcelain` showed only `?? .claude/` and `?? audit/`. There were no modified tracked files. PASS
- `git grep -c KELLY_FILTER_BYPASS HEAD -- . ':!audit' ':!docs'` returned no matches. PASS
- A filesystem grep (excluding audit/, docs/, .venv, .git) matched only `signals/__pycache__/position_sizer.cpython-314.pyc`.
  - This is stale, ignored bytecode from the working-tree version. It was not deleted, because the prompt does not allow deletions.
  - Python rebuilds it automatically, since the source mtime and size changed when `git switch` rewrote `position_sizer.py`.
- Because `core.autocrlf=true`, `git switch` wrote the 12 files back with CRLF line endings. The git content (the blobs) is identical to 4a42db0. Only the on-disk line endings differ from the pre-stage LF working copies.

## 4. .gitignore

### 4a. Defects found (raw bytes)

| line | raw bytes (hex) | defect | fix |
|---|---|---|---|
| 1 | `ef bb bf 23 20 50 79 ...` | UTF-8 BOM before `# Python` | BOM removed |
| 41 | `2e 00 63 00 6c 00 61 00 75 00 64 00 65 00 2f 00 0d 00` | `.claude/\r\n` written as UTF-16LE (each char followed by `00`). Git saw the pattern `.\0c\0l\0a\0u\0d\0e\0/\0\r\0`, which matches nothing. | replaced with `.claude/` |
| 42 | `00` | Stray high byte of the UTF-16LE `\n` (`0a 00`), which left a line containing only NUL | became the blank separator line already implied by the following `0a` |
| 44 | `... 6a 73 6f 6e 0d 0a` | `data/raw/*.json` ends in CRLF, while every other line is LF | normalised to LF (the file's style). Git already matched this pattern (`check-ignore` hit `.gitignore:44`), so its ignore status did not change. |

No other line changed. All other lines keep their text and order. The
file is now UTF-8 without a BOM, uses LF line endings throughout, and
contains no NUL or CR bytes (asserted by the rewrite script). The em
dash on line 7 is a valid UTF-8 character and was kept.

Appended:

```
# Audit repo copies and caches (large / regenerable; see audit/00_STATUS.md)
audit/artifacts/stage4/head_src/
audit/artifacts/stage4/wt_src/
audit/artifacts/stage4/yf_cache/

# Archived data/raw originals (hardening H0a)
data/archive/
```

`data/archive/` was appended because no existing pattern ignored it:
`git check-ignore -v data/archive/x` exited 1 before the change.

### 4b/4d. Ignore-status diff

`git status --ignored --porcelain` was captured before and after the
change (977 lines before). The complete diff:

```
< ?? .claude/                        (only .claude/settings.local.json was ignored before, via the global ~/.config/git/ignore)
> !! .claude/
< !! audit/artifacts/stage4/head_src/{__pycache__,backtest/__pycache__,data/raw,sentiment/__pycache__,signals/__pycache__}/
> !! audit/artifacts/stage4/head_src/
< !! audit/artifacts/stage4/wt_src/{same 5 subpaths}/
> !! audit/artifacts/stage4/wt_src/
> !! audit/artifacts/stage4/yf_cache/
  (plus " M .gitignore" itself)
```

Only the intended paths changed: `.claude/`, `head_src/`, `wt_src/` and
`yf_cache/`. `data/archive/` did not exist yet and appears once
populated. PASS

### 4e. check-ignore

Ignored, as expected:

```
.gitignore:41:.claude/                          .claude/launch.json
.gitignore:41:.claude/                          .claude/scheduled_tasks.lock
.gitignore:47:audit/artifacts/stage4/head_src/  audit/artifacts/stage4/head_src/config.py
.gitignore:48:audit/artifacts/stage4/wt_src/    audit/artifacts/stage4/wt_src/config.py
.gitignore:49:audit/artifacts/stage4/yf_cache/  audit/artifacts/stage4/yf_cache/cookies.db
.gitignore:52:data/archive/                     data/archive/pre_audit_2026-10-13/manifest.csv
```

Not ignored: `git check-ignore -v --no-index audit/00_STATUS.md
audit/artifacts/stage4/yf_snapshot/manifest.jsonl
audit/artifacts/stage4/runs/a/raw/kelly_stats.csv` produced no output and
exited 1. PASS

### 4f. Commit

Commit `0a03735`: ".gitignore: fix .claude/ entry encoding; ignore audit repo copies and data archive".

## 5. audit/ commit

audit/ was untracked, so this step ran.

### 5a. Sizes of the files to be committed

Measured with `git add -n audit/`, which lists 177 files.

| subdirectory | files | bytes |
|---|---|---|
| audit/ (top-level .md) | 7 | 218,292 |
| audit/artifacts/stage3 | 7 | 22,001 |
| audit/artifacts/stage4 (top-level scripts) | 3 | 20,577 |
| audit/artifacts/stage4/logs | 16 | 80,473 |
| audit/artifacts/stage4/runs | 80 | 1,041,885 |
| audit/artifacts/stage4/yf_snapshot | 17 | 887,650 |
| audit/artifacts/stage4b | 47 | 1,660,156 |
| **total** | **177** | **3,931,034 (3.93 MB)** |

The total is below 25 MB, so the step continued. The ignored repo copies
(`stage4/` is 130 MB on disk) are excluded.

### 5b. Secret scan

- Filename scan: `.env*`, `*secret*`, `*key*` and `*.pem` over the 177 paths gave 0 matches.
- Content scan of the 161 text files (`grep -I`, so the 16 binary pickles were skipped):
  - patterns: `api_key=`, `token=`, `apikey`, and `finnhub.{0,40}["'=:]\s*["']?[A-Za-z0-9]{20,}` (case-insensitive)
  - a broader `finnhub.{0,60}[A-Za-z0-9]{20,}`
  - result: 0 matches for every pattern.
- The first draft of the Finnhub regex missed `FINNHUB_KEY = "..."` in a positive-control file, so it was strengthened. The final pattern matched both control lines.
- No values were printed.

### 5c. Commit

`git add audit/` staged 177 paths. None of them were under head_src/,
wt_src/ or yf_cache/ (`grep -c` = 0). Commit `1206c1a`: "audit: stages
1-6 reports, analysis scripts, pinned yfinance snapshot".

## 6. Input integrity

Script: `integrity.py data/raw audit/artifacts/stage4/head_src/data/raw audit/artifacts/stage4/runs/a/raw`.
- Walks both trees and excludes the 26 file names present in runs/a/raw.
- Compares raw bytes first.
- If the raw bytes differ, it compares again after CRLF-to-LF normalisation (autocrlf=true).

Results:
- data/raw had 1,693 files and the copy had 1,693 files.
- Raw-byte identical: 1,667. Identical only after CRLF normalisation: 0.
- **Content differs: 0.**
- Present only in data/raw: 0, so nothing was moved under this step.
- Present only in the copy: 0.

The nightly task's last run (2026-10-10 11:43, result 0x8007042B) left no
file that differs from the copy.

## 7. Artifact alignment

Files in runs/a/raw (26):
- `backtest_{T}.csv` and `backtest_{T}_kelly.csv` for the 10 tickers
- `kelly_stats.csv`, `kelly_stats_oos_train.csv`, `kelly_stats_oos_train_real.csv`
- `quintile_edges.json`, `quintile_edges_oos_train.json`, `quintile_edges_oos_train_real.json`

The prompt says to align every file present in runs/a/raw, so all 26 went
through the procedure:
- each original was moved to `data/archive/pre_audit_2026-10-13/data/raw/`
- the canonical file was copied in with `shutil.copy2`
- the sha256 values were checked: the copy equals the canonical file, and the archived file equals the original.

Afterwards, `cmp` of all 26 against runs/a/raw found 0 mismatches, and a
rerun of the step-6 comparison still showed 1,667 identical and 0
differing inputs. No other data/raw file was touched. Every target already
existed, so there were no "added" rows.

Manifest: `data/archive/pre_audit_2026-10-13/manifest.csv`. It has the
columns relative_path, sha256_before, sha256_after and action, with full
64-character hashes. The table below shows 16-character prefixes:

| relative_path | sha256_before | sha256_after | action |
|---|---|---|---|
| `data/raw/backtest_AAPL.csv` | `7df728be5e926d53` | `7722966537d34887` | replaced |
| `data/raw/backtest_AAPL_kelly.csv` | `3b1e39a56e8030a0` | `873bc291e3d4cd07` | replaced |
| `data/raw/backtest_GLD.csv` | `e9291d1bf5121e88` | `e9291d1bf5121e88` | replaced (content already identical) |
| `data/raw/backtest_GLD_kelly.csv` | `506942a30d24af3e` | `506942a30d24af3e` | replaced (content already identical) |
| `data/raw/backtest_IWM.csv` | `d221a4b45c5ccdb7` | `35ce5d1bb7eced8b` | replaced |
| `data/raw/backtest_IWM_kelly.csv` | `09b93ebadcfa89ab` | `e47ca8e5adada6dc` | replaced |
| `data/raw/backtest_JPM.csv` | `33b2f625b42530d4` | `2614fd4d505f8bb2` | replaced |
| `data/raw/backtest_JPM_kelly.csv` | `c69604d6408191d2` | `7e5f2c7889eef816` | replaced |
| `data/raw/backtest_NVDA.csv` | `e3d280a4f32d7d08` | `531dac43cfadf634` | replaced |
| `data/raw/backtest_NVDA_kelly.csv` | `7377d48b008f8735` | `479a2449c976ee6f` | replaced |
| `data/raw/backtest_SPY.csv` | `1b46086d2ef85ddf` | `8259c4005c7c1bc0` | replaced |
| `data/raw/backtest_SPY_kelly.csv` | `339e72fac9d9a07b` | `a22658c1a257a108` | replaced |
| `data/raw/backtest_TLT.csv` | `ec0efb31a2f1700e` | `3e443df63076048e` | replaced |
| `data/raw/backtest_TLT_kelly.csv` | `06e132d2707fedaf` | `9d21985ce23720d3` | replaced |
| `data/raw/backtest_UNH.csv` | `b4222bbf42358e36` | `a9f55bd9217647eb` | replaced |
| `data/raw/backtest_UNH_kelly.csv` | `1f6b0f2491d04e82` | `ada06cbb7ffe551f` | replaced |
| `data/raw/backtest_WMT.csv` | `a7642f8d438e02c8` | `e921cf7a1fb87b40` | replaced |
| `data/raw/backtest_WMT_kelly.csv` | `aadb6d8b9607460c` | `2a0823fcefaf4141` | replaced |
| `data/raw/backtest_XOM.csv` | `b317dd727afd6297` | `9d0a6fb92e31fa07` | replaced |
| `data/raw/backtest_XOM_kelly.csv` | `e07b2ade70e5cf01` | `6056272e578847a7` | replaced |
| `data/raw/kelly_stats.csv` | `11b3c57d3a98e618` | `fe5836c314b15ca3` | replaced |
| `data/raw/kelly_stats_oos_train.csv` | `d0aa9c3083426392` | `d0aa9c3083426392` | replaced (content already identical) |
| `data/raw/kelly_stats_oos_train_real.csv` | `b6dd9016b3ce4b98` | `b6dd9016b3ce4b98` | replaced (content already identical) |
| `data/raw/quintile_edges.json` | `b26c5d858f4c1b9a` | `642531608003f050` | replaced |
| `data/raw/quintile_edges_oos_train.json` | `36111c7fbf548261` | `36111c7fbf548261` | replaced (content already identical) |
| `data/raw/quintile_edges_oos_train_real.json` | `89b33335ac8231ec` | `89b33335ac8231ec` | replaced (content already identical) |

The 6 "content already identical" files were GLD flat and Kelly (the 4a
control: GLD has no dividend adjustment) and the 4 `*_oos_train*` files.
The 20 replaced files are the post-bypass (2026-05-05) logs and stats.
These include the `_kelly` logs behind the discarded 314-trade R3 result.

## 8. Scheduled task

Search method: `Get-ScheduledTask` filtered on task name `*Options*` or
`*Sentiment*`, or on an action containing `options-sentiment-system` or
`run_daily`. The name `OptionsSentimentPipeline` comes from
scripts/setup_scheduler.ps1:72.

| task | action | state before | LastRunTime / result | NextRunTime |
|---|---|---|---|---|
| `\OptionsSentimentPipeline` | `.venv\Scripts\python.exe scripts\run_daily.py` (wd = repo) | Ready (enabled) | 2026-10-10 11:43:31 / 0x8007042B | **2026-10-13 18:30** |

`Disable-ScheduledTask -TaskName OptionsSentimentPipeline -TaskPath '\'`
failed with **Access is denied.** The final state is **Ready (still enabled)**.

Thomas: run this in an **administrator** PowerShell before 18:30 today:

```powershell
Disable-ScheduledTask -TaskName 'OptionsSentimentPipeline' -TaskPath '\'
Get-ScheduledTask -TaskName 'OptionsSentimentPipeline' | Select-Object TaskName, State   # expect: Disabled
```

If the task runs, it may write new dated `sentiment_*`/`news_*` files
into data/raw. That would change the real-mode sentiment union (D8) and
break the step-6 parity.

## 9. Hunk classification

See [H0a_working_tree_classification.md](H0a_working_tree_classification.md).

- 56 hunks, one row per hunk. Hunks were not grouped and nothing was cherry-picked.
- Diff base: `git diff 4a42db0 wip/pre-audit-snapshot` rather than `HEAD`. By this point main's HEAD included the `.gitignore` and `audit/` commits, which would appear as reverse hunks that are not part of the working tree. `4a42db0` is the snapshot's parent, so the diff is exactly the working-tree change.
- Counts: BYPASS 4 (engine.py x1, position_sizer.py x3); BEHAVIOR-CHANGING 26 (audit_oos_split x11, audit_walkforward x11, sector_decay x4); BEHAVIOR-NEUTRAL 1 (PROJECT_STATE.md); GENERATED-OUTPUT 25 (outputs/).
- The two audit scripts' prose-only hunks are classified BEHAVIOR-CHANGING because they alter report content. The "if unsure" rule applies, and each such row is marked "(prose only)" where no number changes.

## 10. Commit of docs

Commit `docs: H0a hardening report and working-tree classification`, adding
both files under docs/hardening/.

## 11. Final verification

Recorded after the step-10 commit, in the follow-up commit (see below).

Run immediately after commit `8cab910` (step 10). Raw output:

```
$ git diff --stat 4a42db0 HEAD | tail -1; non-allowed paths:
 180 files changed, 15030 insertions(+)
0
$ git diff --name-only 4a42db0 HEAD (top-level groups)
      1 .gitignore
    177 audit/
      1 docs/hardening/H0a_report.md
      1 docs/hardening/H0a_working_tree_classification.md
$ git status --porcelain
(end; lines=0)
$ git log --oneline -6
8cab910 docs: H0a hardening report and working-tree classification
1206c1a audit: stages 1-6 reports, analysis scripts, pinned yfinance snapshot
0a03735 .gitignore: fix .claude/ entry encoding; ignore audit repo copies and data archive
4a42db0 Real-mode validation: backfill, scoring, audits land. PARTIAL/WINDOW-DEPENDENT verdicts on first real-
25c46a5 README: add Research Reports section linking audit findings
5ef15d9 merge: keep local README, replace GitHub stub
$ git branch -a
* main
  wip/pre-audit-snapshot
  remotes/origin/main
$ source parity: git diff --name-only 4a42db0 HEAD -- *.py config.py requirements* outputs README.md PROJECT_STATE.md CLAUDE.md
0
$ git grep -c KELLY_FILTER_BYPASS HEAD -- . :!audit :!docs
exit=1
```

Results:
- `git diff --stat 4a42db0 HEAD` covers 180 files. They are `.gitignore`, 177 files under `audit/`, and 2 under `docs/hardening/`. 0 other paths. PASS
- No `.py`, config, requirements, outputs/, README, PROJECT_STATE or CLAUDE.md path differs outside audit/. Main's source is byte-identical to 4a42db0. PASS
- `git status --porcelain` is empty. PASS
- `KELLY_FILTER_BYPASS` appears 0 times in HEAD outside audit/ and docs/ (git grep exit 1). PASS
- Branches: `main`, `wip/pre-audit-snapshot` (local only, not pushed), `remotes/origin/main`. Nothing was pushed, so main is 3 commits ahead of origin/main.

This section was added in one more docs-only commit, "docs: H0a final verification". The step-11 output can only exist after the step-10 commit, and amending would rewrite history, which is prohibited. That commit changes only this file, so the step-11 invariants still hold.

## Stopped or skipped

- No STOP condition was hit.
- Step 5 was not skipped, because audit/ was untracked.
- Step 6 found nothing to move: no files were present only in data/raw.
- Step 8: the disable failed for lack of permission. The manual command is given above.
- Not done, per the prompt: git push, branch deletion, reset or clean, force operations, history rewrites, deleting anything (including the stale .pyc), editing any .py, config, requirements, outputs/, README.md, PROJECT_STATE.md or CLAUDE.md, and network access.

Commit trailer: the main commits end with a `Co-Authored-By: Claude Opus 5.5
<noreply@anthropic.com>` line, following the session's attribution rule. The
snapshot commit `48279a3` has no trailer. Every subject line is exactly as
specified.

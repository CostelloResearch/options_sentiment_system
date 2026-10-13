# H0a working-tree hunk classification

Source diff: `git diff 4a42db0 wip/pre-audit-snapshot` (default 3-line context).
`4a42db0` is the parent of the snapshot commit `48279a3`, so this diff is
exactly the pre-audit working tree. `git diff HEAD wip/pre-audit-snapshot`
was not used as the source because main's HEAD now also contains the H0a
`.gitignore`, `audit/` and `docs/` commits. Those commits would appear as
reverse hunks, and they are not working-tree hunks.

56 hunks in 13 files: 4 BYPASS, 26 BEHAVIOR-CHANGING, 1 BEHAVIOR-NEUTRAL,
25 GENERATED-OUTPUT. Nothing was cherry-picked.

The line range is the HEAD-side range from the hunk header (`-start,count`,
context lines included). A range of `0` means the file is new.

Classification rules applied:
- Any hunk that changes text written into a generated report is
  BEHAVIOR-CHANGING, even when it changes no number. The class definition
  covers "any value in any ... report", and the instruction is to choose
  BEHAVIOR-CHANGING when unsure. Hunks that change only static wording are
  marked "(prose only)" in the evidence column, so they can be reclassified
  later if wanted.
- A new keyword argument whose default keeps the old behaviour is still
  BEHAVIOR-CHANGING when a CLI flag or call site can reach the new branch.
- Every outputs/ hunk is GENERATED-OUTPUT. The evidence column says which
  ones were produced with the bypass active.

| hunk_id | path | line range (HEAD side) | one-line summary | class | evidence |
|---|---|---|---|---|---|
| H01 | backtest/engine.py | 871-876 | Pass `ticker=ticker` into `size_trade()` from the Kelly path | BYPASS | Activates the `(ticker, signal)` lookup in `KELLY_FILTER_BYPASS`, the only call site that does (00_STATUS s6 rank 9; D3-18, D6) |
| H02 | signals/position_sizer.py | 192-197 | Add module constant `KELLY_FILTER_BYPASS = {("UNH","BUY PUTS")}` plus comment | BYPASS | Bypass definition (01 s1; position_sizer.py:201 in WT) |
| H03 | signals/position_sizer.py | 466-471 | Add `ticker: Optional[str] = None` kwarg to `size_trade()` | BYPASS | Signature plumbing that exists only for the bypass |
| H04 | signals/position_sizer.py | 535-547 | Skip the negative-Kelly early return for bypassed pairs; set `kelly_f = 0.0` for them | BYPASS | UNH BUY PUTS accepted (20/21 rows); +$2,967 canonical (00_STATUS s9) |
| H05 | scripts/audit_oos_split.py | 71-76 | Add `_BASELINE_REAL` / `_BASELINE_DEMO` phrase tables and `_baseline_phrases()` | BEHAVIOR-CHANGING | Supplies hard-coded numbers (+$9,697 / 1.17 / 295) printed in report prose by REAL mode |
| H06 | scripts/audit_oos_split.py | 372-377 | `phrases = _baseline_phrases(mode_label)` in `build_report` | BEHAVIOR-CHANGING | Selects which report text is emitted |
| H07 | scripts/audit_oos_split.py | 386-397 | Intro paragraph baseline figure taken from phrase table instead of literal +$6,775 | BEHAVIOR-CHANGING | Changes the number in the oos_audit_report_real.md intro (see H36) |
| H08 | scripts/audit_oos_split.py | 399-410 | Section 1 question uses `phrases['baseline_pnl']` | BEHAVIOR-CHANGING | Changes the number in report section 1 |
| H09 | scripts/audit_oos_split.py | 581-597 | AAPL paragraph branches on REAL vs DEMO; REAL drops the synthetic stop-cluster claim | BEHAVIOR-CHANGING | New conditional report text; removes the TRAIN/TEST fold attribution in REAL mode |
| H10 | scripts/audit_oos_split.py | 663-668 | Pass `baseline_pnl=` into `_compose_verdict_paragraph` | BEHAVIOR-CHANGING | Changes the number in the verdict paragraph |
| H11 | scripts/audit_oos_split.py | 670-682 | Caveat bullet taken from the mode phrase table (replaces fixed synthetic caveat) | BEHAVIOR-CHANGING | Changes caveats section text per mode |
| H12 | scripts/audit_oos_split.py | 741-747 | Add `baseline_pnl` kwarg (default "+$6,775") to `_compose_verdict_paragraph` | BEHAVIOR-CHANGING | Signature for H10/H14/H15 |
| H13 | scripts/audit_oos_split.py | 751-757 | GENERALIZES verdict text: "synthetic sentiment" changed to "corpus-window coverage" | BEHAVIOR-CHANGING | Report text (prose only) |
| H14 | scripts/audit_oos_split.py | 764-770 | PARTIAL verdict text uses `{baseline_pnl}` | BEHAVIOR-CHANGING | Changes the number in the PARTIAL verdict (real report shows +$9,697) |
| H15 | scripts/audit_oos_split.py | 780-792 | DEGRADES verdict text uses `{baseline_pnl}` (two sites) | BEHAVIOR-CHANGING | Changes the number in the DEGRADES verdict |
| H16 | scripts/audit_walkforward.py | 56-61 | Add `_BASELINE_REAL` / `_BASELINE_DEMO` phrase tables and `_baseline_phrases()` | BEHAVIOR-CHANGING | Hard-coded REAL numbers (+$9,697, +1.17, +0.98, cutoff 2025-12-22) printed into the report |
| H17 | scripts/audit_walkforward.py | 486-491 | `phrases = _baseline_phrases(mode_label)` in `build_report` | BEHAVIOR-CHANGING | Selects which report text is emitted |
| H18 | scripts/audit_walkforward.py | 505-521 | Section 1 intro uses the prior-OOS verdict phrase per mode | BEHAVIOR-CHANGING | Changes numbers/verdict quoted in the intro (see H54) |
| H19 | scripts/audit_walkforward.py | 639-650 | 75/25 column footnote taken from the phrase table; drops `OOS_75_25['cutoff_date']` interpolation | BEHAVIOR-CHANGING | Footnote text changes; REAL footnote admits the column is synthetic (D3-7) |
| H20 | scripts/audit_walkforward.py | 780-794 | AAPL paragraph branches on REAL vs DEMO | BEHAVIOR-CHANGING | New conditional report text |
| H21 | scripts/audit_walkforward.py | 798-803 | Pass `mode_label=` into `compose_verdict` | BEHAVIOR-CHANGING | Enables mode-specific verdict text |
| H22 | scripts/audit_walkforward.py | 810-832 | Caveat bullets taken from phrase table (corpus + single-realisation) | BEHAVIOR-CHANGING | Changes caveats section text per mode |
| H23 | scripts/audit_walkforward.py | 866-874 | `compose_verdict` gains `mode_label` kwarg; computes `oos_sh` from `OOS_75_25["sharpe"]` | BEHAVIOR-CHANGING | Feeds a value into the WINDOW-DEPENDENT verdict (H26) |
| H24 | scripts/audit_walkforward.py | 906-912 | GENERALIZES verdict prints computed `sh_in` instead of literal +0.4103 | BEHAVIOR-CHANGING | Changes the in-sample Sharpe shown in the verdict |
| H25 | scripts/audit_walkforward.py | 918-924 | DEGRADES verdict sign formatting `+{sh_in:.4f}` changed to `{sh_in:+.4f}` | BEHAVIOR-CHANGING | Changes rendered value when `sh_in` < 0 (old text printed "+-x") |
| H26 | scripts/audit_walkforward.py | 929-960 | DEGRADES/WINDOW-DEPENDENT verdicts: computed in-sample Sharpe, phrase-table baseline, "195 refit windows" literal removed, `oos_sh` | BEHAVIOR-CHANGING | Real report now shows +1.1732 instead of literal +0.4103 (H56) |
| H27 | scripts/sector_decay.py | 52-65 | `_load_flat_logs_for(..., real_mode)` reads `backtest_{T}.csv` instead of `_demo`; warns on missing logs | BEHAVIOR-CHANGING | Different input corpus under `--real`; new stderr warning |
| H28 | scripts/sector_decay.py | 126-137 | `main()` gains `real_mode` and forwards it | BEHAVIOR-CHANGING | Plumbing for H27 |
| H29 | scripts/sector_decay.py | 191-197 | Output file `sector_decay_analysis_real.md` when `real_mode` | BEHAVIOR-CHANGING | New output path (produced H47) |
| H30 | scripts/sector_decay.py | 257-261 | Add `--real` CLI flag | BEHAVIOR-CHANGING | New CLI path |
| H31 | PROJECT_STATE.md | 2823-2825 | Append three 2026-05-05 section-12 entries (UNH bypass + Kelly P&L; sector-decay `--real`; audit prose by mode) | BEHAVIOR-NEUTRAL | Docs only; documents the discarded 314-trade bypass result (+$13,906) |
| H32 | outputs/oos_audit_report.md | 44-54 | Train-fold Kelly table "production" rows and production quintile edges rewritten (357/0.0789 to 295/0.2416) | GENERATED-OUTPUT | Demo report re-run against real-mode production stats on disk (D3-6 mismatch) |
| H33 | outputs/oos_audit_report.md | 86-96 | In-sample per-quintile rows replaced (Q1 333 trades to 76) | GENERATED-OUTPUT | Regenerated; in-sample column from post-bypass `_kelly` logs |
| H34 | outputs/oos_audit_report.md | 112-127 | Q5-Q1 spread (-$8,291.41 to $1,364.36) and GENERALIZES paragraph regenerated | GENERATED-OUTPUT | Regenerated |
| H35 | outputs/oos_audit_report.md | 130-137 | Artifact mtime table for production kelly_stats / quintile_edges updated | GENERATED-OUTPUT | Regenerated (mtime 1777945077 = 2026-05-05) |
| H36 | outputs/oos_audit_report_real.md | 2-12 | Intro and section 1 baseline figure +$6,775 / 0.41 / 357 to +$9,697 / 1.17 / 295 | GENERATED-OUTPUT | Output of H07/H08 |
| H37 | outputs/oos_audit_report_real.md | 88-94 | AAPL paragraph REAL wording | GENERATED-OUTPUT | Output of H09 |
| H38 | outputs/oos_audit_report_real.md | 128-139 | PARTIAL verdict paragraph and caveats regenerated | GENERATED-OUTPUT | Output of H11/H14; in-sample column reads post-bypass logs (04a s6.1) |
| H39 | outputs/r3_production_baseline.md | 8-22 | Headline table: flat 507/449/-$18,983; R3 507/314/+$13,906/0.9084 | GENERATED-OUTPUT | Produced with bypass active; the discarded 314-trade result |
| H40 | outputs/r3_production_baseline.md | 24-55 | Cap-utilisation table populated (21 evaluations, peak 1.0037, 1 blocked) and quintile table regenerated | GENERATED-OUTPUT | Produced with bypass active (UNH BUY PUTS cohort) |
| H41 | outputs/sector_decay_analysis.md | 8-38 | Signal-level decay table regenerated (BUY CALLS 348 to 118 trades, etc.) | GENERATED-OUTPUT | Regenerated from logs on disk at 2026-05-05 |
| H42 | outputs/sector_decay_analysis.md | 41-94 | Sector x signal cross-tab regenerated (54 to 42 rows) | GENERATED-OUTPUT | Regenerated |
| H43 | outputs/sector_decay_analysis.md | 102-118 | ConsumerStaples verdict TRADE to DISABLE, horizon table | GENERATED-OUTPUT | Regenerated |
| H44 | outputs/sector_decay_analysis.md | 126-142 | Financials verdict DISABLE to TRADE, horizon table | GENERATED-OUTPUT | Regenerated |
| H45 | outputs/sector_decay_analysis.md | 150-166 | Healthcare verdict TRADE to DISABLE, horizon table | GENERATED-OUTPUT | Regenerated |
| H46 | outputs/sector_decay_analysis.md | 168-190 | Technology horizon rows and optimal horizon 20d to 10d | GENERATED-OUTPUT | Regenerated |
| H47 | outputs/sector_decay_analysis_real.md | 0 (new file, +1..189) | New real-mode sector-decay report | GENERATED-OUTPUT | Output of H27-H30 (`--real`); untracked before snapshot |
| H48 | outputs/walkforward_audit_report.md | 4-10 | Section 1 intro regenerated (DEMO phrase) | GENERATED-OUTPUT | Output of H18 (DEMO branch) |
| H49 | outputs/walkforward_audit_report.md | 41-48 | Comparison table Q5/Q1 in-sample totals updated | GENERATED-OUTPUT | Regenerated; in-sample from post-bypass `_kelly` logs |
| H50 | outputs/walkforward_audit_report.md | 106-116 | In-sample per-quintile table replaced | GENERATED-OUTPUT | Regenerated |
| H51 | outputs/walkforward_audit_report.md | 122-128 | Q5-Q1 spread line updated (in-sample $1,364.36) | GENERATED-OUTPUT | Regenerated |
| H52 | outputs/walkforward_audit_report.md | 150-160 | DEGRADES CONSISTENTLY verdict paragraph regenerated | GENERATED-OUTPUT | Output of H25/H26 |
| H53 | outputs/walkforward_audit_report.md | 163-170 | Artifact mtime table updated | GENERATED-OUTPUT | Regenerated |
| H54 | outputs/walkforward_audit_report_real.md | 4-10 | Intro now quotes REAL PARTIAL verdict (+1.17 to +0.98, cutoff 2025-12-22) | GENERATED-OUTPUT | Output of H16/H18 |
| H55 | outputs/walkforward_audit_report_real.md | 46-52 | 75/25 column footnote states the values are synthetic-mode references | GENERATED-OUTPUT | Output of H19 (D3-7) |
| H56 | outputs/walkforward_audit_report_real.md | 143-160 | AAPL paragraph and WINDOW-DEPENDENT verdict (in-sample +1.1732 vs literal +0.4103) | GENERATED-OUTPUT | Output of H20/H26 |


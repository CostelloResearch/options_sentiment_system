# Audit rules (apply to every audit stage)
1. Read-only. Write only inside audit/. Never modify, move, delete, reformat, stage, or commit any other file.
2. No package installs. No paid API calls (Finnhub, NewsAPI, Bloomberg, OptionsDX, or any key-gated service). No model downloads (including Hugging Face FinBERT weights). Network use is prohibited unless a stage explicitly permits it. If something cannot run without network, record that and move on.
3. Every factual claim carries an evidence tag: [READ path:line], [RAN <exact command>], [INFERRED <basis>], or [UNKNOWN]. Claims based only on docs, comments, docstrings, or names are [INFERRED].
4. Code is the source of truth. When docs and code disagree, report both and the discrepancy.
5. Do not fix anything. Log defects in the stage file's Defects section with path:line, description, severity (CRITICAL = invalidates results or introduces look-ahead; HIGH; MEDIUM; LOW), and how to confirm it.
6. Never resolve uncertainty with a plausible guess. "Could not determine X because Y" is the required form.
7. Before starting any stage, read every existing audit/*.md file.
8. Reddit was removed from the model. Report any Reddit remnants with path:line. Do not remove them and do not reintroduce Reddit.
9. Keep each stage file under ~600 lines. Prefer tables to prose.
10. End every stage file with three sections: Defects, Open questions, Handoff notes for next stage.
11. Never print secret values. Env var and key names only.

# 21. Logging Review (moved)

This audit of logging under multiple env runners, multiple learners and Ray's built-ins is now
§5 of [11_logging_and_observability.md](11_logging_and_observability.md). Its section numbers carry
over with a `5.` in front: §N here is §5.N there, and §N.M is §5.N.M.

| Was | Now |
|---|---|
| §1 What is logged, and by what mechanism | [11](11_logging_and_observability.md) §5.1 |
| §2 Problems under multiple env runners (§2.1–§2.7) | [11](11_logging_and_observability.md) §5.2 (§5.2.1–§5.2.7) |
| §3 Concurrency and parallelism (§3.1–§3.4) | [11](11_logging_and_observability.md) §5.3 (§5.3.1–§5.3.4) |
| §4 What Ray and RLlib already offer | [11](11_logging_and_observability.md) §5.4 |
| §5 Is Ray's Offline Dataset Logging suitable for the per-step record? | [11](11_logging_and_observability.md) §5.5 |
| §6 Recommendations — all eight implemented | [11](11_logging_and_observability.md) §5.6 |
| §7 What was found while implementing | [11](11_logging_and_observability.md) §5.7 |
| §8 What the console records | [11](11_logging_and_observability.md) §5.8 |

The defects the audit found are in [29_fixed_issues.md](29_fixed_issues.md), under "From 21 —
logging review". This page stays so that links from the history files
([16](16_verification_log.md), [17](17_changelog.md)) and from outside the repository still land.

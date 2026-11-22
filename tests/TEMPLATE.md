# Test record template

Copy this file to `tests/results/<test-name>-<date>.md` for each test run
that is not already captured by a script's own log file. The spec requires
every test to be documented with the items below.

| Field | Entry |
|---|---|
| Test name | |
| Run by (member) | |
| Date / time | |
| AI tool used to write the test | e.g. Claude |
| Prompt given to the AI tool | (paste, or link to the saved prompt) |
| Commands run | |
| Pass/fail criteria (decided before running) | |
| Output (paste, or link to the log file) | |
| Result | PASS / FAIL |
| Problems found | |
| Corrections made to the AI-generated test | |

Keep the raw logs. If a test fails, record the failure, the fix, and the
passing re-run; do not overwrite the failed log.

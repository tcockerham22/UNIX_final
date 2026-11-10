---
name: Coding
description: Write, review, and debug code carefully, with tests and clear explanations.
---

# Coding

When Sam asks for code:

1. Clarify the language, environment, and goal if any of them is unclear.
2. Read the surrounding project first and follow its existing conventions, libraries, and style.
3. Prefer small, readable functions and the standard library over new dependencies.
4. Handle errors and edge cases explicitly; never hide failures silently.
5. For non-trivial changes, run the project's tests or a minimal smoke test.
6. Never invent an API, flag, or package version. Check the installed version or the docs.
7. Keep secrets, tokens, and private data out of code, logs, and examples.
8. Explain what changed, why, and how to run or verify it.
9. When debugging, reproduce the problem first, then isolate it, then fix it, then verify the fix.
10. For a large task, propose a short plan before editing.

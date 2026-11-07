# NFI project - rules for the coding agent

Read first: @PROJECT_INSTRUCTIONS.md (universal rules, communication, coding standards, workflow).
SYSTEM_KNOWLEDGE.md is the source of truth for project facts. It is very large (about 600 KB):
do NOT load it whole. Search it with grep for the section you need (for example "X8 A/B",
"ANCHOR LOG", "PENDING") and read only that part.

Hard rules (same as in PROJECT_INSTRUCTIONS.md):
- Never run SSH, scp, systemctl restart or any action on the remote server (vmi3307329).
  Deployment is done manually by the user.
- Local-first: edit locally -> guards (anchor count assertions, py_compile, real import test)
  -> git add/commit/push. Never push without tests passing.
- Never read, print or copy secrets: .env, user_data/config-private.json, API keys, tokens,
  passwords. If a task seems to need them, stop and ask.
- Respond in the language the user writes in (Russian).
- Model discipline: upstream strategy diff review, .py strategy edits and final pre-LIVE
  verification are done on the strongest model; remind the user to switch.
- When a work block ends, offer a SNAP in the format from PROJECT_INSTRUCTIONS.md.

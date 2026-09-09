# Tool comparison: fixture classification script (400-vs-422 tables)

**Task:** Standalone script rebuilding contract §6 status tables and classifying FNOL fixtures against them, done in Cursor instead of Grok.

**Cursor — made easy:**

- Found and cited the contract (§2.4, §6) without being pointed to it.
- Unwrapped the `{id, payload}` fixture format correctly on the first write — no correction needed.
- Stayed in scope: touched only the two new files, didn't reach into routes.py or the Dockerfile despite both existing in sibling worktrees.

**Cursor — made awkward:**

- Workspace root defaulted to the main checkout (`feat/surface`), not the worktree the terminal was actually in — required an explicit correction before it read/wrote in the right tree.
- Agent mode writes files directly with no diff-preview/approve step in chat; review happens after the fact in the editor, not before the write.

**Preference:** For small, self-contained, read-mostly exploratory scripts like this one — where the main risk is misreading a spec, not breaking production code — Cursor's Agent mode is fast because it just writes and you check after. For the actual production surface (routes.py, tests) I would not pick Grok for a diff-preview it does not have. Both agents write first. The difference that mattered today was Grok missing the worktree until corrected. Keep production edits behind an explicit working-directory sentence, then review the file on disk before commit, because neither tool blocked a bad mapping before it landed.
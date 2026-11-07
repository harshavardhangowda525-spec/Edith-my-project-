# EDITH PC bridge: your projects, tests and errors

`tools/edith_bridge.py` connects your computer to your EDITH server. It is one file, uses only
Python's standard library (Python 3.9 or newer, nothing to `pip install`), and works on Windows, macOS and Linux.

## 1. Set it up (2 minutes)

Copy `edith-ai/tools/edith_bridge.py` anywhere on your PC (for example `C:\edith\`). Then in a terminal:

```bash
python edith_bridge.py configure --server https://YOUR-EDITH.onrender.com --token YOUR_OWNER_ACCESS_TOKEN
```

The token is the same password you use in the phone app (`OWNER_ACCESS_TOKEN` on Render). It is saved in
`%USERPROFILE%\.edith\bridge.json` (Windows) or `~/.edith/bridge.json`, readable only by you.

Tell the bridge about a project, with the command that runs its tests:

```bash
python edith_bridge.py add-project shop C:\code\shop --test "npm test" --log logs\app.log
```

Examples of test commands: `flutter test`, `npm test`, `python -m pytest -q`, `.\gradlew test`.

## 2. Use it from the terminal

| What | Command |
|---|---|
| Ask anything, answer streams in as it's written | `python edith_bridge.py ask "why does Gradle 8 break my Flutter build?"` |
| Explain an error and get the fix | `npm run build 2>&1 \| python edith_bridge.py explain-error -` or `python edith_bridge.py explain-error build.log` |
| Teach EDITH your codebase | `python edith_bridge.py index shop` |

**Indexing is incremental:** the bridge remembers a fingerprint of every file. The next run only uploads
files that changed, replaces their old copy, and removes deleted files; the whole repository is never re-sent.
Skipped: `.git`, `node_modules`, build folders, virtual environments, binaries, files over 150 KB, and anything
that looks like a secret (`.env*`, `*.pem`, `*.key`, keystores, `google-services.json`, service-account files).
Obvious credentials inside the files that are uploaded are replaced with `[REDACTED]`.

After indexing, ask normally: *"Edith, where do we validate the login token in shop?"*. The answer comes from
your code and cites the files.

## 3. Let EDITH run jobs on your PC (voice or web)

```bash
python edith_bridge.py serve
```

Leave it running. Now you can say (or type, or press Ctrl+K in the web app):

* "Edith, run the tests on my PC" (or "run the tests for shop")
* "Edith, git status on my PC" / "show recent commits for shop"
* "Edith, index my project shop"

EDITH answers "On it, sir" at once and keeps listening. The phone gets a notification with the real result
when the job is done, and EDITH tells you in your headphones when you're not in a call or meeting.

### What the bridge will and won't do

* The server can only ask for a **fixed list** of jobs: run your configured test command, git status, git
  log, git diff summary, the end of your configured log file, list projects, and index a project. There is
  no "run any command" job, so a bug or a malicious document can't make your PC run something else.
* **Running tests and indexing ask you first on the PC** (`Allow? [y/N]`). Start with
  `serve --yes` only if you want them to run without asking.
* Nothing that deletes files, pushes code, deploys, or installs packages is ever run by the bridge.
* A job is only reported as done when the bridge sends back a result. Failed tests are reported as failed,
  with the output. If the bridge isn't running, the task fails at once with "Your PC bridge isn't connected".

### VS Code

Run the bridge in VS Code's terminal, or add tasks in `.vscode/tasks.json`:

```json
{
  "version": "2.0.0",
  "tasks": [
    { "label": "EDITH: explain last build error", "type": "shell",
      "command": "npm run build 2>&1 | python C:/edith/edith_bridge.py explain-error -" },
    { "label": "EDITH: index this project", "type": "shell",
      "command": "python C:/edith/edith_bridge.py index shop" },
    { "label": "EDITH: bridge", "type": "shell", "command": "python C:/edith/edith_bridge.py serve",
      "isBackground": true }
  ]
}
```

## 4. GitHub (optional)

On Render, add `GITHUB_TOKEN` (a fine-grained token with **read-only** access to your repositories is enough)
and optionally `GITHUB_DEFAULT_REPO=owner/name`. Then: *"Edith, check my GitHub"* or *"check GitHub for
owner/name"*. You get open pull requests, the newest issues, and the latest CI runs with failures, straight
from GitHub's API (no AI guessing). The token stays on the server; it is never sent to the phone or browser.

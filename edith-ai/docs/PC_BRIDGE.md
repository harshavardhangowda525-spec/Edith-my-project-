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

* The server can only ask for a **fixed list** of jobs: run your configured test command or one of the
  commands *you* configured with `--cmd`, open a project, a Claude Code job (see section 4), git status, git
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

## 4. "Edith, turn on my laptop and work on …" (Windows, home Wi-Fi)

### One-time setup on the laptop (10 minutes)

1. **Add your project with its commands** (the names are what you say):
   ```bash
   python edith_bridge.py add-project shop C:\code\shop --test "npm test" --cmd dev="npm run dev" --cmd build="npm run build" --open dev
   ```
   `--open dev` means "start the dev server whenever I open this project".
2. **Install Claude Code** (https://claude.com/claude-code), open a terminal and run `claude` once to sign in.
3. **Start the bridge with Windows:**
   ```bash
   python edith_bridge.py install-autostart
   ```
   From now on it runs in the background after you log in (log: `%USERPROFILE%\.edith\bridge.log`). In this
   mode it doesn't ask on the laptop, because you confirm on the phone. Undo with `uninstall-autostart`.
4. **Let the Wi-Fi card wake the laptop.** Run `python edith_bridge.py wake-info` for the exact steps:
   Device Manager → Wi-Fi adapter → Power Management → *Allow this device to wake the computer* +
   *Only allow a magic packet*; Advanced → *Wake on Magic Packet* = Enabled.
5. **Put the laptop to Sleep, not Shut down**, and keep it plugged in. Closing the lid is fine.

The phone learns the laptop's network address from the bridge by itself; there is nothing to type on the phone.

### What you can say

| Say | What happens |
|---|---|
| "Edith, turn on my laptop" | The phone sends the wake-up signal on your Wi-Fi |
| "Edith, turn on my laptop and open shop" | Wakes it, opens `shop` in VS Code, starts its `--open` commands in their own windows |
| "Edith, run dev for shop" / "run build for shop" | Runs that configured command and tells you how it went |
| "Edith, run the tests for shop" | Runs the test command |
| "Edith, turn on my laptop and work on shop and build the login page" | EDITH asks: *"Should I start Claude Code on shop to build the login page? … Say yes to start."* After **yes**: wakes the laptop, Claude Code writes the code, tests run, you get the summary |
| "Edith, stop the laptop task" | Stops Claude Code (what's done so far stays on its branch) |

### How the coding job keeps your project safe

* It only starts after you say **yes** to the read-back (a misheard sentence can't start it).
* It refuses to start if the project has uncommitted changes, so your own work is never mixed in.
* Claude Code works on a **new branch** `edith/<task>-<time>`; your main branch is untouched.
* It may read and edit files in the project and run the test command and your configured commands, nothing
  else. `git push`, `git reset`, deleting with `rm`/`del`, and web fetching are blocked; commands with
  deploy/publish/push/release in them are never allowed.
* When it's done, the bridge saves the work as one local commit on that branch, runs your tests, and reports:
  Claude Code's summary, files changed, and whether the tests passed. **Nothing is pushed or deployed.**
* Keep it: `git switch main && git merge edith/...`. Drop it: `git switch main && git branch -D edith/...`.
* Limits: up to one hour per job. Claude Code uses your own Claude subscription or API key.

### Honest limits

* Waking only works on the **same Wi-Fi** as the phone, and only from **sleep**. A shut-down laptop can't be
  woken over Wi-Fi.
* Some laptops can't wake over Wi-Fi at all (common with "Modern Standby"). Test it once. If it doesn't wake:
  Settings → System → Power → *When plugged in, put my device to sleep after: Never*. The screen can still
  turn off, and EDITH can always reach it.
* After waking, Windows stays on the lock screen. The work happens behind it; you'll see VS Code and the
  windows when you unlock.
* If the laptop doesn't come online within 4 minutes, the task fails and EDITH tells you; it never says
  "done" for work that didn't happen.

## 5. GitHub (optional)

On Render, add `GITHUB_TOKEN` (a fine-grained token with **read-only** access to your repositories is enough)
and optionally `GITHUB_DEFAULT_REPO=owner/name`. Then: *"Edith, check my GitHub"* or *"check GitHub for
owner/name"*. You get open pull requests, the newest issues, and the latest CI runs with failures, straight
from GitHub's API (no AI guessing). The token stays on the server; it is never sent to the phone or browser.

# Run Smart Money Stories 24/7 on a free server

GitHub only scans every ~30 minutes. That is too slow for memecoins. This guide puts the scanner on a
free cloud server that never sleeps, so alerts reach Telegram within seconds of a tracked wallet
buying, and the public website updates every 10 minutes.

**What runs on the server (all read-only, nothing can trade):**

| Service | What it does |
|---|---|
| `sms-stream` | Keeps a live Helius connection open to the tracked wallets and records every swap |
| `sms-watch` | Every 30 s turns new swaps into graded alerts, sends them to Telegram, scores old alerts |
| `sms-publish` (every 10 min) | Pushes the public record and website data to GitHub, which republishes the site |

Time needed: about 30–45 minutes, once. Cost: $0 on Oracle's Always Free tier.

> **Only one stream can use your Helius key at a time.** The free plan caps open subscriptions. If a
> stream worker is already running on another computer (for example one started by another AI
> assistant), stop it before starting the server, or both will fail with "Too many subscriptions".

---

## Step 1 — Get a free server (Oracle Cloud Always Free)

1. Sign up at [signup.cloud.oracle.com](https://signup.cloud.oracle.com/). Oracle asks for a card to
   verify you; Always Free resources are not charged. Check Oracle's current free-tier terms on that
   page before you start.
2. In the Oracle console: **Create a VM instance**.
   - **Image:** Canonical **Ubuntu** (22.04 or 24.04).
   - **Shape:** any shape marked **Always Free-eligible** (the small AMD one is enough).
   - **SSH keys:** choose **Generate a key pair for me** and **download the private key**. Keep it safe.
3. Click **Create**. When it shows **Running**, copy its **Public IP address**.

Oracle's screens change from time to time; the labels above may differ slightly.

## Step 2 — Connect to the server

On a Mac, open **Terminal** and run (replace the file name and IP with yours):

```bash
chmod 400 ~/Downloads/ssh-key-2026-11-10.key
```

```bash
ssh -i ~/Downloads/ssh-key-2026-11-10.key ubuntu@YOUR.SERVER.IP
```

Type `yes` if asked. You are now on the server.

## Step 3 — Install

On the server:

```bash
curl -fsSL https://raw.githubusercontent.com/anishsaha282002-dotcom/smart-money-alerts/smart-money-stories/deploy/install.sh | bash
```

The first run installs everything and creates a settings file, then stops so you can add keys.

## Step 4 — Add your keys

You need four things. Get them first, then paste them into the settings file.

| Key | Where to get it |
|---|---|
| `HELIUS_API_KEY` | [dashboard.helius.dev](https://dashboard.helius.dev) → API Keys |
| `TELEGRAM_BOT_TOKEN` | In Telegram, message **@BotFather** → `/newbot` → copy the token |
| `TELEGRAM_CHAT_ID` | Make a **private channel**, add your bot as an admin, post one message, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` in Chrome and copy the `"chat":{"id":-100…}` number |
| `GITHUB_TOKEN` | [Create a fine-grained token](https://github.com/settings/personal-access-tokens/new): **Repository access** → *Only select repositories* → `smart-money-alerts`; **Permissions** → *Contents* → **Read and write**. Copy the token |

Open the settings file on the server:

```bash
nano ~/smart-money-alerts/.env
```

Paste each value after its `=`. Save with **Ctrl+O**, **Enter**, then exit with **Ctrl+X**.
Never paste these keys into a chat, an AI assistant, or a GitHub file.

## Step 5 — Start it

Run the installer again. This time it starts the three services:

```bash
curl -fsSL https://raw.githubusercontent.com/anishsaha282002-dotcom/smart-money-alerts/smart-money-stories/deploy/install.sh | bash
```

Check it:

```bash
bash ~/smart-money-alerts/deploy/status.sh
```

You want three **OK** lines. They restart on their own if they crash or the server reboots.

## Step 6 — Hand the website over to the server

On GitHub, in this repository: **Settings → Secrets and variables → Actions → Variables**.
Add a variable `SMS_LIVE_SERVER` = `true`.

From then on the scheduled GitHub scan stands down (so the public record has exactly one writer and
its hash chain never forks), and every push from the server republishes the website.

Within 10 minutes the home page shows a green **"Live stream on"** pill.

---

## Day to day

| Want to… | Run on the server |
|---|---|
| See if everything is fine | `bash ~/smart-money-alerts/deploy/status.sh` |
| Update to the newest version | the Step 5 install command again |
| Stop sending alerts (keep recording) | edit `config.toml`, set `min_grade = "A"` or remove the Telegram keys, then `sudo systemctl restart sms-watch` |
| Stop everything | `sudo systemctl stop sms-stream sms-watch sms-publish.timer` |

## If something is wrong

| You see | Fix |
|---|---|
| `Too many subscriptions` in status | Another stream uses the same Helius key. Stop it (see the note at the top) |
| `GITHUB_TOKEN is not set` | Step 4: add the token, then `sudo systemctl restart sms-publish.timer` |
| `git push failed` | The token needs *Contents: Read and write* on this repository only |
| No Telegram messages | The bot must be an **admin** of the channel; check `TELEGRAM_CHAT_ID` starts with `-100` |
| Site says "Live stream down" | `bash deploy/status.sh`; the stream restarts itself within a minute |

## Credits

The Helius free plan has 1M credits a month. The stream worker has a built-in daily cap (30,000 by
default): at 80% it shrinks to the top 150 wallets, at 100% it pauses until the next day. The
health strip on the website shows today's usage.

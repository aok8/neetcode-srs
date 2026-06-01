# neetcode-srs

Daily spaced-repetition CLI over the [NeetCode 250](https://neetcode.io/practice?tab=neetcode250) — with an optional frequency-weighted supplemental list for extra interview prep.
One card a day, answer `y` or `n`, SM-2 scheduling decides when you see it again.
New cards go Easy → Medium → Hard so muscle memory builds up gradually.

```
  New problem
  Two Sum  [Easy]  Arrays & Hashing
  https://leetcode.com/problems/two-sum/

  y = solved · n = couldn't solve · e = trivially easy · skip
  Answer [y/n/e/skip] > y
  solved — next review in 4 days (2026-04-26).
```

## Install

Requirements: Python 3.10+ and `git`. On macOS, `brew install python@3.13` if you need it.

```bash
git clone https://github.com/siddhant1/neetcode-srs.git ~/projects/neetcode-srs
cd ~/projects/neetcode-srs

python3 -m venv .venv
.venv/bin/pip install -e .

# if you dont want to symlink
source ~/projects/neetcode-srs/.venv/bin/activate
neetcode

# Symlink the CLI onto your PATH (adjust target dir if needed):
mkdir -p ~/.local/bin
ln -sf "$PWD/.venv/bin/neetcode" ~/.local/bin/neetcode
```

Make sure `~/.local/bin` is on your `PATH`. Add this to `~/.zshrc` if it isn't:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Open a new shell, then initialize the deck:

```bash
neetcode setup      # fetches the 250 list from neetcode.io, populates SQLite
neetcode stats      # should show: 250 total · 250 new
```

## Install Windows

```bash
git clone https://github.com/siddhant1/neetcode-srs.git "$HOME/projects/neetcode-srs"
cd "$HOME/projects/neetcode-srs"

python -m venv .venv
.venv\Scripts\pip install -e .

# If you don't want to add to PATH, just activate the venv:
.venv\Scripts\Activate.ps1
neetcode

# Add the Scripts folder to your PATH permanently instead of symlinking:
$scriptsPath = "$PWD\.venv\Scripts"
[Environment]::SetEnvironmentVariable("PATH", "$scriptsPath;" + [Environment]::GetEnvironmentVariable("PATH", "User"), "User")
```

Open a new shell, then initialize the deck:

```bash
neetcode setup      # fetches the 250 list from neetcode.io, populates SQLite
neetcode stats      # should show: 250 total · 250 new
```

## Daily use

```bash
neetcode                   # show today's card, prompts y / n / e / skip
neetcode --shuffle         # enable shuffle mode (saved); random problems, Easy/Medium weighted over Hard
neetcode --no-shuffle      # revert to in-order mode (saved)
neetcode --extra           # enable extra mode (saved); draws from NeetCode 250 + secondary list
neetcode --no-extra        # disable extra mode (saved)
neetcode stats             # deck progress
neetcode history 20        # last 20 reviews
neetcode skip              # postpone today's card one day
neetcode dashboard         # open an HTML progress report (heatmap, streak, etc.)
neetcode setup             # sync the problem list, prune stale cards
neetcode setup --refresh   # re-fetch the NeetCode 250 list from neetcode.io before syncing
neetcode reset             # reset ALL progress back to unseen (confirmation required)
neetcode reset secondary   # reset only the secondary/extra list
neetcode reset neetcode250 # reset only the NeetCode 250 list
```

The `dashboard` command generates a self-contained HTML file in your temp
directory and opens it in your default browser — no server, no network
beyond fonts.

One card per calendar day by default. Run `neetcode` again after answering
and it tells you you're done. Want more per day?

```bash
neetcode config daily 3      # now you can do 3 cards/day
neetcode config shuffle on   # same as --shuffle, persisted
neetcode config shuffle off  # same as --no-shuffle, persisted
neetcode config extra on     # same as --extra, persisted
neetcode config extra off    # same as --no-extra, persisted
neetcode config              # show current config
```

Each invocation still shows one card — `daily` just controls how many times
you can run it before it blocks you until tomorrow.

Shuffle mode picks new cards randomly instead of in order. Difficulty is
weighted — **Easy 35% · Medium 50% · Hard 15%** — so hard problems surface
regularly but don't dominate. Answering `n` on any card also prints the
topic(s) it belongs to so you know exactly what to review.

## Switching modes / starting over

Changing `--extra` or `--shuffle` takes effect immediately on the next `neetcode` run -- no setup needed.
However, cards already scheduled (due reviews from a previous mode) keep surfacing until reviewed,
because SRS progress is always honoured regardless of the current mode.

To get a truly clean slate when switching modes, use `reset`:

```bash
neetcode reset secondary    # clear secondary cards before turning --extra off
neetcode reset neetcode250  # clear NeetCode 250 progress before a fresh start
neetcode reset              # wipe everything and start completely over
```

Each variant shows a breakdown of cards and review records that will be deleted,
and requires you to type `yes` before anything changes.

## Extra mode

`--extra` activates a combined pool that draws from both the NeetCode 250 list
and a supplemental `data/secondary.json` list sorted by interview frequency.

**Selection pipeline:**

1. **Source** — NeetCode 250 is chosen 60% of the time, secondary 40%.
2. **Difficulty** — Easy 35% · Medium 50% · Hard 15%, applied independently within each source.
3. **Card within source:**
   - *NeetCode 250* — uniform random within the chosen difficulty bucket. No frequency decay; the list is not ordered by frequency.
   - *Secondary* — **exponential frequency decay** by rank. The problem at rank 0 is drawn ~311× more often than the problem at rank 415. Every 50 ranks, probability halves: rank 50 is 2× less likely than rank 0, rank 100 is 4× less, rank 200 is 16× less, and so on. Problems near the bottom of the list are genuinely rare regardless of how many cards end up in the chosen difficulty bucket.

The idea is that you're covering NeetCode breadth while being strongly biased toward the interview problems
that actually show up most often in the wild.

`secondary.json` is a plain JSON file — edit it to add or reorder problems. The format mirrors
`neetcode250.json`: an array of `{id, title, difficulty, topics, leetcode_url}` objects where index 0
is the most frequent interview problem. After editing, run `neetcode setup` to sync the changes into
the deck (stale unseen cards are pruned automatically).

## Scheduling rules

Three grades, SM-2 under the hood:

- **`y` — solved it.**
  - First time on a fresh card: interval jumps to **4 days** (no 1-day probe — a first-shot pass is strong evidence, and each LeetCode review costs real time).
  - After that: `round(interval × ease)`. Ease grows by 0.05 per correct (cap 2.8).
- **`e` — trivially easy.**
  - First time on a fresh card: interval jumps to **7 days**.
  - After that: `round(interval × ease × 1.3)` — the Anki "easy bonus". Ease grows by 0.15.
- **`n` — couldn't solve.**
  - Streak resets, card pushed out **at least 3 days** — not tomorrow. The brain needs time to forget and re-encounter cleanly.
  - Ease drops by 0.2 (floor 1.3).

By default, new cards are introduced in order **Easy → Medium → Hard**
within the NeetCode list ordering. With `--shuffle`, the order is randomized using
difficulty weights instead. Due reviews always beat new cards when both are available.

## Data

Everything lives in `data/`:

- `neetcode250.json` — cached NeetCode 250 problem list (committed).
- `secondary.json` — supplemental frequency-ordered problem list (committed). Edit this to add problems; index 0 = most common interview problem.
- `state.db` — SQLite with your progress and audit log (gitignored).

Back up `state.db` if you care about your streak.

## Tests

```bash
.venv/bin/pip install pytest
.venv/bin/pytest
```

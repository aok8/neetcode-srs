from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

from neetcode_srs import config, dashboard, db, problems, selector
from neetcode_srs.srs import schedule

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "state.db"
CACHE_PATH = DATA_DIR / "neetcode250.json"
SECONDARY_PATH = DATA_DIR / "secondary.json"
CONFIG_PATH = DATA_DIR / "config.json"


# --- output helpers -------------------------------------------------------

_USE_COLOR = sys.stdout.isatty()

BOLD = "\033[1m" if _USE_COLOR else ""
DIM = "\033[2m" if _USE_COLOR else ""
RESET = "\033[0m" if _USE_COLOR else ""
GREEN = "\033[32m" if _USE_COLOR else ""
YELLOW = "\033[33m" if _USE_COLOR else ""
RED = "\033[31m" if _USE_COLOR else ""
CYAN = "\033[36m" if _USE_COLOR else ""

DIFFICULTY_COLOR = {"Easy": GREEN, "Medium": YELLOW, "Hard": RED}


def _color(s: str, c: str) -> str:
    if not c:
        return s
    return f"{c}{s}{RESET}"


def _print_card(card: db.Card, kind: str) -> None:
    banner = {
        "review": "Review due",
        "new": "New problem",
    }.get(kind, kind)
    diff = _color(card.difficulty, DIFFICULTY_COLOR.get(card.difficulty, ""))
    print()
    print(_color(f"  {banner}", DIM))
    print(f"  {_color(card.title, BOLD)}  [{diff}]  {DIM}{', '.join(card.topics)}{RESET}")
    print(f"  {_color(card.leetcode_url, CYAN)}")
    if kind == "review":
        streak = card.reps
        prior = card.interval_days
        print(f"  {DIM}streak: {streak} · last interval: {prior}d · ease: {card.ease:.2f}{RESET}")
    print()


def _parse_today(raw: str | None) -> date:
    if raw is None:
        return date.today()
    return date.fromisoformat(raw)


# --- commands -------------------------------------------------------------

def cmd_setup(args: argparse.Namespace) -> int:
    conn = db.connect(DB_PATH)

    cached = problems.load_cached(CACHE_PATH)
    if cached is None or args.refresh:
        print("Fetching NeetCode 250 from neetcode.io …")
        plist = problems.fetch_neetcode250()
        problems.save_cache(CACHE_PATH, plist)
        print(f"Cached {len(plist)} problems → {CACHE_PATH}")
    else:
        plist = cached
        print(f"Using cached problem list ({len(plist)} problems). Use --refresh to re-fetch.")
    n, removed = db.sync_problems(conn, plist, source="neetcode250")
    msg = f"Synced {n} NeetCode 250 problems."
    if removed:
        msg += f" Removed {removed} stale unseen cards."
    print(msg)

    secondary = problems.load_secondary(SECONDARY_PATH)
    if secondary:
        ns, sremoved = db.sync_problems(conn, secondary, source="secondary")
        msg = f"Synced {ns} secondary problems (frequency-ordered)."
        if sremoved:
            msg += f" Removed {sremoved} stale unseen cards."
        print(msg)
    elif SECONDARY_PATH.exists():
        print(f"secondary.json is empty — add problems to {SECONDARY_PATH} to use --extra mode.")

    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    conn = db.connect(DB_PATH)
    today = _parse_today(args.today)
    s = db.stats(conn, today)
    if s["total"] == 0:
        print("Deck is empty. Run `neetcode setup` first.")
        return 1
    print()
    print(f"  {_color('Deck', BOLD)}: {s['total']} total  ·  {s['new']} new  ·  "
          f"{s['learning']} learning  ·  {s['mature']} mature")
    print(f"  {_color('Due today', BOLD)}: {s['due_today']}")
    print(f"  {_color('By difficulty', BOLD)}:")
    for d, counts in s["by_difficulty"].items():
        color = DIFFICULTY_COLOR.get(d, "")
        print(f"    {_color(d, color):<20} {counts['seen']}/{counts['total']} seen")
    print()
    return 0


def cmd_today(args: argparse.Namespace) -> int:
    conn = db.connect(DB_PATH)
    today = _parse_today(args.today)
    cfg = config.load(CONFIG_PATH)
    target = cfg["daily_target"]

    # Persist --shuffle / --no-shuffle if either flag was explicitly passed.
    if getattr(args, "shuffle", False):
        cfg = config.set_key(CONFIG_PATH, "shuffle", True)
    elif getattr(args, "no_shuffle", False):
        cfg = config.set_key(CONFIG_PATH, "shuffle", False)

    # Persist --extra / --no-extra if either flag was explicitly passed.
    if getattr(args, "extra", False):
        cfg = config.set_key(CONFIG_PATH, "extra", True)
    elif getattr(args, "no_extra", False):
        cfg = config.set_key(CONFIG_PATH, "extra", False)

    if getattr(args, "ui", False):
        from neetcode_srs import ui_server as _ui
        _ui.start_ui(DB_PATH, cfg)
        return 0

    shuffle = cfg["shuffle"]
    extra = cfg["extra"]

    pick = selector.pick_today(conn, today, daily_target=target, shuffle=shuffle, extra=extra)
    if pick.kind == "empty":
        print("Deck is empty. Run `neetcode setup` first.")
        return 1
    if pick.kind == "quota_hit":
        print(f"\n  Done for today: {pick.done_today}/{target} cards. "
              f"Come back tomorrow.")
        print(f"  {DIM}Want more? `neetcode config daily N`{RESET}\n")
        return 0
    assert pick.card is not None

    if extra:
        src_label = "extra mode" + (
            f" · from secondary" if pick.card.source == "secondary" else " · from neetcode250"
        )
        print(f"  {DIM}{src_label}{RESET}")
    elif shuffle:
        print(f"  {DIM}shuffle mode{RESET}")
    if target > 1:
        print(f"  {DIM}card {pick.done_today + 1} of {target} today{RESET}")
    _print_card(pick.card, pick.kind)
    print(f"  {DIM}y = solved · n = couldn't solve · e = trivially easy · skip{RESET}")
    prompt = f"  {_color('Answer', BOLD)} [y/n/e/skip] > "
    try:
        answer = input(prompt).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return 130

    if answer in ("skip", "s"):
        next_due = today + timedelta(days=1)
        db.postpone(conn, pick.card, next_due)
        print(f"  {_color('Postponed', DIM)} to {next_due.isoformat()}.\n")
        return 0
    if answer not in ("y", "n", "e"):
        print("  Expected y / n / e / skip. No changes made.")
        return 2

    result = schedule(pick.card.state, answer, today)
    db.apply_review(conn, pick.card, answer, result.state, result.next_due, today)

    verb = {"y": "solved", "n": "failed", "e": "easy"}[answer]
    color = {"y": GREEN, "n": RED, "e": CYAN}[answer]
    days = result.state.interval_days
    print()
    print(f"  {_color(verb, color)} — next review in {days} day{'s' if days != 1 else ''} "
          f"({result.next_due.isoformat()}).")
    print(f"  {DIM}ease {pick.card.ease:.2f} → {result.state.ease:.2f}  ·  "
          f"streak {result.state.reps}{RESET}")
    if answer == "n" and pick.card.topics:
        topics_str = ", ".join(pick.card.topics)
        print(f"  {_color('Study:', BOLD)} {YELLOW}{topics_str}{RESET}")
    print()
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    conn = db.connect(DB_PATH)
    rows = db.recent_reviews(conn, args.n)
    if not rows:
        print("No reviews yet.")
        return 0
    print()
    for r in rows:
        icon = {
            "y": _color("✓", GREEN),
            "n": _color("✗", RED),
            "e": _color("★", CYAN),
            "skip": _color("⋯", DIM),
        }[r["outcome"]]
        diff = _color(r["difficulty"], DIFFICULTY_COLOR.get(r["difficulty"], ""))
        when = r["reviewed_at"][:16].replace("T", " ")
        delta = (
            f"interval {r['interval_before']}d → {r['interval_after']}d"
            if r["outcome"] != "skip"
            else "postponed"
        )
        print(f"  {icon}  {when}  {r['title']:<40} [{diff}]  {DIM}{delta}{RESET}")
    print()
    return 0


_CONFIG_ALIASES = {"daily": "daily_target"}


def cmd_dashboard(args: argparse.Namespace) -> int:
    conn = db.connect(DB_PATH)
    today = _parse_today(args.today)
    if args.write_only:
        path = dashboard.render_to_file(conn, today)
        print(f"Wrote {path}")
    else:
        path = dashboard.open_dashboard(conn, today)
        print(f"Opened {path}")
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    cfg = config.load(CONFIG_PATH)
    if args.key is None:
        print()
        for k, v in cfg.items():
            print(f"  {k} = {v}")
        print()
        return 0
    key = _CONFIG_ALIASES.get(args.key, args.key)
    if args.value is None:
        print(cfg.get(key, "(unset)"))
        return 0
    coerced: int | str | bool = args.value
    if key == "daily_target":
        try:
            coerced = int(args.value)
        except ValueError:
            print(f"  daily_target must be an integer, got {args.value!r}")
            return 2
        if coerced < 1:
            print("  daily_target must be >= 1")
            return 2
    elif key in ("shuffle", "extra"):
        if args.value.lower() in ("on", "true", "1", "yes"):
            coerced = True
        elif args.value.lower() in ("off", "false", "0", "no"):
            coerced = False
        else:
            print(f"  {key} must be on/off, got {args.value!r}")
            return 2
    try:
        updated = config.set_key(CONFIG_PATH, key, coerced)
    except KeyError as e:
        print(f"  {e}")
        return 2
    print(f"  {key} = {updated[key]}")
    return 0


def cmd_skip(args: argparse.Namespace) -> int:
    conn = db.connect(DB_PATH)
    today = _parse_today(args.today)
    cfg = config.load(CONFIG_PATH)
    pick = selector.pick_today(
        conn, today,
        daily_target=cfg["daily_target"],
        shuffle=cfg["shuffle"],
        extra=cfg["extra"],
    )
    if pick.kind in ("empty", "quota_hit"):
        print("Nothing to skip.")
        return 0
    assert pick.card is not None
    next_due = today + timedelta(days=1)
    db.postpone(conn, pick.card, next_due)
    print(f"Postponed {pick.card.title} to {next_due.isoformat()}.")
    return 0


def cmd_reset(args: argparse.Namespace) -> int:
    conn = db.connect(DB_PATH)
    source: str | None = getattr(args, 'source', None)

    if source is not None:
        total_cards = conn.execute(
            'SELECT COUNT(*) FROM cards WHERE source = ?', (source,)
        ).fetchone()[0]
        reviewed = conn.execute(
            'SELECT COUNT(*) FROM cards WHERE source = ? AND next_due IS NOT NULL',
            (source,),
        ).fetchone()[0]
        scope = f'{source} cards'
    else:
        total_cards = conn.execute('SELECT COUNT(*) FROM cards').fetchone()[0]
        reviewed = conn.execute(
            'SELECT COUNT(*) FROM cards WHERE next_due IS NOT NULL'
        ).fetchone()[0]
        scope = 'ALL cards'

    if total_cards == 0:
        print(f'  No {scope} found in the deck.')
        return 0

    print()
    print(f'  {_color("Warning", RED)} This will reset {scope}:')
    print(f'    {total_cards} cards total  ({reviewed} with SRS progress, '
          f'{total_cards - reviewed} unseen)')
    print(f'    All review history for these cards will be permanently deleted.')
    print()
    try:
        answer = input(f'  Type {_color("yes", BOLD)} to confirm: ').strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return 130

    if answer != 'yes':
        print('  Aborted — nothing changed.')
        return 0

    cards_reset, reviews_deleted = db.reset_progress(conn, source)
    print()
    print(f'  {_color("Reset complete", GREEN)}: {cards_reset} cards returned to unseen, '
          f'{reviews_deleted} review records deleted.')
    print()
    return 0


# --- entrypoint -----------------------------------------------------------

def _add_shuffle_flags(parser: argparse.ArgumentParser) -> None:
    grp = parser.add_mutually_exclusive_group()
    grp.add_argument(
        "--shuffle",
        action="store_true",
        default=False,
        help="Enable shuffle mode (saved to config). Picks random problems, weighted Easy/Medium > Hard.",
    )
    grp.add_argument(
        "--no-shuffle",
        action="store_true",
        default=False,
        dest="no_shuffle",
        help="Disable shuffle mode and revert to in-order selection (saved to config).",
    )


def _add_ui_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--ui",
        action="store_true",
        default=False,
        help="Open an interactive browser UI instead of the terminal prompt.",
    )


def _add_extra_flags(parser: argparse.ArgumentParser) -> None:
    grp = parser.add_mutually_exclusive_group()
    grp.add_argument(
        "--extra",
        action="store_true",
        default=False,
        help=(
            "Enable extra mode (saved to config). Draws from both neetcode250 and secondary.json, "
            "weighting neetcode250 10%% more often. Within secondary, problems are weighted by "
            "interview frequency (first entry in secondary.json = highest probability)."
        ),
    )
    grp.add_argument(
        "--no-extra",
        action="store_true",
        default=False,
        dest="no_extra",
        help="Disable extra mode (saved to config).",
    )


def build_parser() -> argparse.ArgumentParser:
    # Parent parser with the hidden --today flag, inherited by all subparsers
    # so it works in both `neetcode --today ...` and `neetcode today --today ...`.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--today", help=argparse.SUPPRESS)

    p = argparse.ArgumentParser(
        prog="neetcode",
        description="Daily NeetCode 250 SRS.",
        parents=[common],
    )
    _add_shuffle_flags(p)
    _add_extra_flags(p)
    _add_ui_flag(p)
    sub = p.add_subparsers(dest="command")

    p_setup = sub.add_parser("setup", parents=[common],
                             help="Fetch the NeetCode 250 list and populate the deck.")
    p_setup.add_argument("--refresh", action="store_true", help="Re-fetch even if cached.")
    p_setup.set_defaults(func=cmd_setup)

    p_stats = sub.add_parser("stats", parents=[common], help="Show deck progress.")
    p_stats.set_defaults(func=cmd_stats)

    p_today = sub.add_parser("today", parents=[common], help="Show today's card (default).")
    _add_shuffle_flags(p_today)
    _add_extra_flags(p_today)
    _add_ui_flag(p_today)
    p_today.set_defaults(func=cmd_today)

    p_hist = sub.add_parser("history", parents=[common], help="Show recent reviews.")
    p_hist.add_argument("n", nargs="?", type=int, default=10)
    p_hist.set_defaults(func=cmd_history)

    p_skip = sub.add_parser("skip", parents=[common], help="Postpone today's card by one day.")
    p_skip.set_defaults(func=cmd_skip)
    p_reset = sub.add_parser(
        'reset', parents=[common],
        help='Reset card progress back to unseen. Prompts for confirmation.',
    )
    p_reset.add_argument(
        'source', nargs='?', choices=['neetcode250', 'secondary'],
        help="Which source to reset (default: all cards). "
             "'secondary' clears only the extra list; 'neetcode250' clears only the main list.",
    )
    p_reset.set_defaults(func=cmd_reset)


    p_dash = sub.add_parser("dashboard", parents=[common],
                            help="Open a local HTML progress dashboard in your browser.")
    p_dash.add_argument("--write-only", action="store_true",
                        help="Write the HTML file but don't open a browser.")
    p_dash.set_defaults(func=cmd_dashboard)

    p_cfg = sub.add_parser("config", parents=[common],
                           help="Show or set config. Example: `neetcode config daily 3`")
    p_cfg.add_argument("key", nargs="?", help="Config key (e.g. 'daily' or 'daily_target').")
    p_cfg.add_argument("value", nargs="?", help="New value (integer for daily_target).")
    p_cfg.set_defaults(func=cmd_config)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        return cmd_today(args)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

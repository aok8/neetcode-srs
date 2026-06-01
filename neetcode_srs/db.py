from __future__ import annotations

import json
import random
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from neetcode_srs.srs import CardState, EASE_START

SCHEMA = """
CREATE TABLE IF NOT EXISTS cards (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    difficulty TEXT NOT NULL,
    topics TEXT NOT NULL,
    leetcode_url TEXT NOT NULL,
    order_idx INTEGER NOT NULL,
    source TEXT NOT NULL DEFAULT 'neetcode250',
    ease REAL NOT NULL DEFAULT 2.5,
    interval_days INTEGER NOT NULL DEFAULT 0,
    reps INTEGER NOT NULL DEFAULT 0,
    next_due TEXT,
    last_reviewed TEXT
);

CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id TEXT NOT NULL REFERENCES cards(id),
    reviewed_at TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('y','n','e','skip')),
    interval_before INTEGER NOT NULL,
    interval_after INTEGER NOT NULL,
    ease_before REAL NOT NULL,
    ease_after REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cards_next_due ON cards(next_due);
CREATE INDEX IF NOT EXISTS idx_cards_order ON cards(order_idx);
"""


@dataclass
class Card:
    id: str
    title: str
    difficulty: str
    topics: list[str]
    leetcode_url: str
    order_idx: int
    source: str
    ease: float
    interval_days: int
    reps: int
    next_due: date | None
    last_reviewed: date | None

    @property
    def state(self) -> CardState:
        return CardState(ease=self.ease, interval_days=self.interval_days, reps=self.reps)


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    # Migration: add source column for existing DBs created before --extra support.
    # The index on source must come AFTER the column exists, so it can't live in SCHEMA.
    try:
        conn.execute("ALTER TABLE cards ADD COLUMN source TEXT NOT NULL DEFAULT 'neetcode250'")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # Column already exists
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cards_source ON cards(source)")
    conn.commit()
    return conn


def _row_to_card(row: sqlite3.Row) -> Card:
    return Card(
        id=row["id"],
        title=row["title"],
        difficulty=row["difficulty"],
        topics=json.loads(row["topics"]),
        leetcode_url=row["leetcode_url"],
        order_idx=row["order_idx"],
        source=row["source"],
        ease=row["ease"],
        interval_days=row["interval_days"],
        reps=row["reps"],
        next_due=date.fromisoformat(row["next_due"]) if row["next_due"] else None,
        last_reviewed=date.fromisoformat(row["last_reviewed"]) if row["last_reviewed"] else None,
    )


def sync_problems(
    conn: sqlite3.Connection, problems: list[dict], source: str = "neetcode250"
) -> tuple[int, int]:
    """Upsert problems and remove unseen stale cards from that source.

    Returns (upserted_count, removed_count). Cards that have already been
    reviewed (next_due IS NOT NULL) are never deleted even if they've been
    removed from the list, so SRS progress is always preserved.
    """
    upsert_problems(conn, problems, source)
    keep_ids = {p["id"] for p in problems}
    stale = conn.execute(
        "SELECT id FROM cards WHERE source = ? AND next_due IS NULL",
        (source,),
    ).fetchall()
    to_delete = [r["id"] for r in stale if r["id"] not in keep_ids]
    if to_delete:
        with conn:
            conn.executemany("DELETE FROM cards WHERE id = ?", [(i,) for i in to_delete])
    return len(problems), len(to_delete)


def upsert_problems(
    conn: sqlite3.Connection, problems: list[dict], source: str = "neetcode250"
) -> int:
    with conn:
        for idx, p in enumerate(problems):
            if source == "neetcode250":
                # neetcode250 always wins: update everything including source so it
                # takes precedence over any secondary entry for the same problem.
                conn.execute(
                    """
                    INSERT INTO cards (id, title, difficulty, topics, leetcode_url, order_idx, source, ease)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        title = excluded.title,
                        difficulty = excluded.difficulty,
                        topics = excluded.topics,
                        leetcode_url = excluded.leetcode_url,
                        order_idx = excluded.order_idx,
                        source = excluded.source
                    """,
                    (
                        p["id"],
                        p["title"],
                        p["difficulty"],
                        json.dumps(p["topics"]),
                        p["leetcode_url"],
                        idx,
                        source,
                        EASE_START,
                    ),
                )
            else:
                # Secondary: insert new cards only; on conflict update metadata but
                # never overwrite source or order_idx so neetcode250 cards keep their
                # classification and position.
                conn.execute(
                    """
                    INSERT INTO cards (id, title, difficulty, topics, leetcode_url, order_idx, source, ease)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        title = excluded.title,
                        difficulty = excluded.difficulty,
                        topics = excluded.topics,
                        leetcode_url = excluded.leetcode_url
                    """,
                    (
                        p["id"],
                        p["title"],
                        p["difficulty"],
                        json.dumps(p["topics"]),
                        p["leetcode_url"],
                        idx,
                        source,
                        EASE_START,
                    ),
                )
    return len(problems)


def get_card(conn: sqlite3.Connection, card_id: str) -> Card | None:
    row = conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
    return _row_to_card(row) if row else None


def reviewed_today(conn: sqlite3.Connection, today: date) -> Card | None:
    row = conn.execute(
        "SELECT * FROM cards WHERE last_reviewed = ? ORDER BY id LIMIT 1",
        (today.isoformat(),),
    ).fetchone()
    return _row_to_card(row) if row else None


def count_reviewed_on(conn: sqlite3.Connection, day: date) -> int:
    """Count distinct cards answered (y/n/e â€” not skip) on a given day."""
    row = conn.execute(
        """
        SELECT COUNT(DISTINCT card_id) FROM reviews
        WHERE date(reviewed_at) = ? AND outcome IN ('y','n','e')
        """,
        (day.isoformat(),),
    ).fetchone()
    return row[0]


def pick_due(conn: sqlite3.Connection, today: date) -> Card | None:
    row = conn.execute(
        """
        SELECT * FROM cards
        WHERE next_due IS NOT NULL AND next_due <= ?
        ORDER BY next_due ASC, ease ASC, order_idx ASC
        LIMIT 1
        """,
        (today.isoformat(),),
    ).fetchone()
    return _row_to_card(row) if row else None


def pick_new(conn: sqlite3.Connection) -> Card | None:
    # Easy â†’ Medium â†’ Hard, then by NeetCode order within a tier.
    # Only introduces neetcode250 cards; secondary cards are only ever
    # introduced via pick_new_extra when --extra is active.
    row = conn.execute(
        """
        SELECT * FROM cards
        WHERE next_due IS NULL AND source = 'neetcode250'
        ORDER BY
            CASE difficulty
                WHEN 'Easy' THEN 0
                WHEN 'Medium' THEN 1
                WHEN 'Hard' THEN 2
                ELSE 3
            END,
            order_idx ASC
        LIMIT 1
        """
    ).fetchone()
    return _row_to_card(row) if row else None


_SHUFFLE_BUCKET_WEIGHTS = {"Easy": 35, "Medium": 50, "Hard": 15}

# 60 / 40 source split: neetcode250 drawn 3 parts, secondary 2 parts.
_SOURCE_WEIGHTS = {"neetcode250": 3, "secondary": 2}

# Exponential decay half-life for secondary frequency weighting.
# At rank 50 a problem is half as likely as rank 0; at rank 100 it's 1/4; at
# rank 200 it's 1/16; at rank 415 it's ~1/250. Problems near the bottom of the
# frequency list are genuinely rare regardless of difficulty-bucket size.
_SECONDARY_FREQ_HALFLIFE = 50


def pick_new_shuffle(conn: sqlite3.Connection) -> Card | None:
    """Pick a random unseen neetcode250 card weighted Easy 35% / Medium 50% / Hard 15%.

    Only draws from neetcode250 cards; secondary cards are only ever introduced
    via pick_new_extra when --extra is active.
    """
    counts = {}
    for diff in ("Easy", "Medium", "Hard"):
        row = conn.execute(
            "SELECT COUNT(*) FROM cards WHERE next_due IS NULL AND difficulty = ? AND source = 'neetcode250'",
            (diff,),
        ).fetchone()
        counts[diff] = row[0]

    available = [(d, _SHUFFLE_BUCKET_WEIGHTS[d]) for d in ("Easy", "Medium", "Hard") if counts[d] > 0]
    if not available:
        return None

    diffs, weights = zip(*available)
    chosen = random.choices(diffs, weights=weights, k=1)[0]

    row = conn.execute(
        "SELECT * FROM cards WHERE next_due IS NULL AND difficulty = ? AND source = 'neetcode250'"
        " ORDER BY RANDOM() LIMIT 1",
        (chosen,),
    ).fetchone()
    return _row_to_card(row) if row else None


def pick_new_extra(conn: sqlite3.Connection) -> Card | None:
    """Combined-pool selection for --extra mode.

    Source selection: neetcode250 60% / secondary 40% (weights 3:2).
    Difficulty selection: Easy 35% / Medium 50% / Hard 15% within the chosen source.
    Secondary cards use exponential frequency decay keyed on order_idx so that
    rank-0 problems are drawn ~250Ã— more often than rank-415 problems, regardless
    of how many cards happen to be in the chosen difficulty bucket.
    neetcode250 cards within a difficulty bucket are drawn uniformly at random.
    """
    nc250: dict[str, int] = {}
    sec: dict[str, int] = {}
    for diff in ("Easy", "Medium", "Hard"):
        nc250[diff] = conn.execute(
            "SELECT COUNT(*) FROM cards WHERE next_due IS NULL AND difficulty = ? AND source = 'neetcode250'",
            (diff,),
        ).fetchone()[0]
        sec[diff] = conn.execute(
            "SELECT COUNT(*) FROM cards WHERE next_due IS NULL AND difficulty = ? AND source = 'secondary'",
            (diff,),
        ).fetchone()[0]

    nc250_has = any(nc250.values())
    sec_has = any(sec.values())
    if not nc250_has and not sec_has:
        return None

    # Choose source.
    sources: list[str] = []
    s_weights: list[float] = []
    if nc250_has:
        sources.append("neetcode250")
        s_weights.append(_SOURCE_WEIGHTS["neetcode250"])
    if sec_has:
        sources.append("secondary")
        s_weights.append(_SOURCE_WEIGHTS["secondary"])
    chosen_source = random.choices(sources, weights=s_weights, k=1)[0]

    by_diff = nc250 if chosen_source == "neetcode250" else sec

    # Choose difficulty bucket.
    available = [
        (d, _SHUFFLE_BUCKET_WEIGHTS[d]) for d in ("Easy", "Medium", "Hard") if by_diff[d] > 0
    ]
    diffs, d_weights = zip(*available)
    chosen_diff = random.choices(diffs, weights=d_weights, k=1)[0]

    if chosen_source == "neetcode250":
        row = conn.execute(
            "SELECT * FROM cards WHERE next_due IS NULL AND difficulty = ? AND source = 'neetcode250'"
            " ORDER BY RANDOM() LIMIT 1",
            (chosen_diff,),
        ).fetchone()
        return _row_to_card(row) if row else None

    # Secondary: exponential frequency decay by order_idx.
    # weight = 2^(-order_idx / HALFLIFE) so rank-0 problems dominate and
    # bottom-ranked problems are extremely rare no matter the bucket size.
    rows = conn.execute(
        "SELECT * FROM cards WHERE next_due IS NULL AND difficulty = ? AND source = 'secondary'"
        " ORDER BY order_idx ASC",
        (chosen_diff,),
    ).fetchall()
    if not rows:
        return None

    cards = [_row_to_card(r) for r in rows]
    freq_weights = [2.0 ** (-c.order_idx / _SECONDARY_FREQ_HALFLIFE) for c in cards]
    return random.choices(cards, weights=freq_weights, k=1)[0]


def apply_review(
    conn: sqlite3.Connection,
    card: Card,
    outcome: str,
    new_state: CardState,
    next_due: date,
    today: date,
) -> None:
    with conn:
        conn.execute(
            """
            UPDATE cards SET
                ease = ?, interval_days = ?, reps = ?,
                next_due = ?, last_reviewed = ?
            WHERE id = ?
            """,
            (
                new_state.ease,
                new_state.interval_days,
                new_state.reps,
                next_due.isoformat(),
                today.isoformat(),
                card.id,
            ),
        )
        conn.execute(
            """
            INSERT INTO reviews
                (card_id, reviewed_at, outcome, interval_before, interval_after, ease_before, ease_after)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                card.id,
                datetime.now().isoformat(timespec="seconds"),
                outcome,
                card.interval_days,
                new_state.interval_days,
                card.ease,
                new_state.ease,
            ),
        )


def postpone(conn: sqlite3.Connection, card: Card, next_due: date) -> None:
    with conn:
        conn.execute(
            "UPDATE cards SET next_due = ? WHERE id = ?",
            (next_due.isoformat(), card.id),
        )
        conn.execute(
            """
            INSERT INTO reviews
                (card_id, reviewed_at, outcome, interval_before, interval_after, ease_before, ease_after)
            VALUES (?, ?, 'skip', ?, ?, ?, ?)
            """,
            (
                card.id,
                datetime.now().isoformat(timespec="seconds"),
                card.interval_days,
                card.interval_days,
                card.ease,
                card.ease,
            ),
        )



def reset_progress(
    conn: sqlite3.Connection, source: str | None = None
) -> tuple[int, int]:
    """Reset card progress to unseen and delete review history.

    If source is given ('secondary' or 'neetcode250') only that source is
    affected.  Otherwise every card in the deck is reset.

    Returns (cards_reset, reviews_deleted).
    """
    with conn:
        if source is not None:
            card_ids = [
                r["id"]
                for r in conn.execute(
                    "SELECT id FROM cards WHERE source = ?", (source,)
                ).fetchall()
            ]
        else:
            card_ids = [
                r["id"] for r in conn.execute("SELECT id FROM cards").fetchall()
            ]

        if not card_ids:
            return 0, 0

        placeholders = ",".join("?" * len(card_ids))
        reviews_deleted = conn.execute(
            f"SELECT COUNT(*) FROM reviews WHERE card_id IN ({placeholders})",
            card_ids,
        ).fetchone()[0]

        conn.execute(
            f"UPDATE cards SET ease = {EASE_START}, interval_days = 0, reps = 0,"
            f" next_due = NULL, last_reviewed = NULL"
            f" WHERE id IN ({placeholders})",
            card_ids,
        )
        conn.execute(
            f"DELETE FROM reviews WHERE card_id IN ({placeholders})",
            card_ids,
        )

    return len(card_ids), reviews_deleted

def stats(conn: sqlite3.Connection, today: date) -> dict:
    total = conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
    new = conn.execute("SELECT COUNT(*) FROM cards WHERE next_due IS NULL").fetchone()[0]
    learning = conn.execute(
        "SELECT COUNT(*) FROM cards WHERE next_due IS NOT NULL AND reps < 2"
    ).fetchone()[0]
    mature = conn.execute(
        "SELECT COUNT(*) FROM cards WHERE reps >= 2"
    ).fetchone()[0]
    due_today = conn.execute(
        "SELECT COUNT(*) FROM cards WHERE next_due IS NOT NULL AND next_due <= ?",
        (today.isoformat(),),
    ).fetchone()[0]
    by_difficulty = {
        d: {
            "total": conn.execute(
                "SELECT COUNT(*) FROM cards WHERE difficulty = ?", (d,)
            ).fetchone()[0],
            "seen": conn.execute(
                "SELECT COUNT(*) FROM cards WHERE difficulty = ? AND next_due IS NOT NULL",
                (d,),
            ).fetchone()[0],
        }
        for d in ("Easy", "Medium", "Hard")
    }
    return {
        "total": total,
        "new": new,
        "learning": learning,
        "mature": mature,
        "due_today": due_today,
        "by_difficulty": by_difficulty,
    }


def recent_reviews(conn: sqlite3.Connection, limit: int = 10) -> list[dict]:
    rows = conn.execute(
        """
        SELECT r.*, c.title, c.difficulty
        FROM reviews r JOIN cards c ON c.id = r.card_id
        ORDER BY r.id DESC LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]

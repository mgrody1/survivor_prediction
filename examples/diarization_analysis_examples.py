#!/usr/bin/env python3
"""
Examples of analyzing diarized Survivor episodes.

The diarized parquet files contain:
- subtitle_text: Full transcribed text (LOCAL ONLY, not in Postgres)
- castaway: Who said it (after labeling)
- castaway_id: Database ID for the speaker
- start_time, end_time: When it was said
- word_count: Number of words

This enables analyses like:
1. Kalshi prediction markets (Jeff's word usage)
2. Castaway screen time and speaking patterns
3. Tribal council vs camp dialogue analysis
4. Vocabulary complexity over season progression
5. Quote extraction for social media
"""

import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if REPO_ROOT not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from gamebot_core.media_diarization import (  # noqa: E402
    DIARIZED_PARQUET_DIR,
    VERSION_COUNTRY,
)


def load_season_data(season: int, episode: int = None):
    """Load all diarized data for a season."""
    version_season = f"{VERSION_COUNTRY}{season:02d}"

    if episode:
        files = [
            DIARIZED_PARQUET_DIR / f"{version_season}_E{episode:02d}_diarized.parquet"
        ]
    else:
        files = sorted(
            DIARIZED_PARQUET_DIR.glob(f"{version_season}_E*_diarized.parquet")
        )

    dfs = [pd.read_parquet(f) for f in files if f.exists()]
    return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()


# =============================================================================
# Example 1: Kalshi Market - Jeff's Specific Words
# =============================================================================
def kalshi_jeff_words(season: int, target_words: list[str]):
    """
    Count Jeff's usage of specific words for Kalshi betting markets.

    Example:
        kalshi_jeff_words(1, ["immunity", "idol", "fire", "tribe"])
    """
    df = load_season_data(season)
    jeff = df[df["castaway"].str.contains("Jeff", case=False, na=False)]

    results = {}
    for word in target_words:
        count = (
            jeff["subtitle_text"]
            .str.contains(word, case=False, na=False, regex=False)
            .sum()
        )
        results[word] = count

    return results


# =============================================================================
# Example 2: Screen Time Analysis
# =============================================================================
def screen_time_by_castaway(season: int, episode: int = None):
    """
    Calculate total speaking time per castaway.

    Returns:
        DataFrame with: castaway, total_seconds, total_utterances, total_words
    """
    df = load_season_data(season, episode)

    # Calculate duration of each utterance
    df["duration"] = df["end_time"] - df["start_time"]

    # Group by castaway
    stats = (
        df.groupby("castaway")
        .agg(
            total_seconds=("duration", "sum"),
            total_utterances=("castaway", "count"),
            total_words=("word_count", "sum"),
        )
        .reset_index()
    )

    stats["avg_words_per_utterance"] = stats["total_words"] / stats["total_utterances"]
    stats = stats.sort_values("total_seconds", ascending=False)

    return stats


# =============================================================================
# Example 3: Episode-by-Episode Speaking Trends
# =============================================================================
def speaking_trend_over_season(season: int, castaway_name: str):
    """
    Track how much a specific castaway speaks in each episode.

    Useful for:
    - Identifying "quiet" vs "loud" episodes
    - Predicting eliminations (speaking time often drops before boot)
    """
    df = load_season_data(season)
    castaway_df = df[df["castaway"].str.contains(castaway_name, case=False, na=False)]

    episode_stats = (
        castaway_df.groupby("episode")
        .agg(
            utterances=("castaway", "count"),
            total_words=("word_count", "sum"),
            avg_words=("word_count", "mean"),
        )
        .reset_index()
    )

    return episode_stats


# =============================================================================
# Example 4: Find Memorable Quotes
# =============================================================================
def find_long_quotes(season: int, min_words: int = 50, castaway: str = None):
    """
    Extract long monologues or memorable quotes.

    Args:
        season: Season number
        min_words: Minimum word count to be considered "long"
        castaway: Optional filter to specific person
    """
    df = load_season_data(season)

    long_quotes = df[df["word_count"] >= min_words].copy()

    if castaway:
        long_quotes = long_quotes[
            long_quotes["castaway"].str.contains(castaway, case=False, na=False)
        ]

    long_quotes = long_quotes.sort_values("word_count", ascending=False)

    return long_quotes[["episode", "castaway", "word_count", "subtitle_text"]]


# =============================================================================
# Example 5: Jeff's Iconic Phrases
# =============================================================================
def jeff_catchphrases(season: int):
    """
    Count Jeff's iconic catchphrases.
    """
    phrases = [
        "the tribe has spoken",
        "come on in",
        "wanna know what you're playing for",
        "worth playing for",
        "fire represents life",
        "immunity is back up for grabs",
        "got nothing for you",
    ]

    return kalshi_jeff_words(season, phrases)


# =============================================================================
# Main Demo
# =============================================================================
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Diarization analysis examples")
    parser.add_argument("--season", type=int, default=1, help="Season number")
    args = parser.parse_args()

    season = args.season

    print(f"\n{'=' * 80}")
    print(f"SURVIVOR SEASON {season} - DIARIZATION ANALYSIS EXAMPLES")
    print(f"{'=' * 80}\n")

    # Example 1: Screen time
    print("📊 SCREEN TIME ANALYSIS")
    print("-" * 80)
    screen_time = screen_time_by_castaway(season)
    print(screen_time.head(10).to_string(index=False))
    print()

    # Example 2: Jeff's catchphrases
    print("\n🎙️  JEFF'S CATCHPHRASES")
    print("-" * 80)
    phrases = jeff_catchphrases(season)
    for phrase, count in sorted(phrases.items(), key=lambda x: x[1], reverse=True):
        if count > 0:
            print(f"  '{phrase}': {count} times")
    print()

    # Example 3: Long quotes
    print("\n💬 LONGEST QUOTES (50+ words)")
    print("-" * 80)
    long_quotes = find_long_quotes(season, min_words=50)
    for idx, row in long_quotes.head(3).iterrows():
        print(
            f"\nEpisode {row['episode']} - {row['castaway']} ({row['word_count']} words):"
        )
        print(f"  {row['subtitle_text'][:200]}...")
    print()

#!/usr/bin/env python3
"""
Analyze Jeff Probst's word usage from diarized episodes.

Use case: Kalshi Survivor mention markets
- Track specific words Jeff says per episode
- Count phrase frequencies ("the tribe has spoken", "come on in", etc.)
- Identify betting opportunities

Example usage:
    # All Jeff quotes from Season 1
    python examples/jeff_word_analysis.py --season 1

    # Search for specific words/phrases
    python examples/jeff_word_analysis.py --season 1 --words "immunity" "idol" "tribe"

    # Episode-specific analysis
    python examples/jeff_word_analysis.py --season 1 --episode 5 --words "merge"
"""

import sys
from pathlib import Path
from collections import Counter
import argparse
import re

import pandas as pd

# Add repo root to path
REPO_ROOT = Path(__file__).resolve().parent.parent
if REPO_ROOT not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from gamebot_core.media_diarization import (  # noqa: E402
    DIARIZED_PARQUET_DIR,
    VERSION_COUNTRY,
)


def load_jeff_utterances(season: int, episode: int = None):
    """
    Load all Jeff Probst utterances from diarized parquet files.

    Args:
        season: Season number
        episode: Optional episode number (if None, loads all episodes)

    Returns:
        DataFrame with columns: episode, start_time, end_time, subtitle_text, word_count
    """
    version_season = f"{VERSION_COUNTRY}{season:02d}"

    if episode:
        # Single episode
        parquet_files = [
            DIARIZED_PARQUET_DIR / f"{version_season}_E{episode:02d}_diarized.parquet"
        ]
    else:
        # All episodes for this season
        parquet_files = sorted(
            DIARIZED_PARQUET_DIR.glob(f"{version_season}_E*_diarized.parquet")
        )

    if not parquet_files:
        print(f"No diarized files found for {version_season}")
        return pd.DataFrame()

    all_jeff = []
    for pq_file in parquet_files:
        if not pq_file.exists():
            continue

        df = pd.read_parquet(pq_file)

        # Filter to Jeff Probst only
        # Adjust castaway name/ID as needed based on your labeling
        jeff_df = df[df["castaway"].str.contains("Jeff", case=False, na=False)].copy()

        if not jeff_df.empty:
            all_jeff.append(jeff_df)

    if not all_jeff:
        print(f"No Jeff utterances found for {version_season}")
        return pd.DataFrame()

    combined = pd.concat(all_jeff, ignore_index=True)
    return combined[
        ["episode", "start_time", "end_time", "subtitle_text", "word_count"]
    ]


def count_word_mentions(df: pd.DataFrame, target_words: list[str]):
    """
    Count how many times target words/phrases appear in Jeff's speech.

    Args:
        df: DataFrame with subtitle_text column
        target_words: List of words/phrases to search for (case-insensitive)

    Returns:
        Dict mapping word -> count
    """
    counts = {word: 0 for word in target_words}

    for text in df["subtitle_text"]:
        text_lower = str(text).lower()
        for word in target_words:
            # Use word boundaries for exact word matching
            pattern = r"\b" + re.escape(word.lower()) + r"\b"
            matches = len(re.findall(pattern, text_lower))
            counts[word] += matches

    return counts


def find_all_words(df: pd.DataFrame, min_count: int = 2):
    """
    Get frequency distribution of all words Jeff says.

    Args:
        df: DataFrame with subtitle_text column
        min_count: Only show words appearing at least this many times

    Returns:
        Counter object with word frequencies
    """
    all_words = []
    for text in df["subtitle_text"]:
        # Simple word tokenization (improve with nltk if needed)
        words = re.findall(r"\b[a-z]+\b", str(text).lower())
        all_words.extend(words)

    word_freq = Counter(all_words)

    # Filter by min count
    return {word: count for word, count in word_freq.items() if count >= min_count}


def main():
    parser = argparse.ArgumentParser(description="Analyze Jeff Probst's word usage")
    parser.add_argument("--season", type=int, required=True, help="Season number")
    parser.add_argument("--episode", type=int, help="Specific episode (optional)")
    parser.add_argument(
        "--words", nargs="+", help="Specific words/phrases to search for"
    )
    parser.add_argument(
        "--top", type=int, default=20, help="Show top N most common words"
    )
    parser.add_argument(
        "--min-count", type=int, default=2, help="Min word count to display"
    )
    parser.add_argument("--export", help="Export results to CSV file")

    args = parser.parse_args()

    # Load Jeff's utterances
    print(f"\n{'=' * 80}")
    print(f"Loading Jeff Probst utterances for Season {args.season}")
    if args.episode:
        print(f"Episode: {args.episode}")
    print(f"{'=' * 80}\n")

    jeff_df = load_jeff_utterances(args.season, args.episode)

    if jeff_df.empty:
        print("No data found!")
        return

    # Summary stats
    print(f"Total Jeff utterances: {len(jeff_df)}")
    print(f"Total words spoken: {jeff_df['word_count'].sum()}")
    print(f"Episodes covered: {jeff_df['episode'].nunique()}")
    print(f"Average words per utterance: {jeff_df['word_count'].mean():.1f}")
    print()

    # Specific word search
    if args.words:
        print(f"\n{'=' * 80}")
        print("WORD/PHRASE COUNTS (Kalshi Market Analysis)")
        print(f"{'=' * 80}")
        counts = count_word_mentions(jeff_df, args.words)
        for word, count in sorted(counts.items(), key=lambda x: x[1], reverse=True):
            print(f"  {word:30s} : {count:4d} mentions")
        print()

    # Overall word frequency
    print(f"\n{'=' * 80}")
    print(f"TOP {args.top} MOST COMMON WORDS")
    print(f"{'=' * 80}")
    word_freq = find_all_words(jeff_df, min_count=args.min_count)
    for word, count in sorted(word_freq.items(), key=lambda x: x[1], reverse=True)[
        : args.top
    ]:
        print(f"  {word:30s} : {count:4d}")
    print()

    # Export if requested
    if args.export:
        export_path = Path(args.export)
        jeff_df.to_csv(export_path, index=False)
        print(f"✅ Exported to: {export_path}")

    # Sample quotes
    print(f"\n{'=' * 80}")
    print("SAMPLE JEFF QUOTES")
    print(f"{'=' * 80}")
    for idx, row in jeff_df.head(5).iterrows():
        print(f"\nEpisode {row['episode']}, {row['start_time']:.1f}s:")
        print(f'  "{row["subtitle_text"]}"')


if __name__ == "__main__":
    main()

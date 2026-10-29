"""Synthetic order history generator.

Responsibility:
Generates synthetic order CSVs simulating realistic Indian F&O trading activity with
embedded, ground-truth behavioral habits (e.g., revenge trading, overtrading, holding losers).
"""

from pathlib import Path


def generate_synthetic_dataset(output_path: Path, habit_type: str | None = None) -> Path:
    """Generate a synthetic CSV dataset with known injected habits."""
    return output_path

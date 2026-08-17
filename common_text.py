from __future__ import annotations
import re
from typing import List, Tuple

# Domain-agnostic normalization: remove whitespace + common punctuation
_PUNCT_RX = re.compile(r"[\s\-\_\(\)\[\]\{\}\.,;:/\\'\"`~!@#$%^&*+=<>?|]+")

def normalize_with_map(text: str) -> Tuple[str, List[int]]:
    """
    Normalize by removing whitespace/punct and lowering ASCII letters.
    Returns (normalized_text, idx_map) where idx_map[norm_i] = original_index.
    """
    norm_chars: List[str] = []
    idx_map: List[int] = []
    for i, ch in enumerate(text):
        if _PUNCT_RX.match(ch):
            continue
        norm_chars.append(ch.lower())
        idx_map.append(i)
    return "".join(norm_chars), idx_map

def normalize(text: str) -> str:
    return normalize_with_map(text)[0]

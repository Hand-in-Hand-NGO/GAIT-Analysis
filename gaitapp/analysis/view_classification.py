"""Heuristic classifier distinguishing front-facing vs side-on camera views.

Used to validate that the user assigned "front video" / "side video" to the
correct files before running full analysis, so a mixed-up pair fails fast
with a clear message instead of producing silently wrong gait metrics.

Heuristic: in a side-on view the shoulders (and hips) are seen nearly
edge-on, so their pixel width is small relative to torso height. In a
front-on view the shoulders are seen face-on, so shoulder width is large
relative to torso height. This ratio is averaged over all confidently
detected frames in the clip.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np

from gaitapp.analysis.landmarks import KeypointName, PoseFrame

# Empirically, side-view shoulder-width/torso-height ratios cluster well
# below 1.0 (shoulders foreshortened), while front-view ratios cluster
# well above 1.0 (full shoulder span visible). A frame landing between the
# two is ambiguous and excluded from the vote rather than guessed at.
SIDE_VIEW_MAX_RATIO = 0.7
FRONT_VIEW_MIN_RATIO = 1.0


class ViewType(str, Enum):
    FRONT = "front"
    SIDE = "side"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ViewClassificationResult:
    view_type: ViewType
    confidence: float  # fraction of confidently-classified frames agreeing
    frames_considered: int
    frames_classified: int


def classify_view(frames: list[PoseFrame], min_confidence: float = 0.3) -> ViewClassificationResult:
    ratios = []
    for pf in frames:
        if not (
            pf.is_visible(KeypointName.LEFT_SHOULDER, min_confidence)
            and pf.is_visible(KeypointName.RIGHT_SHOULDER, min_confidence)
            and pf.is_visible(KeypointName.LEFT_HIP, min_confidence)
            and pf.is_visible(KeypointName.RIGHT_HIP, min_confidence)
        ):
            continue
        torso = pf.torso_height
        if torso <= 1e-3:
            continue
        ratios.append(pf.shoulder_width / torso)

    frames_considered = len(frames)
    if not ratios:
        return ViewClassificationResult(ViewType.UNKNOWN, 0.0, frames_considered, 0)

    ratios_arr = np.array(ratios)
    side_votes = int(np.sum(ratios_arr <= SIDE_VIEW_MAX_RATIO))
    front_votes = int(np.sum(ratios_arr >= FRONT_VIEW_MIN_RATIO))
    frames_classified = side_votes + front_votes

    if frames_classified == 0:
        return ViewClassificationResult(ViewType.UNKNOWN, 0.0, frames_considered, len(ratios))

    if side_votes >= front_votes:
        return ViewClassificationResult(
            ViewType.SIDE, side_votes / frames_classified, frames_considered, frames_classified
        )
    return ViewClassificationResult(
        ViewType.FRONT, front_votes / frames_classified, frames_considered, frames_classified
    )

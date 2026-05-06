from __future__ import annotations

from .models import RejectionRecord
from .reporter import ExistingPlanSummary

_SYSTEM_WRAPPER = """\
You are a senior software engineer reviewing a codebase for improvements.
Analyze the codebase in the current working directory.

USER'S REQUEST:
{user_prompt}

IMPORTANT RULES:
- Find exactly ONE improvement matching the user's request. Do not list multiple.
- Be specific: name exact files, functions, line ranges.
- Provide concrete implementation steps, not vague suggestions.
- If you genuinely cannot find any more improvements, set found_nothing to true.
- ALWAYS fill the `keyword` field with a single PascalCase Feature or
  Component name that identifies the area of the codebase touched by this
  plan. The keyword is used to route the plan to a human owner, so it must
  be a feature/component name — NOT an error class, severity tag, or
  generic acronym.
    - Good keywords: `LoginFlow`, `PaymentCheckout`, `InventoryUI`,
      `MatchmakingService`, `AssetPipeline`, `PushNotification`.
    - Bad keywords: `NRE`, `Bug`, `Crash`, `Perf`, `Refactor`, `Misc`,
      `Error`, `Issue` (these don't tell anyone whose feature it is).
  Pick the keyword from the actual feature/component name as it appears in
  the code (module name, system name, screen name, etc.) whenever possible.
{rejection_context}{existing_context}
"""

_REJECTION_CONTEXT_TEMPLATE = """
PREVIOUSLY REJECTED PLANS (do NOT suggest these or similar ideas again):
{rejections}
"""

_EXISTING_CONTEXT_TEMPLATE = """
PLANS ALREADY REPORTED (pending / working / reviewed / reject — do NOT
propose anything that duplicates or substantially overlaps these. Only
filenames were inspected, so use the keyword and title to judge overlap):
{existing}
"""


MAX_REJECTIONS_IN_PROMPT = 50
MAX_EXISTING_IN_PROMPT = 200


def build_prompt(
    user_prompt: str,
    rejected_plans: list[RejectionRecord],
    existing_plans: list[ExistingPlanSummary] | None = None,
) -> str:
    """Wrap user prompt with system instructions, rejections, and existing-plan context."""
    if rejected_plans:
        recent = rejected_plans[-MAX_REJECTIONS_IN_PROMPT:]
        lines = []
        if len(rejected_plans) > MAX_REJECTIONS_IN_PROMPT:
            lines.append(
                f"  (showing {MAX_REJECTIONS_IN_PROMPT} most recent "
                f"of {len(rejected_plans)} total)"
            )
        for i, r in enumerate(recent, 1):
            lines.append(f"  {i}. [{r.category}] {r.title}")
        rejection_text = _REJECTION_CONTEXT_TEMPLATE.format(
            rejections="\n".join(lines)
        )
    else:
        rejection_text = ""

    if existing_plans:
        recent = existing_plans[-MAX_EXISTING_IN_PROMPT:]
        lines = []
        if len(existing_plans) > MAX_EXISTING_IN_PROMPT:
            lines.append(
                f"  (showing {MAX_EXISTING_IN_PROMPT} most recent "
                f"of {len(existing_plans)} total)"
            )
        for i, p in enumerate(recent, 1):
            lines.append(f"  {i}. [{p.status}] [{p.keyword}] {p.title}")
        existing_text = _EXISTING_CONTEXT_TEMPLATE.format(
            existing="\n".join(lines)
        )
    else:
        existing_text = ""

    return _SYSTEM_WRAPPER.format(
        user_prompt=user_prompt,
        rejection_context=rejection_text,
        existing_context=existing_text,
    )

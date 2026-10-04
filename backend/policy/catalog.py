"""AO-selectable risk policy catalog.

Each setting is a closed list of options (rendered as a drop-down), a secure
default, and a risk statement per option so the Authorizing Official sees what
is being accepted. Options carry a strictness rank; choosing a lower-ranked
option than the current one is a relaxation and requires a written
justification. Some controls are deliberately absent from the catalog and
cannot be switched off: the release gate itself, AI-assistance disclosure,
fail-closed auditing, and PDP filtering.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

LEVELS = ["U", "C", "S", "TS", "TS/SCI"]
_RANK = {lv: i for i, lv in enumerate(LEVELS)}


@dataclass(frozen=True)
class Option:
    value: str
    label: str
    strictness: int
    risk: str


@dataclass(frozen=True)
class Setting:
    key: str
    label: str
    scope: str                      # "per_level" | "global"
    help: str
    options: List[Option]
    default: object                 # str for global, {level: str} for per_level
    group: str = "Release controls"

    def option(self, value: str) -> Optional[Option]:
        return next((o for o in self.options if o.value == value), None)


CATALOG: List[Setting] = [
    Setting(
        key="citation_enforcement",
        label="Citation enforcement",
        scope="per_level",
        help="What happens when a model-drafted sentence has no source citation. "
             "Applied by the product's banner classification.",
        options=[
            Option("block", "Block submission on uncited claims", 3,
                   "Lowest risk. Uncited claims must be cited, removed, or tagged as the "
                   "author's analytic judgment before review."),
            Option("acknowledge", "Flag uncited claims; reviewer must disposition each", 2,
                   "Moderate risk. Uncited claims can reach review, but each one needs a "
                   "named reviewer's recorded disposition before release."),
            Option("advisory", "Show flags only; no disposition required", 1,
                   "Highest risk. Uncited claims are highlighted but nothing stops release. "
                   "Relies entirely on reviewer diligence."),
        ],
        default={"U": "acknowledge", "C": "acknowledge", "S": "block",
                 "TS": "block", "TS/SCI": "block"},
    ),
    Setting(
        key="review_rule",
        label="Release review rule",
        scope="per_level",
        help="Who must approve an AI-assisted product before release. The author can "
             "never approve or release their own product.",
        options=[
            Option("two_person", "Two-person: separate reviewer and releaser", 2,
                   "Lowest risk. Substance review and release authority are held by "
                   "different people, neither of them the author."),
            Option("single", "Single reviewer, different from the author", 1,
                   "Moderate risk. One person both checks substance and authorizes "
                   "release. Faster, with less separation of duties."),
        ],
        default={"U": "single", "C": "single", "S": "two_person",
                 "TS": "two_person", "TS/SCI": "two_person"},
    ),
    Setting(
        key="model_ceiling_mode",
        label="Model classification ceiling",
        scope="global",
        group="Model controls",
        help="Which classification limit is applied before retrieved content is sent "
             "to a model.",
        options=[
            Option("enforced", "Enforce each model's approved ceiling", 2,
                   "Lowest risk. Content above a model's approved level is withheld from "
                   "that model even when the user is cleared for it."),
            Option("system_high", "System-high: every model runs at the system high", 1,
                   "Moderate risk. Appropriate only when every enabled model operates inside "
                   "the accredited boundary. Content above system high is still withheld."),
        ],
        default="enforced",
    ),
    Setting(
        key="egress_mode",
        label="Model network egress",
        scope="global",
        group="Model controls",
        help="Where the tool may send prompts and retrieved content.",
        options=[
            Option("local_only", "Local machine and declared enclave networks only", 2,
                   "Lowest risk. Cloud model endpoints are refused regardless of "
                   "configuration. Required for air-gapped deployments."),
            Option("allowlist", "Allow AO-approved endpoints, including cloud", 1,
                   "Moderate risk. Each non-local endpoint must be individually approved by "
                   "an AO and data leaves the host for that provider."),
        ],
        default="local_only",
    ),
    Setting(
        key="system_high",
        label="System high",
        scope="global",
        group="Model controls",
        help="Highest classification this installation is accredited to process. Ingest "
             "and model ceilings above this level are refused.",
        options=[
            Option(lv, lv, len(LEVELS) - i,
                   "Content up to {} may be ingested and processed.".format(lv))
            for i, lv in enumerate(LEVELS)
        ],
        default="U",
    ),
    Setting(
        key="session_idle_minutes",
        label="Session idle timeout",
        scope="global",
        group="Account controls",
        help="Inactive sessions are terminated after this many minutes.",
        options=[
            Option("15", "15 minutes", 3, "Lowest risk."),
            Option("30", "30 minutes", 2, "Moderate risk."),
            Option("60", "60 minutes", 1, "Higher risk of unattended sessions."),
        ],
        default="15",
    ),
    Setting(
        key="lockout_threshold",
        label="Failed sign-in lockout",
        scope="global",
        group="Account controls",
        help="Local accounts lock for 15 minutes after this many consecutive failures.",
        options=[
            Option("3", "3 attempts", 3, "Lowest risk."),
            Option("5", "5 attempts", 2, "Moderate risk."),
            Option("10", "10 attempts", 1, "Higher exposure to password guessing."),
        ],
        default="3",
    ),
    Setting(
        key="role_separation",
        label="Administrator and AO role separation",
        scope="global",
        group="Account controls",
        help="Whether one account may hold both the system administrator and AO roles.",
        options=[
            Option("separate", "Separate: no account holds both", 2,
                   "Lowest risk. The person configuring models cannot approve them."),
            Option("combined", "May combine (small or standalone sites)", 1,
                   "Higher risk. One person can configure and approve model endpoints and "
                   "policy changes."),
        ],
        default="separate",
    ),
]

_BY_KEY = {s.key: s for s in CATALOG}


class PolicyError(ValueError):
    pass


def setting(key: str) -> Setting:
    return _BY_KEY[key]


def defaults() -> Dict[str, object]:
    return {s.key: (dict(s.default) if isinstance(s.default, dict) else s.default)
            for s in CATALOG}


def validate(settings: Dict[str, object]) -> Dict[str, object]:
    """Return a normalized copy, or raise PolicyError. Every key and every
    level must be present: there is no silent fallback to a default."""
    if not isinstance(settings, dict):
        raise PolicyError("settings must be an object")
    unknown = set(settings) - set(_BY_KEY)
    if unknown:
        raise PolicyError("unknown settings: {}".format(", ".join(sorted(unknown))))
    out: Dict[str, object] = {}
    for s in CATALOG:
        if s.key not in settings:
            raise PolicyError("missing setting {!r}".format(s.key))
        val = settings[s.key]
        if s.scope == "per_level":
            if not isinstance(val, dict) or set(val) != set(LEVELS):
                raise PolicyError("{} must set a value for every level {}".format(s.key, LEVELS))
            for lv, v in val.items():
                if s.option(str(v)) is None:
                    raise PolicyError("{}[{}]: invalid option {!r}".format(s.key, lv, v))
            out[s.key] = {lv: str(val[lv]) for lv in LEVELS}
        else:
            if s.option(str(val)) is None:
                raise PolicyError("{}: invalid option {!r}".format(s.key, val))
            out[s.key] = str(val)
    return out


def relaxations(old: Dict[str, object], new: Dict[str, object]) -> List[str]:
    """Settings (key or key[level]) whose new option is less strict."""
    found: List[str] = []
    for s in CATALOG:
        if s.scope == "per_level":
            for lv in LEVELS:
                if s.option(new[s.key][lv]).strictness < s.option(old[s.key][lv]).strictness:
                    found.append("{}[{}]".format(s.key, lv))
        elif s.option(new[s.key]).strictness < s.option(old[s.key]).strictness:
            found.append(s.key)
    return found


def level_rank(level: str) -> int:
    return _RANK[level]


def catalog_json() -> List[dict]:
    return [dict(asdict(s), levels=LEVELS if s.scope == "per_level" else None) for s in CATALOG]

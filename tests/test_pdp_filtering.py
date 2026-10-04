"""Phase 4 unit tests: PDP decisions against a clearance/control/compartment
matrix, and the consistency property that build_filter is exactly as
permissive as the point-decision.
"""

import itertools

import pytest

from backend.models.marking import ClassificationLevel, MarkingError
from backend.retrieval.pdp import (
    Decision,
    UserAttributes,
    build_filter,
    control_permitted,
    decide,
)


def user(clearance="S", citizenship="USA", compartments=(), ntk=(), user_id="u1"):
    return UserAttributes(
        user_id=user_id,
        clearance=clearance,
        citizenship=citizenship,
        compartments=list(compartments),
        need_to_know_groups=list(ntk),
    )


class TestUserAttributes:
    def test_valid_construction_normalizes(self):
        u = user(clearance="ts", citizenship=" usa ")
        assert u.clearance is ClassificationLevel.TS
        assert u.citizenship == "USA"

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"user_id": "  "},
            {"clearance": "SECRET"},
            {"citizenship": "US"},        # not a trigraph
            {"citizenship": ""},
            {"compartments": ["ALPHA", " "]},
            {"ntk": [""]},
        ],
    )
    def test_invalid_attributes_rejected(self, kwargs):
        with pytest.raises(MarkingError):
            user(**kwargs)

    def test_decision_requires_reason(self):
        with pytest.raises(ValueError):
            Decision(allow=True, reason="  ")


class TestClearanceMatrix:
    LEVELS = ["U", "C", "S", "TS", "TS/SCI"]

    @pytest.mark.parametrize(
        "user_level,chunk_level", list(itertools.product(LEVELS, LEVELS))
    )
    def test_dominance(self, user_level, chunk_level):
        d = decide(user(clearance=user_level), chunk_level, [], None)
        expected = self.LEVELS.index(user_level) >= self.LEVELS.index(chunk_level)
        assert d.allow is expected
        assert d.reason  # every decision carries a reason

    def test_unparseable_level_denied(self):
        d = decide(user(clearance="TS"), "BANANA", [], None)
        assert not d.allow
        assert "unparseable" in d.reason


class TestControls:
    def test_noforn_matrix(self):
        assert control_permitted(user(citizenship="USA"), "NOFORN").allow
        d = control_permitted(user(citizenship="GBR"), "NOFORN")
        assert not d.allow
        assert "non-US" in d.reason

    def test_rel_to_matrix(self):
        rel = "REL TO USA, GBR"
        assert control_permitted(user(citizenship="USA"), rel).allow
        assert control_permitted(user(citizenship="GBR"), rel).allow
        d = control_permitted(user(citizenship="FRA"), rel)
        assert not d.allow
        assert "FRA" in d.reason

    def test_orcon_requires_ntk_group(self):
        assert not control_permitted(user(), "ORCON").allow
        assert control_permitted(user(ntk=["ORCON"]), "ORCON").allow

    @pytest.mark.parametrize("caveat", ["PROPIN", "RELIDO", "NOCON"])
    def test_ntk_gated_caveats(self, caveat):
        assert not control_permitted(user(), caveat).allow
        assert control_permitted(user(ntk=[caveat]), caveat).allow
        # A grant for one caveat does not satisfy another.
        assert not control_permitted(user(ntk=["ORCON"]), caveat).allow

    def test_unknown_control_denied_by_default(self):
        d = control_permitted(user(clearance="TS", ntk=["ORCON"]), "MYSTERY")
        assert not d.allow
        assert "unknown" in d.reason

    def test_one_unsatisfied_control_denies_chunk(self):
        d = decide(user(citizenship="GBR", clearance="TS"), "S", ["ORCON", "NOFORN"], None)
        assert not d.allow

    def test_missing_control_list_denied(self):
        assert not decide(user(clearance="TS"), "S", None, None).allow


class TestCompartments:
    def test_program_requires_compartment(self):
        assert not decide(user(clearance="TS"), "S", [], "ALPHA").allow
        assert decide(user(clearance="TS", compartments=["ALPHA"]), "S", [], "ALPHA").allow

    def test_compartment_does_not_bypass_clearance(self):
        assert not decide(user(clearance="C", compartments=["ALPHA"]), "S", [], "ALPHA").allow


class TestFilterConsistency:
    """build_filter must be exactly as permissive as decide: for every
    user x chunk-marking combination, filter.matches == decide().allow."""

    USERS = [
        user(clearance="U", citizenship="USA", user_id="intern"),
        user(clearance="S", citizenship="GBR", user_id="uk_analyst"),
        user(clearance="TS", citizenship="USA", user_id="us_analyst"),
        user(clearance="TS", citizenship="USA", compartments=["ALPHA"], ntk=["ORCON"], user_id="sap_cleared"),
        user(clearance="S", citizenship="FRA", user_id="fr_liaison"),
        user(clearance="TS/SCI", citizenship="USA", ntk=["PROPIN", "RELIDO"], user_id="sci_analyst"),
    ]
    CHUNK_MARKINGS = [
        ("U", [], None),
        ("C", [], None),
        ("S", [], None),
        ("S", ["NOFORN"], None),
        ("S", ["ORCON"], None),
        ("S", ["NOFORN", "ORCON"], None),
        ("S", ["PROPIN"], None),
        ("S", ["RELIDO"], None),
        ("S", ["NOCON"], None),
        ("S", ["REL TO USA, GBR"], None),
        ("TS", ["REL TO USA, GBR"], None),
        ("TS/SCI", [], None),
        ("TS/SCI", ["NOFORN"], None),
        ("S", [], "ALPHA"),
        ("TS", ["NOFORN"], "ALPHA"),
        ("TS", ["NOFORN"], "BRAVO"),
    ]
    OBSERVED = ["NOFORN", "ORCON", "PROPIN", "RELIDO", "NOCON", "REL TO USA, GBR"]

    @pytest.mark.parametrize("u", USERS, ids=lambda u: u.user_id)
    def test_filter_matches_iff_pdp_allows(self, u):
        flt = build_filter(u, self.OBSERVED)
        for classification, controls, program in self.CHUNK_MARKINGS:
            via_filter = flt.matches(classification, controls, program)
            via_pdp = decide(u, classification, controls, program).allow
            assert via_filter == via_pdp, (
                "filter/PDP divergence for user {} on ({}, {}, {}): "
                "filter={} pdp={}".format(
                    u.user_id, classification, controls, program, via_filter, via_pdp
                )
            )

    def test_filter_permits_only_pdp_allowed_controls(self):
        flt = build_filter(self.USERS[1], self.OBSERVED)  # S / GBR
        assert flt.permitted_controls == ["REL TO USA, GBR"]
        assert [lv.value for lv in flt.allowed_levels] == ["U", "C", "S"]
        assert flt.allowed_programs == []

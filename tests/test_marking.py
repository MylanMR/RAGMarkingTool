"""Unit tests for the marking domain model: parsing, validation, no defaults."""

import pytest

from backend.models.marking import (
    ClassificationLevel,
    MarkingError,
    PortionMarking,
    SectionMarking,
    highest_level,
    validate_dissem_controls,
)


class TestClassificationLevel:
    def test_parse_valid_levels(self):
        assert ClassificationLevel.parse("U") is ClassificationLevel.U
        assert ClassificationLevel.parse("c") is ClassificationLevel.C
        assert ClassificationLevel.parse(" S ") is ClassificationLevel.S
        assert ClassificationLevel.parse("TS") is ClassificationLevel.TS
        assert ClassificationLevel.parse("ts/sci") is ClassificationLevel.TS_SCI

    @pytest.mark.parametrize("bad", [None, "", "  ", "X", "SECRET", "TS//NF", 3])
    def test_parse_rejects_missing_or_unknown(self, bad):
        with pytest.raises(MarkingError):
            ClassificationLevel.parse(bad)

    def test_ordering(self):
        assert ClassificationLevel.TS.dominates(ClassificationLevel.S)
        assert ClassificationLevel.S.dominates(ClassificationLevel.S)
        assert not ClassificationLevel.C.dominates(ClassificationLevel.S)
        assert ClassificationLevel.TS_SCI.dominates(ClassificationLevel.TS)
        assert not ClassificationLevel.TS.dominates(ClassificationLevel.TS_SCI)

    def test_highest_level(self):
        levels = [ClassificationLevel.U, ClassificationLevel.TS, ClassificationLevel.C]
        assert highest_level(levels) is ClassificationLevel.TS
        with pytest.raises(MarkingError):
            highest_level([])


class TestPortionMarking:
    def test_plain_levels(self):
        pm = PortionMarking.parse("(U)")
        assert pm.classification is ClassificationLevel.U
        assert pm.dissem_controls == []

    def test_with_noforn(self):
        pm = PortionMarking.parse("(S//NF)")
        assert pm.classification is ClassificationLevel.S
        assert pm.dissem_controls == ["NOFORN"]
        assert str(pm) == "(S//NOFORN)"

    def test_with_rel_to(self):
        pm = PortionMarking.parse("(TS//REL TO USA, GBR)")
        assert pm.classification is ClassificationLevel.TS
        assert pm.dissem_controls == ["REL TO USA, GBR"]

    def test_multiple_controls(self):
        pm = PortionMarking.parse("(S//NF/OC)")
        assert pm.dissem_controls == ["NOFORN", "ORCON"]

    def test_ts_sci_level(self):
        pm = PortionMarking.parse("(TS/SCI//NF)")
        assert pm.classification is ClassificationLevel.TS_SCI
        assert pm.dissem_controls == ["NOFORN"]
        assert str(PortionMarking.parse("(TS/SCI)")) == "(TS/SCI)"

    @pytest.mark.parametrize("caveat", ["PROPIN", "RELIDO", "NOCON"])
    def test_ic_caveats(self, caveat):
        pm = PortionMarking.parse("(S//{})".format(caveat))
        assert pm.dissem_controls == [caveat]

    @pytest.mark.parametrize(
        "bad",
        [
            None,
            "",
            "   ",
            "S//NF",          # missing parens
            "(X//NF)",        # unknown level
            "(S//)",          # empty control
            "(S//NF/)",       # trailing empty control
            "(S//BANANA)",    # unknown control
            "(U//NF)",        # U cannot carry controls
            "(S//NF/REL TO USA)",  # NOFORN conflicts with REL TO
        ],
    )
    def test_rejects_bad_markings(self, bad):
        with pytest.raises(MarkingError):
            PortionMarking.parse(bad)

    def test_no_default_construction_path(self):
        # There is no way to get a PortionMarking without an explicit level.
        with pytest.raises(TypeError):
            PortionMarking()  # type: ignore[call-arg]


class TestDissemControls:
    def test_normalization_and_dedup(self):
        assert validate_dissem_controls(["NF", "NOFORN", "oc"]) == ["NOFORN", "ORCON"]

    def test_rel_and_noforn_conflict(self):
        with pytest.raises(MarkingError):
            validate_dissem_controls(["REL TO USA, GBR", "NOFORN"])

    def test_multiple_rel_to_rejected(self):
        with pytest.raises(MarkingError):
            validate_dissem_controls(["REL TO USA", "REL TO GBR"])


class TestSectionMarking:
    def test_from_raw(self):
        m = SectionMarking.from_raw("(S//NF)", program="ALPHA")
        assert m.classification is ClassificationLevel.S
        assert m.dissem_controls == ["NOFORN"]
        assert m.program == "ALPHA"

    def test_missing_marking_rejected(self):
        with pytest.raises(MarkingError):
            SectionMarking.from_raw(None)
        with pytest.raises(MarkingError):
            SectionMarking.from_raw("")

    def test_blank_program_rejected(self):
        with pytest.raises(MarkingError):
            SectionMarking.from_raw("(S)", program="   ")

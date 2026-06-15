"""Tests for EPO Formalities Checker (Rules 42-49 EPC)."""

from mcp_server.epo_formalities_checker import EPOFormalitiesChecker


class TestAbstract:
    """Rule 47 EPC: abstract requirements."""

    def test_short_abstract_flagged(self, sample_short_abstract):
        checker = EPOFormalitiesChecker()
        result = checker.check_all_formalities(abstract=sample_short_abstract)
        issues = [i for i in result["issues"] if i["section"] == "abstract"]
        assert len(issues) > 0

    def test_abstract_cites_rule_47(self, sample_short_abstract):
        checker = EPOFormalitiesChecker()
        result = checker.check_all_formalities(abstract=sample_short_abstract)
        issues = [i for i in result["issues"] if i["section"] == "abstract"]
        assert any("Rule 47" in i["legal_ref"] for i in issues)

    def test_good_abstract_with_ref_signs(self, sample_good_abstract):
        checker = EPOFormalitiesChecker()
        result = checker.check_all_formalities(abstract=sample_good_abstract)
        ref_sign_issues = [i for i in result["issues"] if "reference sign" in i.get("problem", "").lower()]
        assert len(ref_sign_issues) == 0

    def test_no_means_said_prohibition(self):
        """EPO does NOT prohibit 'means/said/whereby' in abstracts (unlike USPTO)."""
        checker = EPOFormalitiesChecker()
        abstract = (
            "A means for processing data includes a said processor "
            "whereby computation is performed on input signals. "
            "The processing means employs parallel units for improved "
            "throughput across multiple data channels for real-time analysis."
        )
        result = checker.check_all_formalities(abstract=abstract)
        forbidden_issues = [
            i for i in result["issues"]
            if "forbidden" in i.get("problem", "").lower()
            and any(w in i.get("problem", "").lower() for w in ["means", "said", "whereby"])
        ]
        assert len(forbidden_issues) == 0


class TestOutputFormat:
    def test_uses_legal_ref_key(self, sample_short_abstract):
        checker = EPOFormalitiesChecker()
        result = checker.check_all_formalities(abstract=sample_short_abstract)
        for issue in result["issues"]:
            assert "legal_ref" in issue

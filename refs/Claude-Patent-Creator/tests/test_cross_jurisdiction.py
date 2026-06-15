"""Tests verifying US vs EPO analyzer output compatibility."""

from mcp_server.claims_analyzer import ClaimsAnalyzer
from mcp_server.epo_claims_analyzer import EPOClaimsAnalyzer


class TestCrossJurisdiction:
    """Verify US and EPO analyzers produce correctly-keyed output on the same input."""

    SHARED_CLAIMS = "1. A method comprising processing data in an appropriate manner."

    def test_us_outputs_mpep_key(self):
        analyzer = ClaimsAnalyzer()
        result = analyzer.analyze(self.SHARED_CLAIMS)
        assert all("mpep" in i for i in result["issues"])

    def test_epo_outputs_legal_ref_key(self):
        analyzer = EPOClaimsAnalyzer()
        result = analyzer.analyze(self.SHARED_CLAIMS)
        assert all("legal_ref" in i for i in result["issues"])

    def test_us_refs_contain_mpep(self):
        analyzer = ClaimsAnalyzer()
        result = analyzer.analyze(self.SHARED_CLAIMS)
        assert all("MPEP" in i["mpep"] for i in result["issues"] if i.get("mpep"))

    def test_epo_refs_contain_epc(self):
        analyzer = EPOClaimsAnalyzer()
        result = analyzer.analyze(self.SHARED_CLAIMS)
        for i in result["issues"]:
            ref = i.get("legal_ref", "")
            assert "EPC" in ref or "Rule" in ref, f"Expected EPC ref, got: {ref}"

    def test_both_detect_same_subjective_term(self):
        analyzer_us = ClaimsAnalyzer()
        analyzer_epo = EPOClaimsAnalyzer()
        us_result = analyzer_us.analyze(self.SHARED_CLAIMS)
        epo_result = analyzer_epo.analyze(self.SHARED_CLAIMS)
        us_terms = {i.get("term") for i in us_result["issues"] if i.get("term")}
        epo_terms = {i.get("term") for i in epo_result["issues"] if i.get("term")}
        # Both should flag "appropriate"
        assert "appropriate" in us_terms
        assert "appropriate" in epo_terms


class TestBackwardCompatProperty:
    """Verify BaseIssue.mpep_ref property works as alias for legal_ref."""

    def test_mpep_ref_property(self):
        from mcp_server.analyzer_base import BaseIssue

        issue = BaseIssue(severity="CRITICAL", problem="test", fix="fix", legal_ref="Art. 84 EPC")
        assert issue.legal_ref == "Art. 84 EPC"
        assert issue.mpep_ref == "Art. 84 EPC"

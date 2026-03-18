from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = PROJECT_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from rulesgen.source import parse_conf_line  # noqa: E402
from rulesgen.targets import to_sing_box_rule, to_sing_box_rules  # noqa: E402


class SingBoxMappingTests(unittest.TestCase):
    def _parse(self, line: str):
        rule, warning = parse_conf_line(line)
        self.assertIsNone(warning)
        self.assertIsNotNone(rule)
        assert rule is not None
        return rule

    def test_nested_logical_rule_maps_to_logical_tree(self) -> None:
        line = "AND,((NOT,((DOMAIN,ads.example.com))),(OR,((DOMAIN-SUFFIX,example.com),(DST-PORT,443))))"
        rule = self._parse(line)

        mapped, warning = to_sing_box_rule(rule)
        self.assertIsNone(warning)
        self.assertIsNotNone(mapped)
        assert mapped is not None

        self.assertEqual(mapped.get("type"), "logical")
        self.assertEqual(mapped.get("mode"), "and")
        children = mapped.get("rules")
        self.assertIsInstance(children, list)
        self.assertEqual(len(children), 2)

        not_branch = children[0]
        self.assertEqual(not_branch.get("domain"), ["ads.example.com"])
        self.assertTrue(not_branch.get("invert"))

        or_branch = children[1]
        self.assertEqual(or_branch.get("type"), "logical")
        self.assertEqual(or_branch.get("mode"), "or")
        self.assertEqual(len(or_branch.get("rules", [])), 2)

    def test_not_on_logical_rule_toggles_invert(self) -> None:
        line = "NOT,((OR,((DOMAIN,a.com),(DOMAIN,b.com))))"
        rule = self._parse(line)

        mapped, warning = to_sing_box_rule(rule)
        self.assertIsNone(warning)
        self.assertIsNotNone(mapped)
        assert mapped is not None

        self.assertEqual(mapped.get("type"), "logical")
        self.assertEqual(mapped.get("mode"), "or")
        self.assertTrue(mapped.get("invert"))

    def test_geoip_is_mapped_and_ip_asn_warns(self) -> None:
        geoip = self._parse("GEOIP,CN")
        mapped_geoip, warning_geoip = to_sing_box_rule(geoip)
        self.assertIsNone(warning_geoip)
        self.assertEqual(mapped_geoip, {"geoip": ["cn"]})

        ip_asn = self._parse("IP-ASN,13335")
        mapped_ip_asn, warning_ip_asn = to_sing_box_rule(ip_asn)
        self.assertIsNone(mapped_ip_asn)
        self.assertIn("IP-ASN", warning_ip_asn or "")

    def test_to_sing_box_rules_preserves_input_order(self) -> None:
        rules = [
            self._parse("DOMAIN,a.com"),
            self._parse("DST-PORT,443"),
            self._parse("DOMAIN,b.com"),
        ]

        payload, warnings = to_sing_box_rules(rules)
        self.assertEqual(warnings, [])

        rendered = payload["rules"]
        self.assertEqual(rendered[0], {"domain": ["a.com"]})
        self.assertEqual(rendered[1], {"port": [443]})
        self.assertEqual(rendered[2], {"domain": ["b.com"]})


if __name__ == "__main__":
    unittest.main()

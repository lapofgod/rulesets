from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from rulesgen.source import parse_conf_line  # noqa: E402
from rulesgen.targets import (  # noqa: E402
    LoonTargetEmitter,
    MihomoTargetEmitter,
    ShadowrocketTargetEmitter,
    SurgeTargetEmitter,
)


class LogicalDstPortPlatformMappingTests(unittest.TestCase):
    def _parse_logical_rule(self):
        line = "AND,((DOMAIN,example.com),(OR,((DST-PORT,443),(DST-PORT,8443))))"
        rule, warning = parse_conf_line(line)
        self.assertIsNone(warning)
        self.assertIsNotNone(rule)
        assert rule is not None
        return rule

    def test_nested_dst_port_mapping_differs_by_platform(self) -> None:
        rule = self._parse_logical_rule()

        surge_rule = SurgeTargetEmitter().map_rule(rule)
        loon_rule = LoonTargetEmitter().map_rule(rule)
        shadowrocket_rule = ShadowrocketTargetEmitter().map_rule(rule)
        mihomo_rule = MihomoTargetEmitter().map_rule(rule)

        self.assertIsNotNone(surge_rule)
        self.assertIsNotNone(loon_rule)
        self.assertIsNotNone(shadowrocket_rule)
        self.assertIsNotNone(mihomo_rule)

        assert surge_rule is not None
        assert loon_rule is not None
        assert shadowrocket_rule is not None
        assert mihomo_rule is not None

        self.assertEqual(
            surge_rule.as_line,
            "AND,((DOMAIN,example.com),(OR,((DEST-PORT,443),(DEST-PORT,8443))))",
        )
        self.assertEqual(
            loon_rule.as_line,
            "AND,((DOMAIN,example.com),(OR,((DEST-PORT,443),(DEST-PORT,8443))))",
        )
        self.assertEqual(
            shadowrocket_rule.as_line,
            "AND,((DOMAIN,example.com),(OR,((DST-PORT,443),(DST-PORT,8443))))",
        )
        self.assertEqual(
            mihomo_rule.as_line,
            "AND,((DOMAIN,example.com),(OR,((DST-PORT,443),(DST-PORT,8443))))",
        )


if __name__ == "__main__":
    unittest.main()

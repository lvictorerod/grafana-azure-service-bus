"""Regression tests for validate_dashboard.py.  Run:  python3 -m unittest discover -s validator -v"""
import copy
import json
import re
import unittest
from pathlib import Path

import validate_dashboard as v

ROOT = Path(__file__).resolve().parent.parent
MODERN = ROOT / "dashboard" / "azure-service-bus.json"
ORIGINAL = ROOT / "original" / "azure-service-bus-10533.original.json"
CATALOG = Path(__file__).with_name("servicebus_metrics_catalog.json")
ALERTS = ROOT / "alerting" / "azure-service-bus-alerts.json"


def codes(report, level="ERROR"):
    return {f.code for f in report.findings if f.level == level}


class ValidatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.modern = json.loads(MODERN.read_text(encoding="utf-8"))
        cls.catalog = json.loads(CATALOG.read_text(encoding="utf-8"))

    def validate(self, dash):
        return v.validate(dash, self.catalog)

    def first_target(self, dash, metric):
        for p in v.iter_panels(dash["panels"]):
            for t in p.get("targets", []):
                if t["azureMonitor"]["metricName"] == metric:
                    return p, t
        raise AssertionError(metric)

    # --- baseline -----------------------------------------------------------
    def test_modern_dashboard_has_no_errors_or_warnings(self):
        r = v.run(MODERN, CATALOG)
        self.assertEqual([], [f for f in r.findings if f.level in ("ERROR", "WARN")])

    def test_original_dashboard_is_flagged(self):
        c = codes(v.run(ORIGINAL, CATALOG))
        for expected in ("PANEL_DEPRECATED", "DS_LEGACY_STRING", "COMPAT_SCHEMA_OLD", "HARDCODED_GUID",
                         "SEMANTIC_UNSPLIT_GAUGE", "SEMANTIC_COUNTER_LAST"):
            self.assertIn(expected, c)

    def test_modern_panel_ids_unique_and_ids_preserved_as_ints(self):
        ids = [p["id"] for p in v.iter_panels(self.modern["panels"])]
        self.assertEqual(len(ids), len(set(ids)))

    # --- injected regressions ---------------------------------------------
    def test_duplicate_panel_id(self):
        d = copy.deepcopy(self.modern)
        d["panels"][2]["id"] = d["panels"][1]["id"]
        self.assertIn("PANEL_DUP_ID", codes(self.validate(d)))

    def test_hardcoded_datasource_uid(self):
        d = copy.deepcopy(self.modern)
        d["panels"][1]["datasource"] = {"type": "grafana-azure-monitor-datasource", "uid": "P1234ABCD"}
        self.assertIn("DS_HARDCODED_UID", codes(self.validate(d)))

    def test_hardcoded_resource_group(self):
        d = copy.deepcopy(self.modern)
        _, t = self.first_target(d, "IncomingMessages")
        t["azureMonitor"]["resources"][0]["resourceGroup"] = "rg-prod-weu"
        self.assertIn("HARDCODED_RESOURCE", codes(self.validate(d)))

    def test_undeclared_variable(self):
        d = copy.deepcopy(self.modern)
        _, t = self.first_target(d, "IncomingMessages")
        t["azureMonitor"]["resources"][0]["resourceName"] = "$sbNamespace"
        self.assertIn("VAR_UNDECLARED", codes(self.validate(d)))

    def test_unknown_metric(self):
        d = copy.deepcopy(self.modern)
        _, t = self.first_target(d, "IncomingMessages")
        t["azureMonitor"]["metricName"] = "IncomingMessageRate"
        self.assertIn("METRIC_UNKNOWN", codes(self.validate(d)))

    def test_deprecated_metric(self):
        d = copy.deepcopy(self.modern)
        for p in v.iter_panels(d["panels"]):
            for t in p.get("targets", []):
                if t["azureMonitor"]["metricName"] == "NamespaceCpuUsage":
                    t["azureMonitor"]["metricName"] = "CPUXNS"
        self.assertIn("METRIC_DEPRECATED", codes(self.validate(d)))

    def test_counter_with_unsupported_aggregation(self):
        d = copy.deepcopy(self.modern)
        _, t = self.first_target(d, "IncomingMessages")
        t["azureMonitor"]["aggregation"] = "Average"
        self.assertIn("AGG_UNSUPPORTED", codes(self.validate(d)))

    def test_gauge_with_total(self):
        d = copy.deepcopy(self.modern)
        _, t = self.first_target(d, "ActiveMessages")
        t["azureMonitor"]["aggregation"] = "Total"
        self.assertIn("AGG_UNSUPPORTED", codes(self.validate(d)))

    def test_active_connections_with_auto_grain(self):
        d = copy.deepcopy(self.modern)
        _, t = self.first_target(d, "ActiveConnections")
        t["azureMonitor"]["timeGrain"] = "auto"
        self.assertIn("SEMANTIC_GAUGE_GRAIN", codes(self.validate(d)))

    def test_unsplit_entity_gauge_in_stat(self):
        d = copy.deepcopy(self.modern)
        _, t = self.first_target(d, "ActiveMessages")
        t["azureMonitor"]["dimensionFilters"] = []
        self.assertIn("SEMANTIC_UNSPLIT_GAUGE", codes(self.validate(d)))

    def test_unsupported_dimension(self):
        d = copy.deepcopy(self.modern)
        _, t = self.first_target(d, "ActiveMessages")
        t["azureMonitor"]["dimensionFilters"][0]["dimension"] = "OperationResult"
        self.assertIn("DIM_UNSUPPORTED", codes(self.validate(d)))

    def test_unit_mismatch(self):
        d = copy.deepcopy(self.modern)
        p, _ = self.first_target(d, "Size")
        p["fieldConfig"]["defaults"]["unit"] = "percent"
        self.assertIn("UNIT_MISMATCH", codes(self.validate(d)))

    def test_deprecated_panel_type(self):
        d = copy.deepcopy(self.modern)
        d["panels"][1]["type"] = "singlestat"
        self.assertIn("PANEL_DEPRECATED", codes(self.validate(d)))

    def test_plugin_panel_not_allowed(self):
        d = copy.deepcopy(self.modern)
        d["panels"][1]["type"] = "volkovlabs-form-panel"
        self.assertIn("PANEL_NOT_ALLOWED", codes(self.validate(d)))

    def test_panel_actions_rejected(self):
        d = copy.deepcopy(self.modern)
        d["panels"][1]["options"]["actions"] = [{"title": "Purge DLQ", "fetch": {"method": "POST", "url": "https://x"}}]
        self.assertIn("RO_PANEL_ACTION", codes(self.validate(d)))

    def test_write_link_rejected(self):
        d = copy.deepcopy(self.modern)
        d["links"].append({"title": "Purge", "type": "link",
                           "url": "https://example.invalid/api/deadletter/purge"})
        self.assertIn("RO_WRITE_LINK", codes(self.validate(d)))

    def test_variable_order(self):
        d = copy.deepcopy(self.modern)
        lst = d["templating"]["list"]
        lst[1], lst[3] = lst[3], lst[1]
        self.assertIn("VAR_ORDER", codes(self.validate(d)))

    def test_schema_too_old(self):
        d = copy.deepcopy(self.modern)
        d["schemaVersion"] = 27
        self.assertIn("COMPAT_SCHEMA_OLD", codes(self.validate(d)))

    def test_row_sum_then_last_rejected(self):
        d = copy.deepcopy(self.modern)
        p, _ = self.first_target(d, "ActiveMessages")
        p["transformations"] = [{"id": "joinByField", "options": {"byField": "Time", "mode": "outer"}},
                                {"id": "calculateField", "options": {"mode": "reduceRow", "reduce": {"reducer": "sum"}}}]
        p["options"]["reduceOptions"]["calcs"] = ["lastNotNull"]
        self.assertIn("SEMANTIC_ROWSUM_LAST", codes(self.validate(d)))

    def test_non_numeric_requires_version(self):
        d = copy.deepcopy(self.modern)
        d["__requires"][0]["version"] = "10.x"
        self.assertNotIn("COMPAT_REQUIRES", codes(self.validate(d), "WARN"))

    def test_unknown_transformation(self):
        d = copy.deepcopy(self.modern)
        p, _ = self.first_target(d, "ActiveMessages")
        p["transformations"].append({"id": "seriesToColumns", "options": {}})
        self.assertIn("COMPAT_TRANSFORM", codes(self.validate(d)))



class AlertRuleTests(unittest.TestCase):
    """The alert file is not a dashboard, so it gets its own catalog checks."""

    def test_alert_queries_match_catalog_and_use_env_placeholders(self):
        rules = json.loads(ALERTS.read_text(encoding="utf-8"))
        metrics = json.loads(CATALOG.read_text(encoding="utf-8"))["metrics"]
        panel_ids = {p["id"] for p in v.iter_panels(json.loads(MODERN.read_text(encoding="utf-8"))["panels"])}
        env = re.compile(r"\$\{[A-Z_]+\}")
        for group in rules["groups"]:
            for rule in group["rules"]:
                self.assertIn(int(rule["annotations"]["__panelId__"]), panel_ids, rule["uid"])
                # Grafana expands $VAR in provisioning files: only ${ENV} placeholders may contain '$'.
                self.assertNotIn("$", env.sub("", json.dumps(rule)), rule["uid"])
                for q in rule["data"]:
                    if q["datasourceUid"] == "__expr__":
                        continue
                    am = q["model"]["azureMonitor"]
                    m = metrics[am["metricName"]]
                    self.assertIn(am["aggregation"], m["aggregations"], rule["uid"])
                    self.assertEqual("PT1M", am["timeGrain"], rule["uid"])
                    for f in am.get("dimensionFilters", []):
                        self.assertIn(f["dimension"], m["dimensions"], rule["uid"])
                    for value in am["resources"][0].values():
                        if value != "microsoft.servicebus/namespaces":
                            self.assertRegex(value, env, rule["uid"])


if __name__ == "__main__":
    unittest.main()

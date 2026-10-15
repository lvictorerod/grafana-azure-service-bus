#!/usr/bin/env python3
"""Static validator for the Azure Service Bus Grafana dashboard.

Runs entirely offline (no Grafana instance, no Azure access). It checks structure,
portability, query semantics against the Service Bus metrics catalog, units,
read-only interactions and compatibility with the target Grafana range.

Usage:
    python3 validate_dashboard.py <dashboard.json> [--catalog PATH] [--json]

Exit code: 0 = no errors (warnings allowed), 1 = errors found, 2 = file unreadable / invalid JSON.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Target compatibility profile (see docs/COMPATIBILITY.md)
# ---------------------------------------------------------------------------
TARGET_MIN_SCHEMA = 39          # Grafana 10.4 / 11.x export schemaVersion
TARGET_MAX_SCHEMA = 42          # Grafana 13.x DASHBOARD_SCHEMA_VERSION
AZURE_DS_TYPE = "grafana-azure-monitor-datasource"

DEPRECATED_PANEL_TYPES = {
    "graph": "timeseries", "singlestat": "stat", "table-old": "table",
    "grafana-piechart-panel": "piechart", "grafana-worldmap-panel": "geomap",
    "grafana-singlestat-panel": "stat",
}
# Native, read-only visualisations allowed in this dashboard.
ALLOWED_PANEL_TYPES = {"row", "stat", "timeseries", "bargauge", "gauge", "table", "barchart",
                       "text", "piechart", "state-timeline", "status-history", "heatmap"}
# Variable query types available in released Grafana 10.4 .. 13.x (verified in source).
ALLOWED_VARIABLE_QUERY_TYPES = {"Azure Subscriptions", "Azure Resource Groups", "Azure Namespaces",
                                "Azure Resource Names", "Azure Metric Names", "Azure Workspaces",
                                "Azure Regions", "Azure Custom Namespaces", "Azure Custom Metric Names"}
ALLOWED_TRANSFORMATIONS = {"joinByField", "calculateField", "reduce", "organize", "merge",
                           "filterFieldsByName", "renameByRegex", "sortBy", "seriesToRows", "labelsToFields"}
LEGACY_AZURE_FIELDS = {"metricDefinition", "timeGrainUnit", "dimension", "dimensionFilter", "resourceGroup",
                       "resourceName", "aggOptions", "dimensions", "timeGrains"}
BUILTIN_VARS = {"__interval", "__interval_ms", "__range", "__range_s", "__range_ms", "__rate_interval",
                "__from", "__to", "__dashboard", "__user", "__org", "__name", "__series", "__field",
                "__value", "__data", "__cell", "__timeFilter", "timeFilter", "__all_variables",
                "__url_time_range", "__timezone"}
WRITE_KEYWORDS = re.compile(
    r"\b(delete|purge|resubmit|send(message)?|receive|peek-?lock|complete|abandon|deadletter/.*(move|resend)|"
    r"update|patch|put|post|regenerate(keys)?|listkeys)\b", re.I)
GUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
VAR_REF = re.compile(r"\$\{([A-Za-z0-9_]+)(?::[^}]*)?\}|\$([A-Za-z_][A-Za-z0-9_]*)|\[\[([A-Za-z0-9_]+)\]\]")


@dataclass
class Finding:
    level: str      # ERROR | WARN | INFO
    code: str
    where: str
    message: str


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)

    def add(self, level, code, where, message):
        self.findings.append(Finding(level, code, where, message))

    def count(self, level):
        return sum(1 for f in self.findings if f.level == level)


def iter_panels(panels):
    for p in panels or []:
        yield p
        if p.get("type") == "row":
            yield from iter_panels(p.get("panels"))


def walk_strings(obj, path="$"):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from walk_strings(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk_strings(v, f"{path}[{i}]")
    elif isinstance(obj, str):
        yield path, obj


def is_var(value) -> bool:
    return isinstance(value, str) and value.strip().startswith(("$", "[["))


def ptitle(p):
    return f"panel {p.get('id')} '{p.get('title', '')}'"


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------
def check_structure(d, r):
    for key in ("title", "uid", "panels", "templating", "schemaVersion"):
        if key not in d:
            r.add("ERROR", "STRUCT_MISSING_KEY", "$", f"missing top-level key '{key}'")
    ids = {}
    for p in iter_panels(d.get("panels")):
        pid = p.get("id")
        if pid is None:
            r.add("ERROR", "PANEL_NO_ID", ptitle(p), "panel without id")
        elif pid in ids:
            r.add("ERROR", "PANEL_DUP_ID", ptitle(p), f"duplicate panel id {pid} (also '{ids[pid]}')")
        else:
            ids[pid] = p.get("title")
        if p.get("type") != "row":
            refids = [t.get("refId") for t in p.get("targets", [])]
            if len(refids) != len(set(refids)):
                r.add("ERROR", "TARGET_DUP_REFID", ptitle(p), f"duplicate refIds {refids}")


def check_layout(d, r):
    occupied = {}
    for p in iter_panels(d.get("panels")):
        g = p.get("gridPos") or {}
        x, y, w, h = g.get("x", 0), g.get("y", 0), g.get("w", 0), g.get("h", 0)
        if x + w > 24:
            r.add("ERROR", "LAYOUT_OVERFLOW", ptitle(p), f"x+w = {x + w} > 24")
        if p.get("type") == "row":
            continue
        for cx in range(x, x + w):
            for cy in range(y, y + h):
                other = occupied.get((cx, cy))
                if other is not None and other != p.get("id"):
                    r.add("WARN", "LAYOUT_OVERLAP", ptitle(p), f"overlaps panel {other}")
                    break
                occupied[(cx, cy)] = p.get("id")
            else:
                continue
            break


def check_panel_types(d, r):
    for p in iter_panels(d.get("panels")):
        t = p.get("type")
        if t in DEPRECATED_PANEL_TYPES:
            r.add("ERROR", "PANEL_DEPRECATED", ptitle(p),
                  f"deprecated type '{t}' (use '{DEPRECATED_PANEL_TYPES[t]}')")
        elif t not in ALLOWED_PANEL_TYPES:
            r.add("ERROR", "PANEL_NOT_ALLOWED", ptitle(p),
                  f"type '{t}' is not a native read-only visualisation (plugin dependency / possible actions)")
        if t not in ("row",) and not p.get("title", "").strip():
            r.add("ERROR", "PANEL_NO_TITLE", ptitle(p), "panel without title")
        if t not in ("row", "text") and not p.get("description", "").strip():
            r.add("WARN", "PANEL_NO_DESCRIPTION", ptitle(p), "panel without description")


def check_datasources(d, r, declared_vars):
    def check_ref(ds, where):
        if ds is None:
            return
        if isinstance(ds, str):
            if ds in ("-- Grafana --", "-- Mixed --", "-- Dashboard --"):
                return
            r.add("ERROR", "DS_LEGACY_STRING", where,
                  f"datasource referenced by name string '{ds}' (use {{type, uid}} object)")
            m = VAR_REF.fullmatch(ds.strip())
            if m and (m.group(1) or m.group(2) or m.group(3)) not in declared_vars:
                r.add("ERROR", "DS_UNDECLARED_VAR", where, f"datasource variable '{ds}' not declared")
            return
        uid = ds.get("uid")
        if ds.get("type") == "grafana":
            return
        if uid is None:
            r.add("WARN", "DS_NO_UID", where, "datasource object without uid")
        elif not is_var(uid):
            r.add("ERROR", "DS_HARDCODED_UID", where, f"hardcoded datasource uid '{uid}' (use ${{datasource}})")
        else:
            name = re.sub(r"[${}\[\]]", "", uid).split(":")[0]
            if name not in declared_vars:
                r.add("ERROR", "DS_UNDECLARED_VAR", where, f"datasource variable '{uid}' not declared")
        if ds.get("type") not in (None, AZURE_DS_TYPE):
            r.add("WARN", "DS_UNEXPECTED_TYPE", where, f"datasource type '{ds.get('type')}'")

    for p in iter_panels(d.get("panels")):
        if p.get("type") == "row":
            continue
        check_ref(p.get("datasource"), ptitle(p))
        for t in p.get("targets", []):
            check_ref(t.get("datasource"), f"{ptitle(p)} target {t.get('refId')}")
    for v in d.get("templating", {}).get("list", []):
        if v.get("type") == "query":
            check_ref(v.get("datasource"), f"variable '{v.get('name')}'")


def check_variables(d, r):
    variables = d.get("templating", {}).get("list", [])
    declared = [v.get("name") for v in variables]
    declared_set = set(declared)
    for name in declared_set:
        if declared.count(name) > 1:
            r.add("ERROR", "VAR_DUPLICATE", f"variable '{name}'", "declared more than once")

    # Variables referenced anywhere (panels, links, variable queries).
    referenced = {}
    scan = {"panels": d.get("panels", []), "links": d.get("links", []), "templating": variables}
    for path, s in walk_strings(scan):
        for m in VAR_REF.finditer(s):
            name = m.group(1) or m.group(2) or m.group(3)
            referenced.setdefault(name, path)
    for name, path in referenced.items():
        if name not in declared_set and name not in BUILTIN_VARS:
            r.add("ERROR", "VAR_UNDECLARED", path, f"reference to undeclared variable '${name}'")
    for name in declared_set:
        if name not in referenced:
            r.add("WARN", "VAR_UNUSED", f"variable '{name}'", "declared but never referenced")

    # Dependency order: a variable must only reference variables declared before it.
    seen = set()
    for v in variables:
        for _, s in walk_strings({"q": v.get("query"), "ds": v.get("datasource")}):
            for m in VAR_REF.finditer(s):
                dep = m.group(1) or m.group(2) or m.group(3)
                if dep in declared_set and dep not in seen:
                    r.add("ERROR", "VAR_ORDER", f"variable '{v.get('name')}'",
                          f"depends on '${dep}' declared after it (cascade will not refresh correctly)")
        seen.add(v.get("name"))

        if v.get("type") == "query":
            q = v.get("query")
            if isinstance(q, str):
                r.add("WARN", "VAR_LEGACY_FUNCTION", f"variable '{v.get('name')}'",
                      f"legacy template-variable function '{q}' (migrated at runtime; prefer structured queryType)")
            elif isinstance(q, dict):
                qt = q.get("queryType")
                if qt not in ALLOWED_VARIABLE_QUERY_TYPES:
                    r.add("ERROR", "VAR_QUERYTYPE", f"variable '{v.get('name')}'",
                          f"queryType '{qt}' not available in the target Grafana range")
            if v.get("refresh") not in (1, 2):
                r.add("WARN", "VAR_REFRESH", f"variable '{v.get('name')}'",
                      "refresh should be 1 (on load) or 2 (on time range change)")
    return declared_set


def check_hardcoded_resources(d, r):
    for p in iter_panels(d.get("panels")):
        for t in p.get("targets", []):
            where = f"{ptitle(p)} target {t.get('refId')}"
            am = t.get("azureMonitor") or {}
            fields = {"subscription": t.get("subscription")}
            for i, res in enumerate(am.get("resources") or []):
                for k in ("subscription", "resourceGroup", "resourceName"):
                    fields[f"resources[{i}].{k}"] = res.get(k)
            for k in ("resourceGroup", "resourceName", "resourceUri"):
                fields[f"azureMonitor.{k}"] = am.get(k)
            for k, v in fields.items():
                if v not in (None, "") and not is_var(v):
                    r.add("ERROR", "HARDCODED_RESOURCE", where, f"{k} hardcoded to '{v}'")
            for path, s in walk_strings(t):
                if GUID.search(s) and not is_var(s):
                    r.add("ERROR", "HARDCODED_GUID", f"{where} {path}", "hardcoded GUID (subscription/workspace id)")


def check_queries(d, r, catalog):
    metrics = catalog["metrics"]
    ns = catalog["namespace"]
    unit_map = catalog["grafana_units_by_azure_unit"]
    for p in iter_panels(d.get("panels")):
        if p.get("type") == "row":
            continue
        panel_units = set()
        unit = (p.get("fieldConfig", {}).get("defaults", {}) or {}).get("unit") or p.get("format")
        if p.get("type") == "graph":
            unit = (p.get("yaxes") or [{}])[0].get("format")
        azure_units = set()
        for t in p.get("targets", []):
            where = f"{ptitle(p)} target {t.get('refId')}"
            if t.get("queryType") not in (None, "Azure Monitor"):
                r.add("WARN", "QUERY_TYPE", where, f"queryType '{t.get('queryType')}' not reviewed by this validator")
                continue
            am = t.get("azureMonitor") or {}
            legacy = sorted(k for k in LEGACY_AZURE_FIELDS if k in am)
            if legacy:
                r.add("WARN", "QUERY_LEGACY_MODEL", where, f"legacy Azure Monitor query fields {legacy}")
            for junk in ("appInsights", "azureLogAnalytics"):
                if junk in t and t.get("queryType") == "Azure Monitor":
                    r.add("WARN", "QUERY_LEFTOVER", where, f"unused '{junk}' block left in an Azure Monitor query")
            mns = (am.get("metricNamespace") or am.get("metricDefinition") or "").lower()
            if mns != ns:
                r.add("ERROR", "QUERY_NAMESPACE", where, f"metric namespace '{mns}' != '{ns}'")
            name = am.get("metricName")
            if name not in metrics:
                r.add("ERROR", "METRIC_UNKNOWN", where, f"metric '{name}' not in the Service Bus catalog")
                continue
            m = metrics[name]
            azure_units.add(m["unit"])
            if m.get("deprecated"):
                r.add("ERROR", "METRIC_DEPRECATED", where, f"'{name}' is deprecated, use '{m['replacement']}'")
            agg = am.get("aggregation")
            if agg not in m["aggregations"]:
                r.add("ERROR", "AGG_UNSUPPORTED", where, f"aggregation '{agg}' not supported by '{name}' {m['aggregations']}")
            # Dimensions (new and legacy model)
            dims = [f.get("dimension") for f in am.get("dimensionFilters") or []]
            if am.get("dimension") not in (None, "", "None"):
                dims.append(am.get("dimension"))
            for dim in dims:
                if dim not in m["dimensions"]:
                    r.add("ERROR", "DIM_UNSUPPORTED", where, f"dimension '{dim}' not supported by '{name}'")
            split = bool(dims)
            # Semantics
            grain = am.get("timeGrain")
            if am.get("timeGrainUnit"):
                grain = f"{grain} {am['timeGrainUnit']}"
            if m["kind"] == "gauge_total_only" and grain not in ("PT1M", "1 minute"):
                r.add("ERROR", "SEMANTIC_GAUGE_GRAIN", where,
                      f"'{name}' only supports Total; query it at PT1M (got '{grain}') or samples are summed")
            if m.get("entity_level") and not split and p.get("type") in ("stat", "singlestat", "gauge", "bargauge"):
                r.add("ERROR", "SEMANTIC_UNSPLIT_GAUGE", where,
                      f"'{name}' {agg} without EntityName split is a per-sample {agg.lower()} across entities, "
                      "not a namespace total; split by EntityName and sum")
            if p.get("type") in ("stat", "singlestat"):
                calcs = (p.get("options", {}).get("reduceOptions", {}) or {}).get("calcs") or [p.get("valueName")]
                if m["kind"] == "counter" and grain not in (None, "auto") and calcs and calcs[0] in ("current", "lastNotNull", "last"):
                    r.add("ERROR", "SEMANTIC_COUNTER_LAST", where,
                          f"counter '{name}' shown as the last {grain} bucket; the value depends on the grain and the "
                          "last bucket is often incomplete (use sum over range or label it as a per-grain count)")
            if split and not am.get("top") and "dimensionFilters" in am:
                r.add("INFO", "QUERY_TOP_DEFAULT", where, "split without 'top': Azure Monitor returns 10 series by default")
            if split and not am.get("alias"):
                r.add("WARN", "QUERY_NO_ALIAS", where, "split query without legend alias")
        if p.get("type") == "stat":
            calcs = (p.get("options", {}).get("reduceOptions", {}) or {}).get("calcs") or []
            rowsum = any(tr.get("id") == "calculateField" and (tr.get("options") or {}).get("mode") == "reduceRow"
                         for tr in p.get("transformations") or [])
            if rowsum and calcs and calcs[0] in ("lastNotNull", "last"):
                r.add("ERROR", "SEMANTIC_ROWSUM_LAST", ptitle(p),
                      "row sum across series then last value: a late/partial last row sums to 0 or a partial total "
                      "(reduce each series with 'reduce' lastNotNull, then sum)")
        if azure_units:
            ok = set().union(*(unit_map.get(u, []) for u in azure_units))
            if len(azure_units) > 1:
                r.add("WARN", "UNIT_MIXED", ptitle(p), f"panel mixes metric units {sorted(azure_units)}")
            elif unit is None:
                r.add("ERROR", "UNIT_MISSING", ptitle(p), f"no unit configured (metric unit {azure_units.pop()})")
            elif unit not in ok:
                r.add("ERROR", "UNIT_MISMATCH", ptitle(p),
                      f"unit '{unit}' does not match metric unit {sorted(azure_units)} (expected one of {sorted(ok)})")


def check_read_only(d, r):
    # 1) Panel types are enforced by check_panel_types (no form/button plugins).
    # 2) No Grafana "actions" (11.3+ can issue HTTP requests from panels).
    def find_key(obj, key, path="$"):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == key and v:
                    yield f"{path}.{k}", v
                yield from find_key(v, key, f"{path}.{k}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                yield from find_key(v, key, f"{path}[{i}]")
    for path, _ in find_key(d.get("panels"), "actions"):
        r.add("ERROR", "RO_PANEL_ACTION", path, "panel actions can issue HTTP requests; not allowed in a read-only dashboard")
    # 3) Links / data links: navigation only, no write-looking URLs.
    links = list(find_key(d, "links"))
    for path, lst in links:
        if not isinstance(lst, list):
            continue
        for i, l in enumerate(lst):
            url = (l or {}).get("url", "")
            if WRITE_KEYWORDS.search(url) or url.lower().startswith("javascript:"):
                r.add("ERROR", "RO_WRITE_LINK", f"{path}[{i}]", f"link looks like a write/script action: {url}")
    # 4) Text panels must not embed scripts or forms.
    for p in iter_panels(d.get("panels")):
        if p.get("type") == "text":
            content = json.dumps(p.get("options", {})) + str(p.get("content", ""))
            if re.search(r"<script|<form|fetch\(|XMLHttpRequest|onclick=", content, re.I):
                r.add("ERROR", "RO_TEXT_SCRIPT", ptitle(p), "text panel contains script/form/HTTP code")


def check_compatibility(d, r):
    sv = d.get("schemaVersion")
    if not isinstance(sv, int) or sv < TARGET_MIN_SCHEMA:
        r.add("ERROR", "COMPAT_SCHEMA_OLD", "$.schemaVersion",
              f"schemaVersion {sv} < {TARGET_MIN_SCHEMA}: authored for an old Grafana; relies on runtime migrations")
    elif sv > TARGET_MAX_SCHEMA:
        r.add("ERROR", "COMPAT_SCHEMA_NEW", "$.schemaVersion",
              f"schemaVersion {sv} > {TARGET_MAX_SCHEMA}: newer than the newest Grafana verified")
    for req in d.get("__requires", []):
        if req.get("id") == "grafana":
            try:
                major = int(str(req.get("version", "0")).split(".")[0] or 0)
            except ValueError:
                continue
            if major < 10:
                r.add("WARN", "COMPAT_REQUIRES", "$.__requires", f"declares Grafana {req.get('version')}")
    if d.get("style"):
        r.add("WARN", "COMPAT_IGNORED_PROP", "$.style", "'style' is ignored by modern Grafana (theme is per user)")
    for p in iter_panels(d.get("panels")):
        for tr in p.get("transformations", []) or []:
            if tr.get("id") not in ALLOWED_TRANSFORMATIONS:
                r.add("ERROR", "COMPAT_TRANSFORM", ptitle(p), f"transformation '{tr.get('id')}' not in verified set")
        for k in ("nullPointMode", "renderer", "colorBackground", "valueName", "sparkline", "yaxes", "seriesOverrides"):
            if k in p:
                r.add("WARN", "COMPAT_LEGACY_PANEL_PROP", ptitle(p), f"legacy panel property '{k}'")
                break


def run(path: Path, catalog_path: Path) -> Report:
    return validate(json.loads(path.read_text(encoding="utf-8")),
                    json.loads(catalog_path.read_text(encoding="utf-8")))


def validate(d: dict, catalog: dict) -> Report:
    r = Report()
    check_structure(d, r)
    declared = check_variables(d, r)
    check_datasources(d, r, declared)
    check_panel_types(d, r)
    check_layout(d, r)
    check_hardcoded_resources(d, r)
    check_queries(d, r, catalog)
    check_read_only(d, r)
    check_compatibility(d, r)
    return r


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dashboard", type=Path)
    ap.add_argument("--catalog", type=Path, default=Path(__file__).with_name("servicebus_metrics_catalog.json"))
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    a = ap.parse_args(argv)
    try:
        report = run(a.dashboard, a.catalog)
    except (OSError, json.JSONDecodeError) as e:
        print(f"ERROR JSON_INVALID {a.dashboard}: {e}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps([f.__dict__ for f in report.findings], indent=2))
    else:
        for f in sorted(report.findings, key=lambda f: ("ERROR", "WARN", "INFO").index(f.level)):
            print(f"{f.level:5} {f.code:26} {f.where}: {f.message}")
        print(f"\n{a.dashboard.name}: {report.count('ERROR')} error(s), {report.count('WARN')} warning(s), "
              f"{report.count('INFO')} info")
    return 1 if report.count("ERROR") else 0


if __name__ == "__main__":
    sys.exit(main())

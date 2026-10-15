# Compatibility matrix

## Target version

No environment information (Grafana config, version, data source settings) was available, so the installed
Grafana version is **unknown**. The dashboard is authored for a declared range instead of a single tested version:

- **Minimum:** Grafana **10.4** (LTS line; `schemaVersion` 39).
- **Verified by source inspection up to:** Grafana **13.2.4** (latest release tag at the time of writing; `DASHBOARD_SCHEMA_VERSION` 42).
- **Data source:** the core Azure Monitor data source bundled with Grafana (`grafana-azure-monitor-datasource`), not the retired 0.x plugin.

The file uses `schemaVersion: 39`. Grafana 12/13 migrate it forward on load (39 → 42); the reverse is not true,
which is why the newest schema was not used.

## Matrix

| Element used by the dashboard | 10.4 | 11.x | 12.x | 13.0–13.2 | Evidence |
|---|---|---|---|---|---|
| `schemaVersion` 39 import | ✓ native | ✓ native | ✓ migrated → 41 | ✓ migrated → 42 | `DashboardMigrator.ts` per tag |
| `stat`, `timeseries` panels | ✓ | ✓ | ✓ | ✓ | core panels since 7.x/8.x |
| Datasource object refs `{type, uid: ${datasource}}` | ✓ | ✓ | ✓ | ✓ | core |
| Metrics query model (`resources[]`, `metricNamespace`, `dimensionFilters`, `top`, `alias`) | ✓ | ✓ | ✓ | ✓ | `dataquery.cue`, backend `azuremonitor-datasource.go` |
| Variable `queryType` Azure Subscriptions / Resource Groups / Resource Names | ✓ | ✓ | ✓ | ✓ | `variables.ts` at v10.4.0 … v13.2.4 |
| Variable `queryType` Azure Dimension Values (entity picker) | ✗ | ✗ | ✗ | ✗ | only on `main` → **not used** |
| Transformation `reduce` (`seriesToRows`, `lastNotNull`) | ✓ | ✓ | ✓ | ✓ | core transformation since 7.x; not re-checked against each tag |
| Panel relative time override (`timeFrom`) on the "(now)" stats | ✓ | ✓ | ✓ | ✓ | core panel option; not re-checked against each tag |
| Alias macros `{{ entityname }}`, `{{ replica }}`, `{{ messagingerrorsubcode }}` | ✓ | ✓ | ✓ | ✓ | backend lowercases dimension labels |
| Legend `sortBy`/`sortDesc`, `stat` `wideLayout`/`showPercentChange` | ✓ | ✓ | ✓ | ✓ | options ignored silently if unknown |
| Grafana < 10.4 (9.x and older) | not supported | | | | `schemaVersion` 39 newer than their migrator; older variable editors |

✓ = supported according to source inspection. **None of these cells were confirmed by importing the dashboard into a
running Grafana instance.**

## Validation performed

| Kind | Status | Notes |
|---|---|---|
| JSON syntax & structural rules | Done | `validator/validate_dashboard.py` → 0 errors, 0 warnings |
| Validator regression tests | Done | 25 tests (`python3 -m unittest discover -s validator`) |
| Conformance with Grafana query/variable model | Done (source review) | Grafana repo tags v10.4.0, v11.0.0, v11.6.0, v12.0.0, v12.2.0, v12.3.0, v13.0.0, v13.2.4 |
| Import in a Grafana instance | **Pending** | No Grafana runtime/container daemon in the build environment |
| Queries against Azure Monitor | **Pending** | No Azure access (excluded by scope) |

## Known limitations

- Single namespace per view (`multi: false`). Multi-resource metric queries need same subscription, region and resource type.
- No entity filter variable in released Grafana (see matrix). Use legend click / search; or, once on a release that
  ships `Azure Dimension Values`, add a variable and set it in `dimensionFilters[].filters`.
- Per-entity panels and namespace totals are limited to `top: 50` entities.
- Premium-only metrics show "No data" on Basic/Standard namespaces (the row is collapsed by default).
- `ActiveConnections` runs at a fixed 1-minute grain: a 30-day range returns ~43 000 points per series.
- The Azure-portal link uses the `#@/resource/...` deep-link form; not verified against a live tenant.

## Pending checks (in order)

1. Import `dashboard/azure-service-bus.json` into the target Grafana (UI → Dashboards → New → Import). Confirm no migration warnings.
2. Select a datasource, subscription, resource group and namespace; confirm the cascade refreshes child variables.
3. Overview "(now)" stats: compare the summed Active / Dead-lettered values with the Azure portal namespace overview.
4. Confirm `top: 50` returns > 10 series on a namespace with more than 10 entities.
5. Confirm `{{ entityname }}` legends for topic subscriptions (exact `EntityName` format for subscriptions is not documented).
6. On a Premium namespace, expand "Capacity" and confirm CPU/memory per replica.
7. Check "No data" vs 0 rendering on an idle namespace.
8. Alerts: set the four environment variables, provision `alerting/azure-service-bus-alerts.json`, confirm the three rules load in "Azure Service Bus" and evaluate to Normal on a healthy namespace.
9. Optionally evaluate replacing the duplicated `ServerSendLatency` query with the `-- Dashboard --` data source (see AUDIT.md §3).

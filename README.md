# Azure Service Bus — modernized Grafana dashboard

[![validate](https://github.com/lvictorerod/grafana-azure-service-bus/actions/workflows/validate.yml/badge.svg)](https://github.com/lvictorerod/grafana-azure-service-bus/actions/workflows/validate.yml)

Read-only operational dashboard for one Azure Service Bus namespace, using Azure Monitor platform metrics.
Modernized from [grafana.com dashboard 10533](https://grafana.com/grafana/dashboards/10533-azure-service-bus/) (2019).

```
dashboard/azure-service-bus.json            ← import this
alerting/azure-service-bus-alerts.json     optional Grafana alert rules (file provisioning)
original/azure-service-bus-10533.original.json   (reference copy of 10533)
validator/validate_dashboard.py             static validator
validator/servicebus_metrics_catalog.json   Service Bus metrics catalog (Microsoft Learn)
validator/test_validate_dashboard.py        regression tests
docs/AUDIT.md          audit, decisions, before/after
docs/COMPATIBILITY.md  Grafana version matrix, limitations, pending checks
docs/METRICS.md        metrics, aggregations, units, constraints
```

## Requirements

- Grafana **10.4 or later** (verified by source inspection up to 13.2.4 — see docs/COMPATIBILITY.md).
- A configured **Azure Monitor** data source whose identity can read metrics of the target namespaces
  (Monitoring Reader or equivalent; identity configuration is out of scope). Setting a **Default Subscription**
  on the data source lets the Subscription variable populate automatically.

## Import (manual)

1. Grafana → **Dashboards → New → Import**.
2. Upload `dashboard/azure-service-bus.json` (or paste its content) → **Load**.
3. Choose a folder. The dashboard `uid` is `azure-service-bus`, the same as 10533: importing over an existing copy
   of the old dashboard replaces it (Grafana asks to overwrite). Change the uid in the dialog to keep both.
4. **Import.** No datasource mapping is requested: the datasource is chosen with the `Data source` variable.

## Selecting the environment

The same file serves dev, test, staging and production. Pick, top to bottom:

| Variable | Source | Depends on |
|---|---|---|
| Data source | any Azure Monitor data source in this Grafana | — |
| Subscription | `Azure Subscriptions` query | Data source |
| Resource group | `Azure Resource Groups` query | Subscription |
| Service Bus namespace | `Azure Resource Names` (type `microsoft.servicebus/namespaces`) | Resource group |

Changing a parent variable refreshes its children. To give each environment a stable link, select the values and
use **Share → Link**: variables are kept in the URL (`?var-datasource=…&var-subscription=…&var-resourceGroup=…&var-namespace=…`),
so one bookmark per environment is enough — no per-environment copies of the dashboard.
If no namespace exists in the selected resource group, the namespace list is empty and every panel shows "No data".

## Reading the dashboard

- **Overview** — "(now)" = latest 1-minute value of a state metric (always the last 30 minutes, whatever the time picker says), summed across entities; "(range)" = total over the selected time range. Orange = at least one dead-lettered message / server error / throttled request.
- **Throughput** — namespace-level messages, requests, bytes and send latency. Chart points are counts per Azure time grain, not rates.
- **Queues & topics** — one series per entity (top 50), including abandoned messages (consumers that keep failing on a message), legend table sorted by latest value; click a legend entry to isolate an entity, Ctrl/Cmd-click to add.
- **Errors & connections** — server vs user errors, throttling by reason (CPU / Storage / Namespace / Unknown), active connections.
- **Capacity (Premium tier only)** — collapsed; expand on Premium namespaces for CPU/memory per replica.

The dashboard contains no actions that send, receive, delete or resubmit messages or change resources. The
"Open namespace in Azure portal" link is navigation only; what can be done there is governed by Azure RBAC.

## Alerts (optional)

`alerting/azure-service-bus-alerts.json` holds three Grafana-managed alert rules for one namespace:

| Rule | Fires when | Instances |
|---|---|---|
| Dead-lettered messages | an entity has ≥ 1 dead-lettered message for 5 minutes | one per entity |
| Server errors | ≥ 1 server error in the last 10 minutes | one |
| Throttled requests | ≥ 1 throttled request in the last 10 minutes | one per throttling reason |

Alert rules cannot use dashboard variables, so the file reads the target from environment variables, which Grafana
expands when it loads provisioning files: `AZURE_MONITOR_DS_UID`, `ASB_SUBSCRIPTION_ID`, `ASB_RESOURCE_GROUP`,
`ASB_NAMESPACE`. Set them on the Grafana server and copy the file to `<provisioning>/alerting/`, then restart Grafana.
Rules land in the folder "Azure Service Bus"; one Grafana instance alerts on one namespace with this file (copy the
group with other uids/variables for more). Missing data counts as OK; a failing query (wrong ids, missing permission)
puts the rule in the Error state. Routing goes through the default notification policy; contact points are not part
of this repository. Provisioned rules are read-only in the Grafana UI.

## Validation

```bash
python3 validator/validate_dashboard.py dashboard/azure-service-bus.json      # exit 0 = no errors
python3 -m unittest discover -s validator -v                                # regression tests
```

Both run on every push to `main` and on pull requests (`.github/workflows/validate.yml`).

The validator runs offline. It checks JSON syntax, unique panel ids/refIds, layout, deprecated/plugin panel types,
datasource references (no hardcoded uids or name strings), declared/used variables and cascade order, hardcoded
subscriptions/resource groups/namespaces/GUIDs, every metric/aggregation/dimension against the catalog, semantic
traps (unsplit entity gauges in stats, counter "last bucket" stats, row-sum-then-last stats, Total-only gauges at coarse grain), units,
read-only rules (no panel actions, write-looking links or scripts) and the supported schemaVersion range.
Static validation does **not** prove the dashboard renders or that queries return data — see docs/COMPATIBILITY.md.

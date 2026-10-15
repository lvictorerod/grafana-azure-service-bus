# Audit report — Azure Service Bus dashboard (grafana.com 10533)

**Original:** `original/azure-service-bus-10533.original.json`, downloaded 2026-10-15 from
`https://grafana.com/api/dashboards/10533/revisions/latest/download` (author Sriramajeyam Sugumaran, 2019).
**Modernized:** `dashboard/azure-service-bus.json`.
**Method:** manual inspection of the JSON, Microsoft Learn metrics reference, Grafana source code
(Azure Monitor data source query/variable model, tags v10.4.0 → v13.2.4) and the offline validator in `validator/`.

## 1. State of the original

| Aspect | Finding |
|---|---|
| Model | `schemaVersion` 18, `__requires` Grafana 6.1.6, Azure Monitor plugin 0.3.0 (pre-core plugin). |
| Panels | 1 row, 12 `singlestat`, 8 `graph` (Flot renderer). Both types are removed from modern Grafana and only survive through automatic runtime migration. |
| Datasource | Referenced as the string `"$Subscriptions"`, a **datasource** variable misleadingly named "Subscriptions". There is no subscription variable: every query uses the datasource's default subscription. |
| Queries | 24 Azure Monitor targets in the pre-Grafana-9 model (`metricDefinition`, `resourceGroup`/`resourceName`, `timeGrain`+`timeGrainUnit`, `dimension`/`dimensionFilter`, UI leftovers `aggOptions`, `dimensions`, `timeGrains`). |
| Leftovers | Unused `appInsights` blocks in every target; unused `azureLogAnalytics` placeholder KQL in 8 targets, three of them with **hardcoded workspace GUIDs** from the author's tenant. |
| Variables | `Subscriptions` (datasource), `ResourceGroup` = `ResourceGroups()`, `ResourceName` = `ResourceNames($ResourceGroup,Microsoft.ServiceBus/namespaces)` — legacy string functions. `ResourceName` has no label. |
| Transformations | None. |
| Thresholds/colours | Arbitrary absolute thresholds on every singlestat (`200,1000`, `100,500`, `10,50`, `2,4`, `102400000,204800000`) with full background colouring. Five panels use an **inverted** palette (low = red), so a quiet namespace shows Incoming/Outgoing/Successful/Active Connections in red. |
| Time | `now-6h` → `now-1m`, refresh `1m`, refresh options down to 30 s (metrics have 1-minute granularity). |
| Links | One link to the retired `docs.microsoft.com/en-in/.../metrics-supported` page. |
| Plugins | None beyond core panels; `style: dark` is ignored by modern Grafana. |
| Write actions | None found (no panel actions, data links, scripts or plugins that write). Requirement is satisfied by construction and now enforced by the validator. |
| Validator result | **57 errors, 99 warnings** (see §5). |

### Semantic defects found (not just cosmetic)

1. **Backlog stats are not totals.** "Messages in Queue", "Active messages in Queue" and "Size" query entity-level
   point-in-time metrics with `Average` and **no** `EntityName` split. Azure Monitor computes an unsplit Average as
   Sum ÷ Count of all samples across entities, i.e. the mean *per entity*, not the namespace backlog
   ([metrics aggregation explained](https://learn.microsoft.com/azure/azure-monitor/metrics/metrics-aggregation-explained)).
   With 10 queues holding 100 messages each the stat shows 100, not 1 000.
2. **"DEAD LETTER"** uses `Maximum` unsplit → largest single entity, presented as if it were the total.
3. **Counter stats show one 1-minute bucket.** Seven singlestats (`Total` counters at a fixed 1-minute grain with
   `valueName: current` and `nullPointMode: connected`) display only the last minute, which is frequently incomplete
   or null-then-connected (stale). The value is labelled "Incoming Messages" etc. without any time base.
4. **Per-entity graphs capped at 10 series silently.** The old model sends no `top`; Azure Monitor returns 10 series by default.
5. **"Dead Letters By Topic"** — the split is by `EntityName`, which covers queues as well as topics.
6. **"Service Bus - No of Requests"** draws 3 metrics × N entities in one graph (up to 30 lines), unreadable at scale.

## 2. Component classification

| # | Original component | Problem | Change | Category | Justification |
|---|---|---|---|---|---|
| 27 | Row "Service Bus" | Single row, no hierarchy | Five rows: Overview, Throughput, Queues & topics, Errors & connections, Capacity (Premium, collapsed) | Replace | Operator reads health first, then drills down. |
| 10 | singlestat "Messages in Queue" (`Messages` Avg unsplit) | Defect 1; `Messages` mixes active+DLQ+scheduled | Removed as a headline; replaced by separate Active / Dead-lettered / Scheduled stats | Replace | Each state needs a different response; the sum of all three adds no information. `Messages` per entity is still recoverable as Active+DLQ+Scheduled. |
| 11 | singlestat "Active messages in Queue" | Defect 1 | Stat "Active messages (now)": split by EntityName (top 50) → last non-null per entity → sum, last 30 min at PT1M | Modernize | Real namespace backlog. |
| 19 | singlestat "DEAD LETTER" (`Maximum` unsplit) | Defect 2; shouting title | Stat "Dead-lettered messages (now)" summed across entities, orange when ≥ 1 | Modernize | Any DLQ message is actionable; threshold has operational meaning. |
| 29 | singlestat "Size" | Defect 1; arbitrary 100/200 MB thresholds | Stat "Entity size (now)" summed across entities, no thresholds | Modernize | Quota depends on tier/entity config → no universal threshold. |
| 14 / 16 | singlestat "Incoming / Outgoing Messages" | Defect 3; inverted colours | Stats "… (range)" = sum over the selected range, neutral colour | Modernize | Range total is grain-independent and unambiguous. |
| 12 | singlestat "Server Errors" | Defect 3 | Stat "Server errors (range)", orange ≥ 1 | Modernize | |
| 18 | singlestat "Throttled requests" | Defect 3 | Stat "Throttled requests (range)", orange ≥ 1 | Modernize | |
| 13 | singlestat "User errors" | Defect 3; red at 10 | Stat "User errors (range)", neutral | Modernize | User errors include expected client behaviour (e.g. lock lost); no fixed threshold is defensible. |
| 15 | singlestat "Successful Requests" | Defect 3; inverted colours | Stat "Successful requests (range)", neutral | Modernize | |
| 17 | singlestat "Incoming Requests" | Defect 3; redundant with Successful+Throttled | **Removed as a stat**; kept as a series in "Requests (namespace)" | Remove (stat) | Avoid duplicate headline numbers; information preserved in the time series. |
| 20 | singlestat "Active Connections" | Inverted colours, thresholds `2,4` meaningless | Stat "Active connections (now)" at fixed PT1M, neutral | Modernize | `Total` is the only aggregation; a fixed 1-minute grain keeps it a point value. |
| 2 | graph "Dead Letters By Topic" | Defects 4, 5 | Time series "Dead-lettered messages by entity", top 50, legend table sorted by last value | Modernize | |
| 22 | graph "No of Requests" (3 metrics × entities) | Defect 6 | Time series "Requests (namespace)" (3 series, unsplit) | Modernize | Per-entity request split moved out of the default view; entity traffic is shown by Incoming/Outgoing by entity. |
| 4 | graph "Incoming & Outgoing messages" by entity | 2 × N lines in one chart | Split into "Messages in / out (namespace)" plus "Incoming messages by entity" and "Outgoing messages by entity" | Modernize | Comparison at namespace level, drill-down per entity. |
| 28 | graph "Messages in Queue / Topic" (`Messages` by entity) | Overlaps 30 + DLQ panel | Removed | Remove | `Messages` = Active + Dead-lettered + Scheduled, all shown per entity. Saves one query per refresh. |
| 30 | graph "Active Messages in Queue / Topic" | Defect 4 | "Active messages by entity" | Modernize | |
| 23 | graph "Size" by entity | Defect 4 | "Entity size" (decbytes) | Modernize | |
| 24 | graph "Active Connections" | Old graph | "Active connections" at PT1M | Modernize | |
| 3 | graph "Errors" (stacked bars, identical aliases) | Both series named `{{metric}} - {{resourcename}}` ⇒ indistinguishable without hovering | "Errors (namespace)" bars, explicit aliases | Modernize | |
| — | *(new)* Throttled requests by reason | Throttling cause invisible | Split by `MessagingErrorSubCode` (CPU / Storage / Namespace / Unknown) | Add | Documented dimension; tells the operator *what* to scale. |
| — | *(new)* Scheduled messages (stat + by entity) | Not shown | Added | Add | Scheduled messages explain backlog that is not "stuck". |
| — | *(new)* Data volume, Server send latency | Not shown | Added (Incoming/OutgoingBytes, ServerSendLatency) | Add | Degradation signals that message counts alone do not show. |
| — | *(new)* Abandoned messages by entity | Consumer failures invisible until messages reach the DLQ | `AbandonMessage` Total split by EntityName | Add | Early signal of poison messages / failing consumers. |
| — | *(new)* Alert rules (optional file) | No alerting | `alerting/azure-service-bus-alerts.json`: dead-lettered (per entity), server errors, throttled (per reason) | Add | Same thresholds as the orange stats; read-only (metric queries only). |
| — | *(new)* CPU / Memory (Premium) | Not shown | Collapsed row, `NamespaceCpuUsage` / `NamespaceMemoryUsage` Maximum by Replica | Add | Premium only; collapsed so Standard users don't see empty panels by default. Deprecated `CPUXNS`/`WSXNS` deliberately not used. |
| var | `Subscriptions` (datasource var) | Misnamed, no subscription selection | `datasource` (datasource var) + `subscription` (`Azure Subscriptions`) | Replace | Same dashboard across subscriptions / environments. |
| var | `ResourceGroup` = `ResourceGroups()` | Legacy function | `resourceGroup` (`Azure Resource Groups`, depends on `$subscription`) | Modernize | |
| var | `ResourceName` = `ResourceNames(...)` | Legacy function, no label, refresh on time change | `namespace` (`Azure Resource Names`, namespace `microsoft.servicebus/namespaces`), refresh on load | Modernize | Resource list does not depend on the time range. |
| var | *(requested)* entity variable | — | **Not added** | Investigate | `Azure Dimension Values` variable exists only on Grafana `main`, not in any release up to v13.2.4. Entity filtering is available via legend click / legend search. |
| link | docs.microsoft.com metrics link | Retired URL | Microsoft Learn Service Bus metrics reference + "Open namespace in Azure portal" (navigation) | Modernize | |
| time | `now-1m`, 30 s refresh | 30 s refresh on 1-minute data | `now`, refresh 1m+, stats use *last non-null* | Modernize | Trailing nulls handled by the reducer instead of shifting the window. |
| misc | `style`, `gnetId`, `_author`, leftover `appInsights` / `azureLogAnalytics` blocks, workspace GUIDs | Dead config, tenant leakage | Removed | Remove | |
| misc | `uid: azure-service-bus`, title, tags `azure` | — | Kept (tags extended) | Keep | Preserves identity; re-import overwrites the old version cleanly. |

## 3. Design decisions

- **Two kinds of stats, labelled explicitly.** "(now)" = latest non-null point-in-time value at PT1M, with a fixed 30-minute panel time override so it stays a current value on long ranges; "(range)" = sum of a counter over the selected time range. This removes the grain dependence of the original.
- **Namespace totals for entity gauges** are computed in Grafana (split by `EntityName` → `reduce` *seriesToRows* with `lastNotNull` per entity → stat *sum*). This is exact up to the `top` limit (50). An earlier version summed rows first (`joinByField` → `calculateField` reduceRow) and then took the last row; a late or partial last minute then summed to 0 or to a partial total. The validator now rejects that pattern (`SEMANTIC_ROWSUM_LAST`).
- **`top` = 50** for every entity split (Azure default is 10). Larger namespaces should raise it; see docs/METRICS.md.
- **Thresholds only where they carry meaning:** dead-lettered, server errors and throttled requests turn orange at ≥ 1. Everything else is neutral. No invented health percentages.
- **Missing data vs zero:** stats show "No data" instead of 0; time series do not span nulls. Microsoft documents that counts may read 0 while a namespace is throttled — noted in the relevant descriptions.
- **Counters use `timeGrain: auto`** so long ranges stay cheap; descriptions state that each point is a per-grain count, not a rate. Fixed `PT1M` is used only for `ActiveConnections` (Total-only gauge) and the "(now)" stats (30-minute window).
- **Single resource per query.** Multi-select namespaces was not enabled: multi-resource metrics require same subscription, region and type, and the dashboard's purpose is one namespace at a time.
- **Deliberate query duplication.** The "(now)" stats query their metric over a fixed 30-minute window, so they cannot reuse the detail panel's result. Only `ServerSendLatency` (stat + chart) is still a true duplicate. Grafana's `-- Dashboard --` data source could reuse it, but the source panels sit below the fold and source-panel execution outside the viewport has differed across Grafana versions; robustness was preferred over one fewer metric call. Revisit after the import test (docs/COMPATIBILITY.md).
- **schemaVersion 39** (export format of Grafana 10.4/11.x) rather than the newest 42, so the same file imports on every version in the matrix; newer Grafana migrates forward automatically.
- **Read-only:** native panels only, no panel `actions`, no scripts. The Azure-portal link is navigation; what a user can do in the portal is governed by Azure RBAC (out of scope).

## 4. Before / after

| | Original | Modernized |
|---|---|---|
| Schema / Grafana | 18 / 6.1 | 39 / 10.4 → 13.x |
| Panel types | singlestat ×12, graph ×8 | stat ×12, timeseries ×16 (2 in collapsed row) |
| Azure queries | 24 | 33 (31 on load; the 2 Premium queries run only when the row is expanded) |
| Datasource reference | name string `$Subscriptions` | `{type, uid: ${datasource}}` |
| Environment selection | datasource → RG → namespace (subscription fixed by DS) | datasource → subscription → RG → namespace |
| Hardcoded tenant IDs | 3 workspace GUIDs | none |
| Namespace backlog stat | per-entity mean (wrong) | sum across entities |
| Counter stats | last 1-minute bucket | total over selected range |
| Entity series limit | 10 (implicit) | 50 (explicit) |
| Throttling cause | not visible | by `MessagingErrorSubCode` |
| Premium CPU/memory | none | `NamespaceCpuUsage` / `NamespaceMemoryUsage` |
| Validator | 57 errors, 99 warnings | 0 errors, 0 warnings |

**Functionality not preserved 1:1:** the `Messages` (all states) metric and the "Incoming Requests" headline stat are no longer shown as separate panels (see table §2 for where the information lives now); per-entity request splits (successful/incoming/throttled × entity) were dropped in favour of namespace-level request series plus per-entity message traffic.

## 5. Validation status

| Level | Status |
|---|---|
| Static validation (JSON, IDs, layout, datasource refs, variables, hardcoded resources, metrics/aggregations/dimensions vs catalog, units, read-only, schema range) | **Done** — 0 errors / 0 warnings; 25 regression tests pass. |
| Model conformance vs Grafana source (query fields, variable `queryType`s, transformation ids, alias macros) | **Done by source inspection**, not by executing Grafana. |
| Import into a running Grafana instance | **Not done** — no Grafana runtime or container daemon available in the build environment. |
| Queries executed against Azure Monitor | **Not done** — no Azure access (out of scope by design). |
| Visual/UX review of the rendered dashboard | **Not done** — requires the import above. |

See docs/COMPATIBILITY.md for the pending checks list.

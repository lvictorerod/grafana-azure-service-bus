# Metrics report

Source of truth: [Azure Service Bus monitoring data reference](https://learn.microsoft.com/azure/service-bus-messaging/monitor-service-bus-reference)
(retrieved 2026-10-15), mirrored in `validator/servicebus_metrics_catalog.json`, and
[Azure Monitor metrics aggregation explained](https://learn.microsoft.com/azure/azure-monitor/metrics/metrics-aggregation-explained).
All Service Bus platform metrics have 1-minute (PT1M) native granularity. Metric namespace: `microsoft.servicebus/namespaces`.

## Metric kinds and how the dashboard treats them

| Kind | Meaning | Correct use | Dashboard treatment |
|---|---|---|---|
| Counter (`Total`) | Events accumulated per time grain; additive across grains | Sum over a range; per-grain counts in charts | Stats: **sum over selected range**. Charts: count per auto grain (stated in descriptions). Never shown as a per-second rate. |
| Point-in-time (`Average`/`Min`/`Max`) | Sampled state (queue depth, size) | Latest value; never `Total` | Stats: **latest non-null per entity, then summed in Grafana** (split by `EntityName`), queried over the last 30 minutes at PT1M. |
| Gauge exposed only as `Total` | `ActiveConnections` | Fixed PT1M grain | Fixed `PT1M` in both panels; the stat also uses a 30-minute window. |
| Pre-averaged (`Average` only) | Latency | Mean | Stat: mean over range. |

## Metrics used

| Metric (REST name) | Unit → Grafana unit | Aggregation used | Dimension split | Panels | Constraints / notes |
|---|---|---|---|---|---|
| `ActiveMessages` | Count → short | Average | EntityName (top 50) | Active messages (now); Active messages by entity | Point-in-time. Reads 0 while the namespace is throttled (documented by Microsoft). |
| `DeadletteredMessages` | Count → short | Average | EntityName (top 50) | Dead-lettered messages (now); …by entity | Point-in-time. Orange at ≥ 1 in the stat. |
| `ScheduledMessages` | Count → short | Average | EntityName (top 50) | Scheduled messages (now); …by entity | Point-in-time. New vs original. |
| `Size` | Bytes → decbytes | Average | EntityName (top 50) | Entity size (now); Entity size | Point-in-time. |
| `IncomingMessages` | Count → short | Total | none / EntityName | Incoming messages (range); Messages in/out; Incoming by entity | Includes auto-forwarded messages. |
| `OutgoingMessages` | Count → short | Total | none / EntityName | Outgoing messages (range); Messages in/out; Outgoing by entity | Excludes outgoing auto-forwarded messages; may legitimately differ from incoming. |
| `IncomingRequests` | Count → short | Total | none | Requests (namespace) | |
| `SuccessfulRequests` | Count → short | Total | none | Successful requests (range); Requests | |
| `ThrottledRequests` | Count → short | Total | none / MessagingErrorSubCode | Throttled requests (range); Requests; Throttled by reason | Sub-codes documented: CPU, Storage, Namespace, Unknown. |
| `ServerErrors` | Count → short | Total | none | Server errors (range); Errors | Orange at ≥ 1 in the stat. |
| `UserErrors` | Count → short | Total | none | User errors (range); Errors | Includes expected client conditions (e.g. lock lost) → no threshold. |
| `IncomingBytes` / `OutgoingBytes` | Bytes → decbytes | Total | none | Data volume | New vs original. |
| `ServerSendLatency` | MilliSeconds → ms | Average | none | Server send latency (avg); Server send latency | New vs original. |
| `AbandonMessage` | Count → short | Total | EntityName (top 50) | Abandoned messages by entity | Lock released without completing; repeated abandons end in the DLQ after MaxDeliveryCount. |
| `ActiveConnections` | Count → short | Total @ PT1M | none (no dimensions) | Active connections (now); Active connections | Only `Total` is supported → fixed grain. |
| `NamespaceCpuUsage` | Percent → percent (max 100) | Maximum | Replica | CPU usage (Premium) | **Premium only.** Replaces deprecated `CPUXNS`. |
| `NamespaceMemoryUsage` | Percent → percent (max 100) | Maximum | Replica | Memory usage (Premium) | **Premium only.** Replaces deprecated `WSXNS`. |

## Metrics from the original that were dropped

| Metric | Reason |
|---|---|
| `Messages` | Sum of all message states; redundant with Active + Dead-lettered + Scheduled, which are shown separately per entity. |

## Available but not used (candidates)

`CompleteMessage` (consumer throughput per entity), `ConnectionsOpened`/`ConnectionsClosed`
(documented aggregation is `Average`; semantics of an averaged connection count were not clear enough to chart
without testing), `PendingCheckpointOperationCount` (Premium), `ReplicationLagCount`/`ReplicationLagDuration`
(geo-replication only). Deprecated `CPUXNS`/`WSXNS` are rejected by the validator.

## Query cost and cardinality

- Entity splits request `top: 50`. Azure Monitor returns 10 series when `top` is omitted. Raise `top` in the six
  entity queries + four entity stats for larger namespaces; namespace totals are only exact up to that limit.
- Counters use `timeGrain: auto` (Grafana picks the grain from the range), so a 30-day view stays cheap.
- 31 metric calls per refresh on load (33 with the Premium row expanded). Default refresh is 1 minute; refresh
  intervals below 1 minute were removed because the metrics have 1-minute granularity.

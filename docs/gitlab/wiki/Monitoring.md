# Monitoring and release health

[Private GCP operations dashboard](https://console.cloud.google.com/monitoring/dashboards/builder/c9a32446-520c-45cd-a86a-54a4917c64fc?project=project-bb13ecd8-9d67-408d-9a7)
uses existing VM CPU/memory, production request rate, 5xx rate, p95 latency and staging request
rate. It requires existing GCP IAM access. No logs or telemetry have been made public.

All charts were queried against actual data on **2026-10-19 UTC**. VM CPU, Ops Agent memory,
production traffic/latency and staging traffic returned samples. The 5xx selector returned
no series in that window; this is not a claim of continuous availability. Metric ingestion
and chart refresh can lag. The dashboard creates no new VM, backend, agent or notification channel.

[Cloud Logs Explorer](https://console.cloud.google.com/logs/query?project=project-bb13ecd8-9d67-408d-9a7)
contains the existing VM Ops Agent and Cloud Run operational logs. Filter by `request_id`,
`dataset_id`, source SHA and deployment operation. Do not paste tokens or patient information
into logs. Ingestion failures, retrieval timings and deployment events are separate operations.

GitLab views:

- [Environments](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/22263020/showcase/-/environments)
- [Pipeline analytics](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/22263020/showcase/-/pipelines/charts)
- [CI jobs and real test reports](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/22263020/showcase/-/pipelines)
- [Release evidence](Release-evidence)

The verified release's public smoke passed in **30.26 seconds**. It is a point-in-time real
investigation, not a background uptime monitor or SLA. Staging/prod links are distinct.
Hosted GitLab Observability and additional account-dependent integrations are not configured.

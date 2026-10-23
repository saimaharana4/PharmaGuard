# PharmaGuard AI operations

[Open the chatbot](https://pharmaguard-web-dfthmgvvaa-el.a.run.app) ·
[Staging preview](https://pharmaguard-vm-preview-dfthmgvvaa-el.a.run.app) ·
[Source and setup](../blob/main/README.md)

PharmaGuard investigates drug-safety reporting signals using real FAERS, archived DailyMed
labels and a bounded PubMed corpus. It is a research prototype, not medical advice or proof
of causality. PostgreSQL supplies deterministic facts; MedCPT retrieves canonical evidence;
Vertex synthesizes cited explanations. Coverage gaps are visible in each investigation.

- [Planning and traceability](Planning-and-traceability): epics, requirements, reviewed Test Cases and board.
- [Release evidence](Release-evidence): immutable source, image digests, actual gates and human approvals.
- [Architecture and operations](Architecture-and-operations): routing, data flow and recovery.
- [Security and governance](Security-and-governance): credentials, scans and approval boundaries.
- [Monitoring](Monitoring): existing private telemetry and point-in-time release health.

Repository documentation is the technical source of truth. These pages provide navigation
and recorded evidence; a green historical release is not a guarantee about a later revision.

"""Populate real planning records idempotently; never backdate or rewrite benchmark labels."""

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

from operations.gitlab import GitLab

PROJECT_ID = 87777712
PROJECT_PATH = "gitlab-ai-hackathon/transcend-october-2026/22263020/showcase"
GROUP_PATH = PROJECT_PATH.rsplit("/", 1)[0]
URL = "https://gitlab.com/" + PROJECT_PATH
SOURCE = "a3eeebea0931d1c422132612cf0ceba74601b6a2"
PIPELINE = URL + "/-/pipelines/2964230916"
SNAPSHOT_SHA256 = "3e24ee4fb783704abcf7ea538bbf490cbe7b147d7d70ebffe52b8673a85086a1"
LABELS = {
    "workflow::ready": "#428BCA",
    "workflow::in-progress": "#D97706",
    "workflow::review": "#8B5CF6",
    "workflow::blocked": "#DC2626",
    "priority::high": "#B91C1C",
    "priority::normal": "#64748B",
    "type::retrospective": "#475569",
    "type::requirement": "#0F766E",
    "type::test-case": "#0369A1",
    "stage::plan": "#4F46E5",
    "stage::verify": "#4F46E5",
    "stage::secure": "#4F46E5",
    "stage::release": "#4F46E5",
    "stage::configure": "#4F46E5",
    "stage::monitor": "#4F46E5",
    "stage::govern": "#4F46E5",
}
MILESTONES = {
    "baseline": "Verified release baseline",
    "visibility": "Operational visibility and native reports",
    "repair": "Supervised release repair demonstration",
}
EPICS = {
    "baseline": "Reliable evidence and verified releases",
    "visibility": "Operational visibility and security evidence",
    "repair": "Supervised release repair with human governance",
}
REQUIREMENTS = [
    (
        "metrics",
        "Metrics originate from deterministic distinct-case calculations",
        "tests/test_signals.py",
        "facts_match",
    ),
    (
        "temporal",
        "Retrieval excludes evidence unavailable at the requested cutoff",
        "tests/test_retrieval.py",
        "temporal_leakage",
    ),
    (
        "citations",
        "Every returned citation resolves to eligible canonical evidence",
        "tests/test_security.py",
        "citation_integrity",
    ),
    (
        "recall",
        "Reviewed benchmark retrieves required and all critical evidence",
        "evaluation/core.py",
        "critical_hit",
    ),
    (
        "isolation",
        "Staging cannot stop or retarget approved production",
        "tests/test_vm_channels.py",
        None,
    ),
    (
        "memory",
        "Session memory retains only the newest five complete exchanges",
        "tests/test_conversation.py",
        None,
    ),
    (
        "governance",
        "Production promotion requires a human and unchanged release gates",
        ".gitlab/ci/vm.yml",
        None,
    ),
]
ITEMS = [
    (
        "release-baseline",
        "Verified production release and routing isolation",
        "baseline",
        "stage::release",
        True,
        "Document the release retrospectively, preserving actual dates and failed attempts.",
        [
            "All 20 jobs passed at the recorded source",
            "Production smoke passed with required citations",
            "Independent staging/production routing and image digests verified",
        ],
    ),
    (
        "terraform-recovery",
        "Recover partial Terraform applies without stale plans or broad IAM",
        "baseline",
        "stage::configure",
        True,
        "Record the permission failure, partial apply, fresh-plan recovery and revoked grant.",
        [
            "Original failure and stale-plan retry retained",
            "Fresh apply recorded 2 added, 0 changed, 0 destroyed",
            "Temporary network-create binding revoked",
        ],
    ),
    (
        "planning",
        "Link planning, requirements, test cases and operator documentation",
        "visibility",
        "stage::plan",
        False,
        "Create durable work-item traceability for the application and its release process.",
        [
            "Requirements and reviewed benchmark Test Cases exist",
            "Epics, milestones and board lists link real work",
            "Wiki links resolve to source, environments and immutable evidence",
        ],
    ),
    (
        "test-reporting",
        "Publish complete native test and deterministic RAG reports",
        "visibility",
        "stage::verify",
        False,
        "Expose actual frontend, integration, routing and frozen RAG results in GitLab Tests.",
        [
            "JUnit reports include all executed suites",
            "RAG report conversion fails closed on malformed results",
            "Reviewed labels, checksum and gate thresholds are unchanged",
        ],
    ),
    (
        "security-reporting",
        "Publish native security findings and dependency SBOMs",
        "visibility",
        "stage::secure",
        False,
        "Retain blocking audits and add source, dependency, secret and container reports.",
        [
            "Native reports validate against their schemas",
            "No finding is hidden to achieve green status",
            "Dependency inventory and immutable image scan evidence are available",
        ],
    ),
    (
        "monitoring",
        "Surface existing monitoring data and release health dashboards",
        "visibility",
        "stage::monitor",
        False,
        "Use existing Cloud Logging/Monitoring and GitLab data without extra accounts.",
        [
            "Dashboard links show existing VM and service telemetry",
            "Health evidence is clearly distinguished from continuous monitoring",
            "No prompts, answers, tokens or secret payloads are exported",
        ],
    ),
    (
        "environment-links",
        "Expose staging URL and explicit deployment tiers",
        "visibility",
        "stage::release",
        False,
        "Make both channels inspectable with independent routing and human promotion.",
        [
            "Staging and production environment links resolve",
            "Staging/production tiers are explicit",
            "Existing manual approvals and WIF restrictions remain",
        ],
    ),
    (
        "duo-demo",
        "Demonstrate one bounded Duo regression diagnosis and repair",
        "repair",
        "stage::govern",
        False,
        "Future demonstration on a separate branch; production requires human approval.",
        [
            "Real hosted Duo session reads the failing artifacts",
            "One bounded product fix preserves all gates and labels",
            "Failed repair stops; successful staging evidence is reviewed by a human",
        ],
    ),
]


def reviewed_cases(snapshot: Path) -> list[dict]:
    with snapshot.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != SNAPSHOT_SHA256:
            raise ValueError("Snapshot differs from the approved frozen corpus")
    with zipfile.ZipFile(snapshot) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    if manifest["dataset_version"] != "v2" or len(manifest["cases"]) != 10:
        raise ValueError("Expected the ten reviewed v2 benchmark cases")
    return manifest["cases"]


class Workspace:
    def __init__(self, api: GitLab):
        self.api = api
        self.records = {}

    def work_items(self, namespace: str):
        result, cursor = [], None
        while True:
            data = self.api.graphql(
                "query($path:ID!,$cursor:String){namespace(fullPath:$path){"
                "workItems(first:100,after:$cursor){nodes{id iid title description webUrl state}"
                "pageInfo{hasNextPage endCursor}}}}",
                {"path": namespace, "cursor": cursor},
            )["namespace"]["workItems"]
            result.extend(data["nodes"])
            if not data["pageInfo"]["hasNextPage"]:
                return result
            cursor = data["pageInfo"]["endCursor"]

    def item(self, namespace: str, key: str, title: str, kind: str, description: str, **widgets):
        marker = f"<!-- pharmaguard-operations:{key} -->"
        existing = next(
            (v for v in self.items[namespace] if marker in (v["description"] or "")), None
        )
        if existing:
            self.records[key] = existing
            return existing
        body = {
            "namespacePath": namespace,
            "workItemTypeId": self.types[namespace][kind],
            "title": title,
            "descriptionWidget": {"description": description + "\n\n" + marker},
            **widgets,
        }
        payload = self.api.graphql(
            "mutation($input:WorkItemCreateInput!){workItemCreate(input:$input){"
            "errors workItem{id iid title description webUrl state}}}",
            {"input": body},
        )["workItemCreate"]
        if payload["errors"]:
            raise RuntimeError("Cannot create " + key + ": " + str(payload["errors"]))
        record = payload["workItem"]
        self.items[namespace].append(record)
        self.records[key] = record
        print(
            json.dumps({"event": "work_item_created", "key": key, "url": record["webUrl"]}),
            flush=True,
        )
        return record

    def apply(self, cases: list[dict]) -> dict:
        project = f"projects/{PROJECT_ID}"
        labels = {
            v["name"]: v for v in self.api.pages(project + "/labels?include_ancestor_groups=false")
        }
        for name, color in LABELS.items():
            if name not in labels:
                labels[name] = self.api.request(
                    "POST", project + "/labels", {"name": name, "color": color}
                )
        milestones = {v["title"]: v for v in self.api.pages(project + "/milestones")}
        for title in MILESTONES.values():
            if title not in milestones:
                milestones[title] = self.api.request(
                    "POST",
                    project + "/milestones",
                    {
                        "title": title,
                        "description": "Evidence-linked work with actual dates.",
                    },
                )
        self.items, self.types = {}, {}
        for namespace in [GROUP_PATH, PROJECT_PATH]:
            self.items[namespace] = self.work_items(namespace)
            data = self.api.graphql(
                "query($path:ID!){namespace(fullPath:$path){workItemTypes{nodes{id name}}}}",
                {"path": namespace},
            )
            self.types[namespace] = {
                v["name"]: v["id"] for v in data["namespace"]["workItemTypes"]["nodes"]
            }
        for key, title in EPICS.items():
            self.item(
                GROUP_PATH,
                "epic-" + key,
                title,
                "Epic",
                f"Track {title.lower()} through implementation, verification and release."
                f"\n\nVerified baseline: {PIPELINE}.",
            )
        for key, title, phase, stage, closed, problem, criteria in ITEMS:
            description = (
                problem + "\n\nAcceptance criteria:\n" + "\n".join("- [ ] " + c for c in criteria)
            )
            description += f"\n\nRelease evidence: {PIPELINE}\n\nSource: `{SOURCE}`."
            if closed:
                description += (
                    "\n\nRetrospective record: entered after the outcome, without backdating. "
                    "All listed criteria were observed in the linked release."
                )
                description = description.replace("- [ ]", "- [x]")
            record = self.item(
                PROJECT_PATH,
                key,
                title,
                "Issue",
                description,
                hierarchyWidget={"parentId": self.records["epic-" + phase]["id"]},
                milestoneWidget={
                    "milestoneId": "gid://gitlab/Milestone/"
                    + str(milestones[MILESTONES[phase]]["id"])
                },
                labelsWidget={
                    "labelIds": [
                        "gid://gitlab/ProjectLabel/" + str(labels[n]["id"])
                        for n in [
                            stage,
                            "type::retrospective"
                            if closed
                            else (
                                "workflow::ready" if phase == "repair" else "workflow::in-progress"
                            ),
                            "priority::high" if phase != "repair" else "priority::normal",
                        ]
                    ]
                },
            )
            if closed and record["state"] != "CLOSED":
                payload = self.api.graphql(
                    "mutation($input:WorkItemUpdateInput!){workItemUpdate(input:$input){"
                    "errors workItem{id state}}}",
                    {"input": {"id": record["id"], "stateEvent": "CLOSE"}},
                )["workItemUpdate"]
                if payload["errors"]:
                    raise RuntimeError(str(payload["errors"]))
        for key, title, source, gate in REQUIREMENTS:
            description = (
                f"Contract: {title}.\n\nImplementation/test: {URL}/-/blob/{SOURCE}/{source}"
                f"\n\nVerified baseline: {PIPELINE}."
            )
            if gate:
                description += (
                    f"\n\nEvidence field: `{gate}` in all ten approved v2 cases. "
                    f"Snapshot SHA256: `{SNAPSHOT_SHA256}`."
                )
            description += (
                "\n\nThis records the tested contract; it does not establish causality "
                "or independent clinical truth."
            )
            self.item(PROJECT_PATH, "requirement-" + key, title, "Requirement", description)
        for key, title, parent in [
            ("task-junit", "Validate complete JUnit and RAG test reporting", "test-reporting"),
            ("task-sbom", "Validate native security and SBOM ingestion", "security-reporting"),
            ("task-dashboard", "Verify existing-service telemetry dashboard", "monitoring"),
        ]:
            self.item(
                PROJECT_PATH,
                key,
                title,
                "Task",
                f"Acceptance: execute the checks in {self.records[parent]['webUrl']} "
                "and attach actual artifacts before closing.",
                hierarchyWidget={"parentId": self.records[parent]["id"]},
            )
        for case in cases:
            details = {
                k: case[k]
                for k in [
                    "case_id",
                    "question",
                    "cutoff_date",
                    "required_evidence_ids",
                    "critical_evidence_ids",
                    "reviewed_by",
                    "review_note",
                ]
            }
            description = (
                "Reviewed case, copied from the checksum-verified immutable snapshot.\n\n```json\n"
                + json.dumps(details, indent=2, default=str)
                + "\n```"
            )
            description += (
                "\n\nExpected facts and reviewed answer points remain in the frozen snapshot; "
                "no labels are generated or changed here."
                f"\n\nSnapshot SHA256: `{SNAPSHOT_SHA256}`."
                f"\n\nActual result: {URL}/-/jobs/17292303405/artifacts/file/evaluation/report.json"
                f"\n\nTracking issue: {self.records['test-reporting']['webUrl']}"
            )
            self.item(
                PROJECT_PATH, "test-" + case["case_id"], case["case_id"], "Test Case", description
            )
        boards = self.api.request("GET", project + "/boards")
        board = next(v for v in boards if v["name"] == "Development")
        lists = self.api.request("GET", project + f"/boards/{board['id']}/lists")
        present = {(v.get("label") or {}).get("id") for v in lists}
        for label in [
            "workflow::ready",
            "workflow::in-progress",
            "workflow::review",
            "workflow::blocked",
        ]:
            if labels[label]["id"] not in present:
                self.api.request(
                    "POST",
                    project + f"/boards/{board['id']}/lists",
                    {"label_id": labels[label]["id"]},
                )
        return {
            "records": self.records,
            "milestones": milestones,
            "labels": labels,
            "board_url": URL + f"/-/boards/{board['id']}",
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--output", type=Path, default=Path(".data/gitlab-workspace.json"))
    args = parser.parse_args()
    cases = reviewed_cases(args.snapshot)
    if not args.apply:
        print(
            json.dumps(
                {
                    "reviewed_cases": len(cases),
                    "requirements": len(REQUIREMENTS),
                    "issues": len(ITEMS),
                    "epics": len(EPICS),
                }
            )
        )
        return
    result = Workspace(GitLab()).apply(cases)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

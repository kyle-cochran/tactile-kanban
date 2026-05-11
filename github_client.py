from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

import requests


@dataclass
class StatusOption:
    id: str
    name: str


@dataclass
class SprintItem:
    item_id: str
    issue_number: int
    title: str
    assignees: list[str]
    status: str
    status_option_id: str
    sprint_id: str


@dataclass
class ProjectMeta:
    project_id: str
    status_field_id: str
    status_options: list[StatusOption]
    current_sprint_id: str
    current_sprint_title: str


_GQL_URL = "https://api.github.com/graphql"

_QUERY_PROJECT_META = """
query($org: String!, $number: Int!) {
  organization(login: $org) {
    projectV2(number: $number) {
      id
      title
      fields(first: 30) {
        nodes {
          ... on ProjectV2SingleSelectField {
            id
            name
            options { id name }
          }
          ... on ProjectV2IterationField {
            id
            name
            configuration {
              iterations { id title startDate duration }
            }
          }
        }
      }
    }
  }
}
"""

_QUERY_ITEMS = """
query($projectId: ID!, $cursor: String) {
  node(id: $projectId) {
    ... on ProjectV2 {
      items(first: 50, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          content {
            ... on Issue {
              number
              title
              assignees(first: 3) { nodes { login } }
            }
          }
          fieldValues(first: 15) {
            nodes {
              ... on ProjectV2ItemFieldSingleSelectValue {
                name
                optionId
                field { ... on ProjectV2SingleSelectField { id name } }
              }
              ... on ProjectV2ItemFieldIterationValue {
                iterationId
                title
                field { ... on ProjectV2IterationField { id name } }
              }
            }
          }
        }
      }
    }
  }
}
"""

_MUTATION_UPDATE_STATUS = """
mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $optionId: String!) {
  updateProjectV2ItemFieldValue(input: {
    projectId: $projectId
    itemId:    $itemId
    fieldId:   $fieldId
    value:     { singleSelectOptionId: $optionId }
  }) {
    projectV2Item { id }
  }
}
"""


class GitHubClient:
    def __init__(self, token: str, org: str, project_number: int, sprint_prefix: str = "Sprint"):
        self.org = org
        self.project_number = project_number
        self.sprint_prefix = sprint_prefix
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
        )

    def _gql(self, query: str, variables: dict) -> dict:
        resp = self.session.post(
            _GQL_URL, json={"query": query, "variables": variables}, timeout=15
        )
        resp.raise_for_status()
        body = resp.json()
        if "errors" in body:
            raise RuntimeError(f"GitHub GraphQL error: {body['errors']}")
        return body["data"]

    def get_project_meta(self, sprint_prefix: Optional[str] = None) -> ProjectMeta:
        prefix = sprint_prefix or self.sprint_prefix
        data = self._gql(
            _QUERY_PROJECT_META,
            {"org": self.org, "number": self.project_number},
        )
        project = data["organization"]["projectV2"]
        project_id: str = project["id"]

        status_field_id = ""
        status_options: list[StatusOption] = []
        current_sprint_id = ""
        current_sprint_title = ""

        for field in project["fields"]["nodes"]:
            if not field:
                continue
            name: str = field.get("name", "")

            # Status column — a single-select field named "Status"
            if name.lower() == "status" and "options" in field:
                status_field_id = field["id"]
                status_options = [
                    StatusOption(id=o["id"], name=o["name"])
                    for o in field["options"]
                ]

            # Iteration field — find current sprint
            if "configuration" in field:
                iterations = field["configuration"].get("iterations", [])
                sprint_id, sprint_title = _find_current_iteration(iterations, prefix)
                if sprint_id:
                    current_sprint_id = sprint_id
                    current_sprint_title = sprint_title

        if not status_field_id:
            raise RuntimeError(
                "Could not find a 'Status' single-select field in the project. "
                "Check the field name in your GitHub Project."
            )
        if not current_sprint_id:
            raise RuntimeError(
                f"Could not find a current iteration matching prefix '{prefix}'. "
                "Check SPRINT_PREFIX in your .env."
            )

        return ProjectMeta(
            project_id=project_id,
            status_field_id=status_field_id,
            status_options=status_options,
            current_sprint_id=current_sprint_id,
            current_sprint_title=current_sprint_title,
        )

    def get_sprint_items(self, project_id: str, sprint_id: str) -> list[SprintItem]:
        """Return all project items belonging to the given iteration."""
        items: list[SprintItem] = []
        cursor: Optional[str] = None

        while True:
            data = self._gql(
                _QUERY_ITEMS,
                {"projectId": project_id, "cursor": cursor},
            )
            page = data["node"]["items"]
            for node in page["nodes"]:
                if not node or not node.get("content"):
                    continue
                content = node["content"]
                if "number" not in content:
                    continue  # not an Issue (could be a draft or PR)

                item_status = ""
                item_option_id = ""
                item_sprint_id = ""

                for fv in node["fieldValues"]["nodes"]:
                    if not fv:
                        continue
                    if "optionId" in fv:
                        item_status = fv.get("name", "")
                        item_option_id = fv.get("optionId", "")
                    if "iterationId" in fv:
                        item_sprint_id = fv.get("iterationId", "")

                if item_sprint_id != sprint_id:
                    continue

                assignees = [a["login"] for a in content["assignees"]["nodes"]]
                items.append(
                    SprintItem(
                        item_id=node["id"],
                        issue_number=content["number"],
                        title=content["title"],
                        assignees=assignees,
                        status=item_status,
                        status_option_id=item_option_id,
                        sprint_id=item_sprint_id,
                    )
                )

            if not page["pageInfo"]["hasNextPage"]:
                break
            cursor = page["pageInfo"]["endCursor"]

        return items

    def update_item_status(
        self, project_id: str, item_id: str, field_id: str, option_id: str
    ) -> bool:
        try:
            self._gql(
                _MUTATION_UPDATE_STATUS,
                {
                    "projectId": project_id,
                    "itemId": item_id,
                    "fieldId": field_id,
                    "optionId": option_id,
                },
            )
            return True
        except Exception as exc:
            print(f"  [github] failed to update status: {exc}")
            return False


def _find_current_iteration(
    iterations: list[dict], prefix: str
) -> tuple[str, str]:
    """Pick the active sprint iteration by start date + duration."""
    today = date.today()
    best_id = ""
    best_title = ""
    best_start: Optional[date] = None

    for it in iterations:
        if not it.get("title", "").startswith(prefix):
            continue
        try:
            start = date.fromisoformat(it["startDate"])
        except (KeyError, ValueError):
            continue
        duration: int = it.get("duration", 14)
        end = start + timedelta(days=duration)

        if start <= today <= end:
            return it["id"], it["title"]

        # Track the most recent past sprint as fallback
        if start <= today and (best_start is None or start > best_start):
            best_id = it["id"]
            best_title = it["title"]
            best_start = start

    return best_id, best_title

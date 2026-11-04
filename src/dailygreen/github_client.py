"""GitHub API client with rate limit handling, retries, and test mock support."""

import os
import time
from typing import Any, Optional
import httpx
from dailygreen.security import redact_secrets


class GitHubAPIError(Exception):
    """Raised when GitHub API operations fail."""
    def __init__(self, message: str, status_code: Optional[int] = None, response_body: str = ""):
        redacted_msg = redact_secrets(message)
        super().__init__(redacted_msg)
        self.status_code = status_code
        self.response_body = redact_secrets(response_body)


class GitHubClient:
    """Production GitHub client using httpx with rate limiting and retry handling."""

    BASE_URL = "https://api.github.com"

    def __init__(self, token: Optional[str] = None, max_retries: int = 3):
        self.token = token or os.getenv("GITHUB_TOKEN", "").strip()
        self.max_retries = max_retries

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "DailyGreen-Maintenance-Bot/0.1.0",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict[str, Any]] = None,
        json_data: Optional[dict[str, Any]] = None,
    ) -> Any:
        url = f"{self.BASE_URL}{endpoint}"
        retries = 0

        while True:
            try:
                with httpx.Client(timeout=30.0) as client:
                    response = client.request(
                        method=method,
                        url=url,
                        headers=self._headers(),
                        params=params,
                        json=json_data,
                    )

                    # Check for rate limit
                    if response.status_code == 403 and "rate limit" in response.text.lower():
                        retry_after = int(response.headers.get("Retry-After", "5"))
                        if retries < self.max_retries:
                            retries += 1
                            time.sleep(retry_after)
                            continue
                        raise GitHubAPIError("GitHub API rate limit exceeded", status_code=403, response_body=response.text)

                    # Check for transient server errors
                    if response.status_code in (500, 502, 503, 504):
                        if retries < self.max_retries:
                            retries += 1
                            time.sleep(2 ** retries)
                            continue
                        raise GitHubAPIError(
                            f"GitHub server error HTTP {response.status_code}",
                            status_code=response.status_code,
                            response_body=response.text,
                        )

                    if response.status_code == 404:
                        return None

                    if not (200 <= response.status_code < 300):
                        raise GitHubAPIError(
                            f"GitHub API error HTTP {response.status_code}: {response.text}",
                            status_code=response.status_code,
                            response_body=response.text,
                        )

                    if response.status_code == 204:
                        return True

                    return response.json()
            except httpx.RequestError as e:
                if retries < self.max_retries:
                    retries += 1
                    time.sleep(2 ** retries)
                    continue
                raise GitHubAPIError(f"Network error communicating with GitHub: {e}") from e

    def get_authenticated_user(self) -> Optional[dict[str, Any]]:
        """Fetch the authenticated user profile (GET /user)."""
        return self._request("GET", "/user")

    def get_rate_limit(self) -> Optional[dict[str, Any]]:
        """Fetch current rate limit status (GET /rate_limit)."""
        return self._request("GET", "/rate_limit")

    def get_repository(self, repo: str) -> Optional[dict[str, Any]]:
        return self._request("GET", f"/repos/{repo}")

    def get_labeled_issues(self, repo: str, label: str = "dailygreen") -> list[dict[str, Any]]:
        res = self._request("GET", f"/repos/{repo}/issues", params={"labels": label, "state": "open"})
        if not res or not isinstance(res, list):
            return []
        # Exclude Pull Requests returned in the issues API
        return [item for item in res if "pull_request" not in item]

    def branch_exists(self, repo: str, branch: str) -> bool:
        res = self._request("GET", f"/repos/{repo}/branches/{branch}")
        return res is not None

    def get_branch_ref(self, repo: str, branch: str) -> Optional[str]:
        res = self._request("GET", f"/repos/{repo}/git/ref/heads/{branch}")
        if res and isinstance(res, dict):
            return res.get("object", {}).get("sha")
        return None

    def get_pull_requests(
        self,
        repo: str,
        state: str = "open",
        head_branch: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        params = {"state": state}
        if head_branch:
            # GitHub expects head in owner:branch format or branch
            params["head"] = head_branch
        res = self._request("GET", f"/repos/{repo}/pulls", params=params)
        if not res or not isinstance(res, list):
            return []
        return res

    def get_open_pull_requests(self, repo: str, head_branch: Optional[str] = None) -> list[dict[str, Any]]:
        return self.get_pull_requests(repo, state="open", head_branch=head_branch)

    def create_branch(self, repo: str, branch: str, sha: str) -> dict[str, Any]:
        payload = {"ref": f"refs/heads/{branch}", "sha": sha}
        res = self._request("POST", f"/repos/{repo}/git/refs", json_data=payload)
        return res or {}

    def create_blob(self, repo: str, content: str) -> str:
        payload = {"content": content, "encoding": "utf-8"}
        res = self._request("POST", f"/repos/{repo}/git/blobs", json_data=payload)
        return (res or {}).get("sha", "")

    def create_tree(self, repo: str, base_tree: str, tree: list[dict[str, Any]]) -> str:
        payload = {"base_tree": base_tree, "tree": tree}
        res = self._request("POST", f"/repos/{repo}/git/trees", json_data=payload)
        return (res or {}).get("sha", "")

    def create_commit(self, repo: str, message: str, tree: str, parents: list[str]) -> str:
        payload = {"message": message, "tree": tree, "parents": parents}
        res = self._request("POST", f"/repos/{repo}/git/commits", json_data=payload)
        return (res or {}).get("sha", "")

    def update_branch_ref(self, repo: str, branch: str, sha: str, force: bool = False) -> dict[str, Any]:
        payload = {"sha": sha, "force": force}
        res = self._request("PATCH", f"/repos/{repo}/git/refs/heads/{branch}", json_data=payload)
        return res or {}

    def delete_branch(self, repo: str, branch: str) -> bool:
        res = self._request("DELETE", f"/repos/{repo}/git/refs/heads/{branch}")
        return res is not None

    def create_pull_request(
        self,
        repo: str,
        title: str,
        body: str,
        head: str,
        base: str = "main",
    ) -> dict[str, Any]:
        payload = {
            "title": title,
            "body": body,
            "head": head,
            "base": base,
        }
        try:
            res = self._request("POST", f"/repos/{repo}/pulls", json_data=payload)
            return res or {}
        except GitHubAPIError as e:
            # Handle idempotent recovery: PR was already created remotely
            if e.status_code == 422 and "already exists" in (e.response_body or "").lower():
                existing_prs = self.get_pull_requests(repo, state="all", head_branch=head)
                if existing_prs:
                    return existing_prs[0]
            raise
        except Exception:
            # Check if PR actually succeeded remotely despite network timeout
            try:
                existing_prs = self.get_pull_requests(repo, state="all", head_branch=head)
                if existing_prs:
                    return existing_prs[0]
            except Exception:
                pass
            raise


class MockGitHubClient(GitHubClient):
    """In-memory mock GitHub client for unit and integration testing."""

    def __init__(
        self,
        repositories: Optional[dict[str, dict[str, Any]]] = None,
        labeled_issues: Optional[dict[str, list[dict[str, Any]]]] = None,
        existing_branches: Optional[dict[str, list[str]]] = None,
        open_prs: Optional[dict[str, list[dict[str, Any]]]] = None,
        should_fail: bool = False,
        rate_limit_error: bool = False,
        simulate_timeout_on_pr_create: bool = False,
        simulate_pr_already_exists: bool = False,
        pull_requests: Optional[dict[str, list[dict[str, Any]]]] = None,
    ):
        super().__init__(token="mock-token")
        self.repositories = repositories
        self.labeled_issues = labeled_issues or {}
        self.existing_branches = existing_branches or {}
        self.open_prs = open_prs or {}
        self.pull_requests = pull_requests or {}
        if not self.pull_requests and self.open_prs:
            self.pull_requests = {repo: list(prs) for repo, prs in self.open_prs.items()}
        elif not self.open_prs and self.pull_requests:
            self.open_prs = {
                repo: [
                    p for p in prs
                    if p.get("state", "open") == "open" and not p.get("merged", False) and p.get("merged_at") is None
                ]
                for repo, prs in self.pull_requests.items()
            }
        self.should_fail = should_fail
        self.rate_limit_error = rate_limit_error
        self.simulate_timeout_on_pr_create = simulate_timeout_on_pr_create
        self.simulate_pr_already_exists = simulate_pr_already_exists
        self.created_branches: list[dict[str, Any]] = []
        self.created_prs: list[dict[str, Any]] = []
        self.created_blobs: list[dict[str, Any]] = []
        self.created_trees: list[dict[str, Any]] = []
        self.created_commits: list[dict[str, Any]] = []
        self.updated_refs: list[dict[str, Any]] = []
        self.deleted_branches: list[dict[str, Any]] = []

    def get_authenticated_user(self) -> Optional[dict[str, Any]]:
        """Fetch the authenticated user profile in mock."""
        if self.should_fail:
            raise GitHubAPIError("Mock GitHub API error", status_code=500)
        return {"login": "mock-operator", "type": "User"}

    def get_rate_limit(self) -> Optional[dict[str, Any]]:
        """Fetch current rate limit status in mock."""
        if self.rate_limit_error:
            raise GitHubAPIError("GitHub API rate limit exceeded", status_code=403)
        if self.should_fail:
            raise GitHubAPIError("Mock GitHub API error", status_code=500)
        return {"rate": {"limit": 5000, "remaining": 4999, "reset": 1800000000}}

    def get_repository(self, repo: str) -> Optional[dict[str, Any]]:
        if self.rate_limit_error:
            raise GitHubAPIError("GitHub API rate limit exceeded", status_code=403)
        if self.should_fail:
            raise GitHubAPIError("Mock GitHub API error", status_code=500)
        if self.repositories is not None:
            return self.repositories.get(repo)
        return {"name": repo, "default_branch": "main"}

    def get_labeled_issues(self, repo: str, label: str = "dailygreen") -> list[dict[str, Any]]:
        if self.should_fail:
            raise GitHubAPIError("Mock GitHub API error", status_code=500)
        return self.labeled_issues.get(repo, [])

    def branch_exists(self, repo: str, branch: str) -> bool:
        branches = self.existing_branches.get(repo, [])
        return branch in branches

    def get_branch_ref(self, repo: str, branch: str) -> Optional[str]:
        return "mock_base_commit_sha_1234567890abcdef"

    def get_pull_requests(
        self,
        repo: str,
        state: str = "open",
        head_branch: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        if self.rate_limit_error:
            raise GitHubAPIError("GitHub API rate limit exceeded", status_code=403)
        if self.should_fail:
            raise GitHubAPIError("Mock GitHub API error", status_code=500)

        all_repo_prs = self.pull_requests.get(repo)
        if all_repo_prs is None:
            all_repo_prs = self.open_prs.get(repo, [])

        if state == "all":
            filtered = list(all_repo_prs)
        elif state == "open":
            filtered = [
                p for p in all_repo_prs
                if p.get("state", "open") == "open" and not p.get("merged", False) and p.get("merged_at") is None
            ]
        elif state == "closed":
            filtered = [
                p for p in all_repo_prs
                if p.get("state") == "closed" or p.get("merged", False) or p.get("merged_at") is not None
            ]
        else:
            filtered = [p for p in all_repo_prs if p.get("state", "open") == state]

        if head_branch:
            return [
                p for p in filtered
                if p.get("head", {}).get("ref") == head_branch or head_branch.endswith(p.get("head", {}).get("ref", ""))
            ]
        return filtered

    def get_open_pull_requests(self, repo: str, head_branch: Optional[str] = None) -> list[dict[str, Any]]:
        return self.get_pull_requests(repo, state="open", head_branch=head_branch)

    def create_branch(self, repo: str, branch: str, sha: str) -> dict[str, Any]:
        if self.should_fail:
            raise GitHubAPIError("Failed to create branch", status_code=500)
        record = {"repo": repo, "branch": branch, "sha": sha}
        self.created_branches.append(record)
        if repo not in self.existing_branches:
            self.existing_branches[repo] = []
        self.existing_branches[repo].append(branch)
        return {"ref": f"refs/heads/{branch}", "object": {"sha": sha}}

    def create_blob(self, repo: str, content: str) -> str:
        if self.should_fail:
            raise GitHubAPIError("Failed to create blob", status_code=500)
        blob_sha = f"blob_sha_{len(self.created_blobs) + 1}_{hash(content) & 0xffffffff:08x}"
        self.created_blobs.append({"repo": repo, "content": content, "sha": blob_sha})
        return blob_sha

    def create_tree(self, repo: str, base_tree: str, tree: list[dict[str, Any]]) -> str:
        if self.should_fail:
            raise GitHubAPIError("Failed to create tree", status_code=500)
        tree_sha = f"tree_sha_{len(self.created_trees) + 1}"
        self.created_trees.append({"repo": repo, "base_tree": base_tree, "tree": tree, "sha": tree_sha})
        return tree_sha

    def create_commit(self, repo: str, message: str, tree: str, parents: list[str]) -> str:
        if self.should_fail:
            raise GitHubAPIError("Failed to create commit", status_code=500)
        commit_sha = f"commit_sha_{len(self.created_commits) + 1}"
        self.created_commits.append({"repo": repo, "message": message, "tree": tree, "parents": parents, "sha": commit_sha})
        return commit_sha

    def update_branch_ref(self, repo: str, branch: str, sha: str, force: bool = False) -> dict[str, Any]:
        if self.should_fail:
            raise GitHubAPIError("Failed to update ref", status_code=500)
        record = {"repo": repo, "branch": branch, "sha": sha, "force": force}
        self.updated_refs.append(record)
        return {"ref": f"refs/heads/{branch}", "object": {"sha": sha}}

    def delete_branch(self, repo: str, branch: str) -> bool:
        if self.should_fail:
            raise GitHubAPIError("Failed to delete branch", status_code=500)
        self.deleted_branches.append({"repo": repo, "branch": branch})
        if repo in self.existing_branches and branch in self.existing_branches[repo]:
            self.existing_branches[repo].remove(branch)
        return True

    def create_pull_request(
        self,
        repo: str,
        title: str,
        body: str,
        head: str,
        base: str = "main",
    ) -> dict[str, Any]:
        if self.should_fail:
            raise GitHubAPIError("Failed to create pull request", status_code=500)

        # Check if simulate PR already exists
        if self.simulate_pr_already_exists:
            # If an existing PR is in open_prs, super().create_pull_request or recovery finds it
            raise GitHubAPIError(
                "Validation Failed: A pull request already exists",
                status_code=422,
                response_body='{"message":"Validation Failed","errors":[{"message":"A pull request already exists"}]}',
            )

        pr_number = len(self.created_prs) + 1
        record = {
            "repo": repo,
            "number": pr_number,
            "title": title,
            "body": body,
            "head": {"ref": head},
            "base": {"ref": base},
            "html_url": f"https://github.com/{repo}/pull/{pr_number}",
            "state": "open",
        }

        # Simulate timeout on PR create: PR was created on remote, but client received timeout
        if self.simulate_timeout_on_pr_create:
            # Store in open_prs and pull_requests so recovery can find it
            if repo not in self.open_prs:
                self.open_prs[repo] = []
            self.open_prs[repo].append(record)
            if repo not in self.pull_requests:
                self.pull_requests[repo] = []
            self.pull_requests[repo].append(record)
            # Try to recover by querying existing PRs
            existing = self.get_pull_requests(repo, state="all", head_branch=head)
            if existing:
                return existing[0]
            raise GitHubAPIError("Network timeout creating pull request", status_code=504)

        self.created_prs.append(record)
        if repo not in self.open_prs:
            self.open_prs[repo] = []
        self.open_prs[repo].append(record)
        if repo not in self.pull_requests:
            self.pull_requests[repo] = []
        self.pull_requests[repo].append(record)
        return record

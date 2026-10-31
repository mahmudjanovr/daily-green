import { RunReport } from '../types';

export function formatMarkdownSummary(report: RunReport): string {
  const statusIcon =
    report.status === 'task_completed' ||
    report.status === 'pull_request_created' ||
    report.status === 'dry_run_completed'
      ? '🟢'
      : report.status === 'no_task' || report.status === 'skipped'
      ? '⚪'
      : '🔴';

  const taskTitle = report.task?.title || 'None';
  const taskId = report.task?.id || 'N/A';
  const prLink = report.delivery?.pr_url || 'N/A';
  const branchName = report.delivery?.branch_name || 'N/A';
  const dryRunText = report.delivery?.is_dry_run
    ? 'YES (simulation only)'
    : 'NO (remote published)';

  return `# DailyGreen Run Summary ${statusIcon}

| Field | Value |
| :--- | :--- |
| **Run ID** | \`${report.run_id}\` |
| **Timestamp** | \`${report.timestamp}\` |
| **Repository** | \`${report.repo}\` |
| **Overall Status** | **\`${report.status.toUpperCase()}\`** |
| **Dry Run Mode** | ${dryRunText} |
| **Task ID** | \`${taskId}\` |
| **Task Title** | ${taskTitle} |
| **Branch** | \`${branchName}\` |
| **Pull Request** | ${prLink} |

### Details
${report.message}

### GitHub Contribution Policy Notice
- **Commit Contribution Eligibility**: GitHub counts commits towards the contribution graph only when they are merged into the repository's default branch (\`main\`) or \`gh-pages\`, and when the commit author's email matches a verified GitHub account email.
- **Pull Request Eligibility**: Opening a PR will count towards your contribution profile only if PR activity tracking is enabled in your GitHub profile settings.
- **Integrity Guarantee**: DailyGreen never commits empty changes, fabricates activity, or automatically merges pull requests.
`;
}

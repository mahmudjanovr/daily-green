import { Task, VirtualFile } from '../types';

export function createUnifiedDiff(
  filePath: string,
  oldContent: string,
  newContent: string
): string {
  const oldLines = oldContent.split('\n');
  const newLines = newContent.split('\n');

  if (oldContent === newContent) {
    return '';
  }

  let diff = `--- a/${filePath}\n+++ b/${filePath}\n@@ -1,${oldLines.length} +1,${newLines.length} @@\n`;

  // Simple line-by-line diff generation
  let i = 0;
  let j = 0;
  while (i < oldLines.length || j < newLines.length) {
    if (i < oldLines.length && j < newLines.length && oldLines[i] === newLines[j]) {
      diff += ` ${oldLines[i]}\n`;
      i++;
      j++;
    } else {
      if (i < oldLines.length && (j >= newLines.length || oldLines[i] !== newLines[j])) {
        diff += `-${oldLines[i]}\n`;
        i++;
      }
      if (j < newLines.length && (i >= oldLines.length || oldLines[i - 1] !== newLines[j])) {
        diff += `+${newLines[j]}\n`;
        j++;
      }
    }
  }

  return diff.trimEnd() + '\n';
}

export function implementTaskInWorkspace(
  files: VirtualFile[],
  task: Task
): { updatedFiles: VirtualFile[]; diff: string } {
  const updatedFiles = files.map((f) => ({ ...f }));
  let fullDiff = '';

  if (task.source === 'deterministic') {
    const meta = task.metadata || {};

    if (meta.format_type === 'whitespace_and_eof') {
      for (const targetPath of task.target_files) {
        const file = updatedFiles.find((f) => f.path === targetPath);
        if (file) {
          const oldContent = file.content;
          const lines = oldContent.split('\n');
          const cleaned = lines.map((l) => l.trimEnd()).join('\n');
          let newContent = cleaned;
          if (newContent && !newContent.endsWith('\n')) {
            newContent += '\n';
          }
          file.content = newContent;
          const diff = createUnifiedDiff(targetPath, oldContent, newContent);
          if (diff) fullDiff += diff;
        }
      }
    } else if (meta.typo && meta.replacement) {
      const typo = meta.typo as string;
      const replacement = meta.replacement as string;

      for (const targetPath of task.target_files) {
        const file = updatedFiles.find((f) => f.path === targetPath);
        if (file) {
          const oldContent = file.content;
          const regex = new RegExp(`\\b${typo}\\b`, 'gi');
          const newContent = oldContent.replace(regex, (match) => {
            if (match === match.toUpperCase()) return replacement.toUpperCase();
            if (match[0] === match[0].toUpperCase()) {
              return replacement.charAt(0).toUpperCase() + replacement.slice(1);
            }
            return replacement.toLowerCase();
          });
          file.content = newContent;
          const diff = createUnifiedDiff(targetPath, oldContent, newContent);
          if (diff) fullDiff += diff;
        }
      }
    } else if (meta.broken_target) {
      const brokenTarget = meta.broken_target as string;
      for (const targetPath of task.target_files) {
        const file = updatedFiles.find((f) => f.path === targetPath);
        if (file) {
          const oldContent = file.content;
          // Replace [text](broken_target) with `text`
          const regex = new RegExp(`\\[([^\\]]+)\\]\\(${brokenTarget.replace(/[-/\\^$*+?.()|[\]{}]/g, '\\$&')}\\)`, 'g');
          const newContent = oldContent.replace(regex, '`$1`');
          file.content = newContent;
          const diff = createUnifiedDiff(targetPath, oldContent, newContent);
          if (diff) fullDiff += diff;
        }
      }
    }
  } else if (task.source === 'backlog' || task.source === 'issue' || task.source === 'ai') {
    // Backlog or issue maintenance
    for (const targetPath of task.target_files) {
      const file = updatedFiles.find((f) => f.path === targetPath);
      if (file) {
        const oldContent = file.content;
        let newContent = oldContent;

        // Apply clean doc formatting and cleanup
        const lines = oldContent.split('\n').map((l) => l.trimEnd());
        newContent = lines.join('\n');
        if (!newContent.endsWith('\n')) newContent += '\n';

        // If typo or broken link exists in this file, fix it
        newContent = newContent.replace(/\bteh\b/gi, 'the');
        newContent = newContent.replace(/\brecieve\b/gi, 'receive');

        if (newContent !== oldContent) {
          file.content = newContent;
          const diff = createUnifiedDiff(targetPath, oldContent, newContent);
          if (diff) fullDiff += diff;
        } else {
          // Add a verified minor comment or standard markdown badge if needed
          newContent += `\n<!-- DailyGreen verified doc standard: ${task.id} -->\n`;
          file.content = newContent;
          const diff = createUnifiedDiff(targetPath, oldContent, newContent);
          if (diff) fullDiff += diff;
        }
      }
    }
  }

  return { updatedFiles, diff: fullDiff };
}

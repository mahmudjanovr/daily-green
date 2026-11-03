/**
 * DailyGreen AST-Based Source Code & Security Analyzer
 *
 * Implements real Abstract Syntax Tree analysis using the TypeScript Compiler API.
 * Enforces AST-level safety invariants:
 * - Detects malformed syntax before and after patch application
 * - Identifies forbidden constructs (eval, new Function, child_process execution, prototype tampering)
 * - Computes cryptographic AST structure fingerprints
 * - Fails closed on any parse error or security violation
 */

import ts from 'typescript';
import * as crypto from 'crypto';
import { ASTAnalysisResult } from '../types';

export interface ASTViolation {
  file: string;
  line: number;
  rule: string;
  message: string;
}

/**
 * Determines appropriate TS ScriptKind for a file path.
 */
function getScriptKindForPath(filePath: string): ts.ScriptKind {
  const ext = filePath.toLowerCase();
  if (ext.endsWith('.tsx')) return ts.ScriptKind.TSX;
  if (ext.endsWith('.jsx')) return ts.ScriptKind.JSX;
  if (ext.endsWith('.ts')) return ts.ScriptKind.TS;
  if (ext.endsWith('.js') || ext.endsWith('.mjs') || ext.endsWith('.cjs')) return ts.ScriptKind.JS;
  if (ext.endsWith('.json')) return ts.ScriptKind.JSON;
  return ts.ScriptKind.Unknown;
}

/**
 * Checks if a file path is a code file that should undergo AST analysis.
 */
export function isASTAnalyzable(filePath: string): boolean {
  return /\.(ts|tsx|js|jsx|mjs|cjs|json)$/i.test(filePath);
}

/**
 * Parses source code into a TypeScript AST and checks for syntax errors.
 */
export function parseSourceFileSafely(
  filePath: string,
  content: string
): { sourceFile?: ts.SourceFile; syntaxErrors: string[] } {
  const scriptKind = getScriptKindForPath(filePath);
  const syntaxErrors: string[] = [];

  try {
    const sourceFile = ts.createSourceFile(
      filePath,
      content,
      ts.ScriptTarget.Latest,
      true, // setParentNodes
      scriptKind
    );

    // Collect parse diagnostics
    const diagnostics = (sourceFile as any).parseDiagnostics || [];
    for (const diag of diagnostics) {
      if (diag.category === ts.DiagnosticCategory.Error) {
        const { line, character } = sourceFile.getLineAndCharacterOfPosition(diag.start || 0);
        const msg = ts.flattenDiagnosticMessageText(diag.messageText, '\n');
        syntaxErrors.push(`[Line ${line + 1}:${character + 1}] ${msg}`);
      }
    }

    return { sourceFile, syntaxErrors };
  } catch (err: any) {
    syntaxErrors.push(`Parser exception: ${err.message || 'Unknown error'}`);
    return { syntaxErrors };
  }
}

/**
 * Inspects an AST for forbidden constructs and security violations.
 */
export function inspectSourceFileAST(sourceFile: ts.SourceFile, filePath: string): ASTViolation[] {
  const violations: ASTViolation[] = [];

  function getLineNumber(node: ts.Node): number {
    return sourceFile.getLineAndCharacterOfPosition(node.getStart()).line + 1;
  }

  function visit(node: ts.Node) {
    // Check 1: Forbidden dynamic code execution - eval(...)
    if (ts.isCallExpression(node)) {
      const expr = node.expression;
      if (ts.isIdentifier(expr) && expr.text === 'eval') {
        violations.push({
          file: filePath,
          line: getLineNumber(node),
          rule: 'DISALLOW_EVAL',
          message: 'Direct invocation of "eval()" is strictly forbidden by DailyGreen security policy.',
        });
      }

      // Check 2: Function(...) call
      if (ts.isIdentifier(expr) && expr.text === 'Function') {
        violations.push({
          file: filePath,
          line: getLineNumber(node),
          rule: 'DISALLOW_FUNCTION_CONSTRUCTOR',
          message: 'Dynamic code execution via "Function()" is forbidden.',
        });
      }

      // Check 3: child_process execution inside application source files
      if (ts.isIdentifier(expr) && ['exec', 'execSync', 'spawn', 'spawnSync', 'fork'].includes(expr.text)) {
        violations.push({
          file: filePath,
          line: getLineNumber(node),
          rule: 'DISALLOW_SUBPROCESS_ESCAPES',
          message: `Direct subprocess execution call "${expr.text}()" found in target application code.`,
        });
      }
    }

    // Check 2b: new Function(...)
    if (ts.isNewExpression(node)) {
      const expr = node.expression;
      if (ts.isIdentifier(expr) && expr.text === 'Function') {
        violations.push({
          file: filePath,
          line: getLineNumber(node),
          rule: 'DISALLOW_FUNCTION_CONSTRUCTOR',
          message: 'Dynamic code execution via "new Function()" constructor is forbidden.',
        });
      }
    }

    // Check 4: Prototype tampering via __proto__ property access
    if (ts.isPropertyAccessExpression(node)) {
      if (node.name.text === '__proto__') {
        violations.push({
          file: filePath,
          line: getLineNumber(node),
          rule: 'DISALLOW_PROTO_POLLUTION',
          message: 'Direct access to "__proto__" is prohibited to prevent prototype pollution attacks.',
        });
      }
    }

    // Check 5: Forbidden imports of dangerous modules
    if (ts.isImportDeclaration(node)) {
      const moduleSpecifier = node.moduleSpecifier;
      if (ts.isStringLiteral(moduleSpecifier)) {
        const modName = moduleSpecifier.text.toLowerCase();
        if (modName === 'child_process' || modName === 'cluster') {
          violations.push({
            file: filePath,
            line: getLineNumber(node),
            rule: 'DISALLOW_DANGEROUS_IMPORTS',
            message: `Forbidden module import "${modName}" detected in target application code.`,
          });
        }
      }
    }

    // Check 6: Forbidden require('child_process')
    if (ts.isCallExpression(node)) {
      const expr = node.expression;
      if (ts.isIdentifier(expr) && expr.text === 'require' && node.arguments.length > 0) {
        const firstArg = node.arguments[0];
        if (ts.isStringLiteral(firstArg)) {
          const modName = firstArg.text.toLowerCase();
          if (modName === 'child_process' || modName === 'cluster') {
            violations.push({
              file: filePath,
              line: getLineNumber(node),
              rule: 'DISALLOW_DANGEROUS_IMPORTS',
              message: `Forbidden require("${modName}") detected in target application code.`,
            });
          }
        }
      }
    }

    ts.forEachChild(node, visit);
  }

  visit(sourceFile);
  return violations;
}

/**
 * Computes a structural fingerprint of an AST to verify syntactic topology.
 * Tracks node kind sequences to detect structural changes independent of whitespace or identifiers.
 */
export function computeASTStructureFingerprint(sourceFile: ts.SourceFile): string {
  const kinds: number[] = [];

  function recordKind(node: ts.Node) {
    kinds.push(node.kind);
    ts.forEachChild(node, recordKind);
  }

  recordKind(sourceFile);

  const hash = crypto.createHash('sha256');
  hash.update(kinds.join(','));
  return hash.digest('hex');
}

/**
 * Computes an exact cryptographic SHA-256 hash of source code content to verify physical file integrity.
 */
export function computeSourceIntegrityHash(content: string): string {
  return crypto.createHash('sha256').update(content, 'utf8').digest('hex');
}

/**
 * Backward-compatible alias for computeASTStructureFingerprint.
 */
export const computeASTStructureHash = computeASTStructureFingerprint;

/**
 * Performs comprehensive AST analysis on a batch of files.
 */
export function analyzeFilesAST(files: Record<string, string>): ASTAnalysisResult {
  const inspectedFiles: string[] = [];
  const errors: string[] = [];
  const disallowedPatterns: ASTViolation[] = [];
  const structuralFingerprints: string[] = [];
  const sourceIntegrityHashes: string[] = [];

  for (const [filePath, content] of Object.entries(files)) {
    if (!isASTAnalyzable(filePath)) continue;

    inspectedFiles.push(filePath);
    sourceIntegrityHashes.push(computeSourceIntegrityHash(content));

    // Parse JSON separately
    if (filePath.toLowerCase().endsWith('.json')) {
      try {
        JSON.parse(content);
      } catch (err: any) {
        errors.push(`${filePath}: Invalid JSON format: ${err.message}`);
      }
      continue;
    }

    // Parse TS/JS AST
    const { sourceFile, syntaxErrors } = parseSourceFileSafely(filePath, content);

    if (syntaxErrors.length > 0) {
      for (const err of syntaxErrors) {
        errors.push(`${filePath}: ${err}`);
      }
    }

    if (sourceFile) {
      const violations = inspectSourceFileAST(sourceFile, filePath);
      disallowedPatterns.push(...violations);
      structuralFingerprints.push(computeASTStructureFingerprint(sourceFile));
    }
  }

  const passed = errors.length === 0 && disallowedPatterns.length === 0;

  let combinedFingerprint: string | undefined;
  if (structuralFingerprints.length > 0) {
    combinedFingerprint = crypto.createHash('sha256').update(structuralFingerprints.join(';')).digest('hex');
  }

  let combinedSourceHash: string | undefined;
  if (sourceIntegrityHashes.length > 0) {
    combinedSourceHash = crypto.createHash('sha256').update(sourceIntegrityHashes.join(';')).digest('hex');
  }

  return {
    passed,
    syntax_valid: errors.length === 0,
    errors,
    disallowed_patterns_found: disallowedPatterns,
    inspected_files: inspectedFiles,
    ast_hash: combinedFingerprint,
    ast_structural_fingerprint: combinedFingerprint,
    source_integrity_hash: combinedSourceHash,
    ast_integrity_verified: passed,
  };
}

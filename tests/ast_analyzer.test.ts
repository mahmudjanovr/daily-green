import { test, describe } from 'node:test';
import assert from 'node:assert';
import {
  analyzeFilesAST,
  parseSourceFileSafely,
  inspectSourceFileAST,
  computeASTStructureHash,
} from '../src/services/astAnalyzer';
import { evaluateQualityGate } from '../src/services/qualityGate';
import { DEFAULT_CONFIG, DEFAULT_POLICY } from '../src/data/defaultConfig';
import { Task } from '../src/types';

describe('Phase 4: AST-Based Source Code & Security Analyzer', () => {
  test('parseSourceFileSafely parses valid TypeScript/TSX without syntax errors', () => {
    const validTs = `
      interface UserConfig {
        username: string;
        active: boolean;
      }
      export function greet(config: UserConfig): string {
        return 'Hello ' + config.username;
      }
    `;
    const res = parseSourceFileSafely('src/utils.ts', validTs);
    assert.strictEqual(res.syntaxErrors.length, 0);
    assert.ok(res.sourceFile);
  });

  test('parseSourceFileSafely captures syntax errors cleanly with line numbers', () => {
    const invalidTs = `
      const a = ; // syntax error
      function broken( {
    `;
    const res = parseSourceFileSafely('src/broken.ts', invalidTs);
    assert.strictEqual(res.syntaxErrors.length > 0, true);
    assert.ok(res.syntaxErrors[0].includes('Line'));
  });

  test('inspectSourceFileAST flags forbidden eval() invocation', () => {
    const badCode = `
      const expr = "2 + 2";
      const result = eval(expr);
    `;
    const { sourceFile } = parseSourceFileSafely('src/eval.ts', badCode);
    assert.ok(sourceFile);
    const violations = inspectSourceFileAST(sourceFile, 'src/eval.ts');

    assert.strictEqual(violations.length >= 1, true);
    assert.strictEqual(violations.some((v) => v.rule === 'DISALLOW_EVAL'), true);
  });

  test('inspectSourceFileAST flags forbidden Function constructor', () => {
    const badCode = `
      const dynamicFn = new Function("a", "b", "return a + b;");
    `;
    const { sourceFile } = parseSourceFileSafely('src/func.ts', badCode);
    assert.ok(sourceFile);
    const violations = inspectSourceFileAST(sourceFile, 'src/func.ts');

    assert.strictEqual(violations.length >= 1, true);
    assert.strictEqual(violations.some((v) => v.rule === 'DISALLOW_FUNCTION_CONSTRUCTOR'), true);
  });

  test('inspectSourceFileAST flags child_process execution escapes', () => {
    const badCode = `
      import { exec } from 'child_process';
      exec('rm -rf /tmp');
    `;
    const { sourceFile } = parseSourceFileSafely('src/escape.ts', badCode);
    assert.ok(sourceFile);
    const violations = inspectSourceFileAST(sourceFile, 'src/escape.ts');

    assert.strictEqual(violations.length >= 1, true);
    assert.strictEqual(violations.some((v) => v.rule === 'DISALLOW_DANGEROUS_IMPORTS'), true);
  });

  test('inspectSourceFileAST flags prototype pollution via __proto__', () => {
    const badCode = `
      const target = {};
      target.__proto__.admin = true;
    `;
    const { sourceFile } = parseSourceFileSafely('src/proto.ts', badCode);
    assert.ok(sourceFile);
    const violations = inspectSourceFileAST(sourceFile, 'src/proto.ts');

    assert.strictEqual(violations.length >= 1, true);
    assert.strictEqual(violations.some((v) => v.rule === 'DISALLOW_PROTO_POLLUTION'), true);
  });

  test('computeASTStructureHash produces deterministic fingerprint for equivalent structures', () => {
    const codeA = `function add(x: number, y: number) { return x + y; }`;
    const codeB = `function sum(a: number, b: number) { return a + b; }`;

    const parsedA = parseSourceFileSafely('a.ts', codeA);
    const parsedB = parseSourceFileSafely('b.ts', codeB);

    assert.ok(parsedA.sourceFile && parsedB.sourceFile);
    const hashA = computeASTStructureHash(parsedA.sourceFile);
    const hashB = computeASTStructureHash(parsedB.sourceFile);

    // Identical AST node syntax structures yield identical structure fingerprints
    assert.strictEqual(hashA, hashB);
    assert.strictEqual(typeof hashA, 'string');
    assert.strictEqual(hashA.length, 64);
  });

  test('distinguishes AST structural fingerprint from cryptographic source integrity hash', () => {
    const codeA = `function calculate(total: number) { return total * 2; }`;
    const codeB = `function compute(val: number) { return val * 2; }`; // Same AST shape, different identifiers

    const parsedA = parseSourceFileSafely('a.ts', codeA);
    const parsedB = parseSourceFileSafely('b.ts', codeB);

    assert.ok(parsedA.sourceFile && parsedB.sourceFile);

    const structuralA = computeASTStructureHash(parsedA.sourceFile);
    const structuralB = computeASTStructureHash(parsedB.sourceFile);

    // Structural fingerprints must be identical because node kinds and AST grammar topology match
    assert.strictEqual(structuralA, structuralB);

    // Cryptographic source integrity hashes must strictly differ because bytes/identifiers differ
    const resA = analyzeFilesAST({ 'code.ts': codeA });
    const resB = analyzeFilesAST({ 'code.ts': codeB });

    assert.strictEqual(resA.ast_structural_fingerprint, resB.ast_structural_fingerprint);
    assert.notStrictEqual(resA.source_integrity_hash, resB.source_integrity_hash);
    assert.ok(resA.source_integrity_hash && resB.source_integrity_hash);
    assert.strictEqual(resA.source_integrity_hash.length, 64);
    assert.strictEqual(resB.source_integrity_hash.length, 64);
  });

  test('analyzeFilesAST verifies batch of clean files successfully', () => {
    const files = {
      'src/math.ts': `export const add = (a: number, b: number): number => a + b;`,
      'docs/guide.md': `# Guide\nDocumentation content.`,
      'package.json': `{"name": "test", "version": "1.0.0"}`,
    };

    const res = analyzeFilesAST(files);
    assert.strictEqual(res.passed, true);
    assert.strictEqual(res.syntax_valid, true);
    assert.strictEqual(res.errors.length, 0);
    assert.strictEqual(res.disallowed_patterns_found.length, 0);
    assert.ok(res.ast_hash);
  });

  test('evaluateQualityGate fails closed when AST security policy is violated', async () => {
    const maliciousCode = `
      export function runOperation() {
        eval("process.exit(1)");
      }
    `;

    const sampleTask: Task = {
      id: 'task-ast-test',
      repo: 'example-org/astro-portfolio',
      title: 'Fix formatting',
      description: 'Test',
      rationale: 'Test',
      acceptance_criteria: ['Passes'],
      risk_level: 'low',
      validation_strategy: 'ast',
      source: 'deterministic',
      target_files: ['README.md'],
      created_at: new Date().toISOString(),
    };

    const qgResult = await evaluateQualityGate(
      sampleTask,
      '+ malicious line',
      { 'src/component.ts': maliciousCode },
      DEFAULT_CONFIG.repos[0],
      DEFAULT_POLICY
    );

    assert.strictEqual(qgResult.passed, false);
    assert.ok(qgResult.reason.includes('AST security gate failed'));
    assert.strictEqual(qgResult.ast_result?.passed, false);
    assert.strictEqual(qgResult.ast_result?.disallowed_patterns_found.some((p) => p.rule === 'DISALLOW_EVAL'), true);
  });
});

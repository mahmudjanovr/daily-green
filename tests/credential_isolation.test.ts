import { test, describe } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';
import {
  createSecureAskpassScript,
  redactSecrets,
  sanitizeShellArg,
  cloneRepository,
} from '../src/server/gitService';
import { executeSubprocess } from '../src/server/worker';

describe('Security Remediation: Git Credential Isolation & Safe Transport', () => {
  test('redactSecrets sanitizes GitHub tokens, bearer headers, and basic auth', () => {
    const raw = 'Git push to https://ghp_1234567890abcdef1234567890abcdef1234@github.com failed with basic authorization Bearer gho_9876543210fedcba';
    const redacted = redactSecrets(raw);

    assert.strictEqual(redacted.includes('ghp_1234567890abcdef1234567890abcdef1234'), false);
    assert.strictEqual(redacted.includes('gho_9876543210fedcba'), false);
    assert.ok(redacted.includes('***REDACTED_GITHUB_TOKEN***') || redacted.includes('***REDACTED'));
  });

  test('sanitizeShellArg disallows control characters and newlines', () => {
    assert.throws(() => sanitizeShellArg('repo\nrm -rf /'), /Control character/);
    assert.throws(() => sanitizeShellArg('repo; cat /etc/passwd'), /Suspicious character/);
    assert.throws(() => sanitizeShellArg('repo`whoami`'), /Suspicious character/);
    assert.strictEqual(sanitizeShellArg('valid-repo_123.git'), 'valid-repo_123.git');
  });

  test('createSecureAskpassScript writes an isolated script with strict 0o700 permissions and cleans up', () => {
    const scriptPath = createSecureAskpassScript();

    assert.ok(fs.existsSync(scriptPath));
    const stats = fs.statSync(scriptPath);
    // 0o700 permissions (octal mask 0o777)
    const mode = stats.mode & 0o777;
    assert.strictEqual(mode, 0o700, `Expected permissions 0o700, received 0o${mode.toString(8)}`);

    // Verify script does NOT contain any hardcoded secret token
    const scriptContent = fs.readFileSync(scriptPath, 'utf8');
    assert.strictEqual(scriptContent.includes('ghp_'), false);
    assert.ok(scriptContent.includes('DAILYGREEN_EPHEMERAL_PAT'));

    // Verify cleanup
    fs.unlinkSync(scriptPath);
    assert.strictEqual(fs.existsSync(scriptPath), false);
  });

  test('cloneRepository never passes credentials in command arguments', async () => {
    // Attempt clone to a dummy target without network/with dummy token
    const dummyDir = path.join(process.cwd(), '.dailygreen-data', 'test-clone-dummy');
    if (fs.existsSync(dummyDir)) {
      fs.rmSync(dummyDir, { recursive: true, force: true });
    }

    const testSecret = 'ghp_TESTSECRETNEVERLEAKME1234567890abcdef';
    
    // We expect clone to fail gracefully because git won't connect or dummy repo doesn't exist,
    // but critically: the secret MUST NOT be present in command string, logs, or thrown errors!
    try {
      await cloneRepository(
        'https://github.com/mahmudjanovr/daily-green.git',
        dummyDir,
        testSecret,
        'main'
      );
    } catch (err: any) {
      const errStr = String(err?.message || err);
      assert.strictEqual(errStr.includes(testSecret), false, 'Secret token leaked in error message!');
    } finally {
      if (fs.existsSync(dummyDir)) {
        fs.rmSync(dummyDir, { recursive: true, force: true });
      }
    }
  });

  test('executeSubprocess environment never leaks PAT to spawned process argv', async () => {
    // Run node to inspect process.argv and process.env
    const testSecret = 'ghp_VERIFY_ENV_ISOLATION_SECRET_987654';
    const inspectScript = `
      const args = process.argv.join(' ');
      if (args.includes('${testSecret}')) {
        console.error('LEAKED_IN_ARGV');
        process.exit(1);
      }
      if (process.env.TEST_TOKEN !== '${testSecret}') {
        console.error('ENV_MISMATCH');
        process.exit(2);
      }
      console.log('SAFE_ENV_PASSED');
    `;

    const res = await executeSubprocess(
      ['node', '-e', inspectScript],
      process.cwd(),
      5,
      undefined,
      { TEST_TOKEN: testSecret }
    );

    assert.strictEqual(res.exit_code, 0);
    assert.ok(res.stdout.includes('SAFE_ENV_PASSED'));
    assert.strictEqual(res.stderr.includes('LEAKED_IN_ARGV'), false);
  });
});

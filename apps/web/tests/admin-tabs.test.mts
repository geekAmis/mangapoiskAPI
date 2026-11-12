import assert from 'node:assert/strict';
import test from 'node:test';
import { ADMIN_TABS, adminTabDefinition, parseAdminTab } from '../src/pages/admin/tabs.ts';

const EXPECTED_TABS = [
  'overview',
  'servers',
  'deploy',
  'crawler',
  'media',
  'ads',
  'comments',
  'integrations',
  'audit',
  'terminal',
];

test('admin tab map is complete and unique', () => {
  assert.deepEqual(
    ADMIN_TABS.map((tab) => tab.id),
    EXPECTED_TABS,
  );
  assert.equal(new Set(ADMIN_TABS.map((tab) => tab.id)).size, EXPECTED_TABS.length);
  for (const tab of ADMIN_TABS) {
    assert.ok(tab.label.length > 0);
    assert.ok(tab.description.length > 0);
  }
});

test('deep link parser accepts every tab and falls back to overview', () => {
  for (const id of EXPECTED_TABS) {
    assert.equal(parseAdminTab(id), id);
  }
  assert.equal(parseAdminTab(null), 'overview');
  assert.equal(parseAdminTab(''), 'overview');
  assert.equal(parseAdminTab('nope'), 'overview');
});

test('tab definition resolves to the active tab', () => {
  assert.equal(adminTabDefinition('terminal').id, 'terminal');
  assert.equal(adminTabDefinition('servers').label, 'Серверы');
  assert.equal(adminTabDefinition('integrations').label, 'Интеграции');
});

// Evaluate the shipped rule in a polkit-shaped sandbox; no authorization changes.
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const source = fs.readFileSync(process.argv[2], 'utf8');
const rules = [], admins = [];
const Result = {YES:'yes', NO:'no', AUTH_ADMIN:'auth_admin', NOT_HANDLED:undefined};
// Conservative syntax guard plus runtime execution. Full polkit engine is image-only.
assert(!/\b(const|let|class|Set|Map)\b|=>|`/.test(source.replace(/\/\/[^\n]*/g,'')));
vm.runInNewContext(source, {polkit:{Result, addRule:f=>rules.push(f), addAdminRule:f=>admins.push(f)}});
const actions = ['app-install','runtime-install','app-update','runtime-update',
 'app-downgrade','runtime-downgrade','update-remote','modify-repo','install-bundle',
 'runtime-uninstall','app-uninstall','configure-remote','configure',
 'override-parental-controls','override-parental-controls-update','future-mutation','DeployAppstream'];
for (const wheel of [false,true]) for (const local of [false,true]) for (const active of [false,true]) {
 const subject={local,active,isInGroup:group=>wheel && group==='wheel'};
 for (const suffix of [...actions,'appstream-update','metadata-update']) {
  const action={id:'org.freedesktop.Flatpak.'+suffix};
  const metadata=['appstream-update','metadata-update'].includes(suffix);
  assert.equal(rules[0](action,subject), metadata && local && active ? Result.YES : wheel ? Result.AUTH_ADMIN : Result.NO);
  assert.equal(JSON.stringify(admins[0](action,subject)), '["unix-group:wheel"]');
 }
 assert.equal(rules[0]({id:'org.freedesktop.login1.reboot'},subject),undefined);
 assert.equal(admins[0]({id:'org.freedesktop.login1.reboot'},subject),undefined);
}
console.log('Flatpak policy decisions passed');

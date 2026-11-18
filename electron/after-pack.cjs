'use strict';

const {execFileSync} = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

exports.default = async context => {
  if (context.electronPlatformName !== 'darwin') return;
  const bundles = fs.readdirSync(context.appOutDir)
    .filter(name => name.endsWith('.app'));
  if (bundles.length !== 1) throw new Error(`Expected one macOS app bundle, found ${bundles.length}`);
  const helper = path.resolve(__dirname, '../tools/fix_mac_asar_integrity.py');
  execFileSync('python', [helper, path.join(context.appOutDir, bundles[0])], {stdio:'inherit'});
};

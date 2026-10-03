"""Run the actual workflow with fake Proxmox/APT commands, never real updates."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "proxmox-safe-update"
MOCK = r'''#!/usr/bin/env python3
import os, sys
from pathlib import Path
name = Path(sys.argv[0]).name
args = sys.argv[1:]
mode = os.environ['SCENARIO']
root = Path(os.environ['MOCK_ROOT'])
upgraded = (root / 'upgraded').exists()
with (root / 'calls').open('a') as f:
    f.write(name + ' ' + ' '.join(args) + '\n')
if name == 'apt-get':
    if 'update' in args:
        if mode == 'repository': print('W: Failed to fetch repository')
    elif '-s' in args:
        counter = root / 'simulations'
        n = int(counter.read_text()) + 1 if counter.exists() else 1
        counter.write_text(str(n))
        if mode == 'simulation': sys.exit(1)
        if upgraded or mode == 'none': print('0 upgraded, 0 newly installed, 0 to remove and 0 not upgraded.')
        elif mode == 'held': print('0 upgraded, 0 newly installed, 0 to remove and 2 not upgraded.')
        elif mode in ('protected', 'critical', 'essential', 'running', 'oldkernel'):
            p = {'protected':'proxmox-ve:amd64', 'critical':'proxmox-firewall:amd64', 'essential':'essential-package', 'running':'proxmox-kernel-6.8.1-pve-signed', 'oldkernel':'proxmox-kernel-6.5.1-pve-signed'}[mode]
            print('Remv ' + p)
            print('0 upgraded, 0 newly installed, 1 to remove and 0 not upgraded.')
        else:
            print('Inst ' + ('different-package' if mode == 'changed' and n > 1 else 'normal-package') + ' [1] (2 repository)')
            print('1 upgraded, 0 newly installed, 0 to remove and 0 not upgraded.')
    else:
        if mode == 'upgradefail': sys.exit(1)
        (root / 'upgraded').touch()
elif name == 'dpkg':
    if mode == 'audit' or (mode == 'postaudit' and upgraded): print('incomplete package')
elif name == 'dpkg-query':
    if '-S' in args: print('proxmox-kernel-6.8.1-pve-signed: /boot/vmlinuz-6.8.1-pve')
    elif '${Status}' in ' '.join(args): print('install ok installed')
    elif mode == 'essential': print('yes')
    else: print('no')
elif name == 'fuser': sys.exit(0 if mode == 'lock' else 1)
elif name == 'df':
    if '-B1' in args: print('Avail\n' + ('1' if mode == 'space' else '64424509440'))
    elif '-P' in args: print('Filesystem Blocks Used Available Capacity Mounted\n/mock 100 8 92 8% /')
    else: print('Avail\n60G')
elif name == 'pveversion': print('pve-manager/9.2.21/test')
elif name == 'uname': print('6.8.1-pve')
elif name == 'qm': print('VMID NAME STATUS\n100 test ' + ('stopped' if mode == 'guestchange' and upgraded else 'running'))
elif name == 'pct': print('VMID Status Lock Name\n200 running - test')
elif name == 'find': print('vmlinuz-' + ('6.9.1-pve' if mode == 'kernel' else '6.8.1-pve'))
elif name == 'tee':
    if mode == 'logfail': sys.exit(1)
    os.execv('/usr/bin/tee', ['/usr/bin/tee'] + args)
else: sys.exit(2)
'''


class Workflow(unittest.TestCase):
    def run_case(self, mode, options=('--check',), answer=''):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / 'bin'
            binary.mkdir()
            mock = binary / 'mock'
            mock.write_text(MOCK)
            mock.chmod(0o755)
            for command in ('apt-get', 'dpkg', 'dpkg-query', 'fuser', 'df', 'pveversion', 'uname', 'qm', 'pct', 'find', 'tee'):
                (binary / command).symlink_to(mock)
            # Test-copy-only bypass: no privilege bypass option in production.
            script = root / 'script'
            script.write_text(SOURCE.read_text().replace('((EUID == 0))', 'true'))
            env = dict(os.environ, PATH=str(binary) + ':' + os.environ['PATH'], SCENARIO=mode, MOCK_ROOT=str(root))
            result = subprocess.run(['bash', str(script), *options], input=answer, text=True, capture_output=True, env=env, timeout=15)
            calls = (root / 'calls').read_text()
            return result, calls, (root / 'upgraded').exists()

    def test_check_never_upgrades(self):
        for mode in ('none', 'changes', 'oldkernel'):
            with self.subTest(mode=mode):
                result, calls, upgraded = self.run_case(mode)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertFalse(upgraded)
                self.assertNotIn('--assume-yes', calls)

    def test_preflight_and_safety_fail_closed(self):
        for mode in ('repository', 'simulation', 'protected', 'critical', 'essential', 'running', 'audit', 'lock', 'space', 'held'):
            with self.subTest(mode=mode):
                result, calls, upgraded = self.run_case(mode)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertFalse(upgraded)
                self.assertNotIn('--assume-yes', calls)

    def test_confirmation(self):
        for answer in ('n\n', ''):
            result, calls, upgraded = self.run_case('changes', (), answer)
            self.assertFalse(upgraded)
            self.assertNotIn('--assume-yes', calls)
        for answer in ('y\n', 'Y\n'):
            result, calls, upgraded = self.run_case('changes', (), answer)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(upgraded)
            self.assertIn('VM 100: running -> running', result.stdout)
            self.assertIn('LXC 200: running -> running', result.stdout)

    def test_changed_plan_is_rejected(self):
        result, calls, upgraded = self.run_case('changed', (), 'y\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(upgraded)
        self.assertIn('plan changed', result.stderr)

    def test_post_failures(self):
        for mode in ('upgradefail', 'postaudit', 'guestchange'):
            result, _, _ = self.run_case(mode, (), 'y\n')
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertNotIn('UPDATE COMPLETED', result.stdout)

    def test_kernel_and_log_failure(self):
        result, _, _ = self.run_case('kernel', (), 'y\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('REBOOT REQUIRED', result.stdout)
        result, calls, upgraded = self.run_case('logfail', ('--verbose', '--check'))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(upgraded)


if __name__ == '__main__':
    unittest.main()

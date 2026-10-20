"""Accessible line-oriented terminal frontend and JSON interface."""
import argparse
import json
import os
import re
from pathlib import Path
import sys

from . import hardware as hw
from .execution import Store, SetupError, command, complete, reconcile, stage

MATRIX = Path('/usr/share/current/image-matrix.tsv')
COMPATIBILITY = Path('/usr/share/current/setup-compatibility.json')


def menu(title, options):
    print('\n' + title)
    for number, (_, label) in enumerate(options, 1):
        print(f'  {number}. {label}')
    while True:
        answer = input('Choose a number (q to leave setup): ').strip()
        if answer.lower() == 'q':
            raise EOFError
        if answer.isdecimal() and 1 <= int(answer) <= len(options):
            return options[int(answer) - 1][0]
        print('Enter one of the displayed numbers.')


def confirm(prompt):
    return input(prompt + ' [y/N]: ').strip().lower() in ('y', 'yes')


def review(candidate, hardware):
    print('\nReview Current setup')
    for key in ('platform', 'role', 'environment', 'driver', 'reference', 'compatibility'):
        print(f"  {key}: {candidate[key]}")
    print(f"  architecture: {hardware['architecture']}; CPU level: {hardware['cpu_level']}")
    print(f"  UEFI: {hardware['uefi']}; Secure Boot: {hardware['secure_boot']}")
    print('  GPUs: ' + (', '.join(f"{gpu['vendor']}:{gpu['device']} ({gpu['slot']})"
                                for gpu in hardware['gpus']) or 'none detected'))
    for reason in candidate['reasons']:
        print('  Reason: ' + reason)
    for warning in candidate['warnings']:
        print('  Warning: ' + warning)
    print('The native immutable digest will be resolved before staging. Signatures are required.\n'
          'The current deployment remains available for rollback. No automatic reboot.\n'
          'Destination updates remain pinned until you deliberately return to a moving channel.')


def plan(args, preferences):
    hardware = json.loads(args.fixture.read_text()) if args.fixture else hw.discover()
    rows, compatibility = hw.catalogue(args.matrix, args.compatibility)
    result = hw.recommend(hardware, rows, compatibility, **preferences)
    for candidate in result['candidates']:
        candidate['reference'] = candidate['reference'].rsplit(':', 1)[0] + ':' + args.channel
    return result


def wizard(args, store=None):
    state = reconcile(store) if store else {'phase': 'not-configured'}
    if state['phase'] == 'complete':
        print('Current setup is complete. Use current rebase for later image changes.')
        return
    if state['phase'] == 'image-staged':
        print('Destination staged: ' + state['target'] + '\nReboot when ready; setup is not complete yet.')
        return
    if state['phase'] == 'destination-booted':
        print('The selected image is booted. Verify networking and your login/desktop before accepting.')
        if confirm('Have networking and your intended login/session worked?'):
            complete(store)
            print('Current setup is complete.')
        return
    print('Current setup — q or Ctrl-D exits safely. Use nmtui in another console if networking needs setup.')
    if state.get('error'):
        print('Previous attempt: ' + state['error'])
    saved = state.get('candidate')
    if saved and confirm('Resume the previous selection?'):
        preferences = {'distribution': saved['platform'], 'role': saved['role'],
                       'desktop': saved['environment'] if saved['role'] == 'workstation' else 'gnome'}
    else:
        preferences = {'distribution': menu('Choose a distribution', [
            ('alma10', 'AlmaLinux 10'), ('fedora', 'Fedora'), ('alma9', 'AlmaLinux 9'),
            ('auto', 'Automatically recommend')]),
            'role': menu('Choose a system type', [('server', 'Server'), ('workstation', 'Workstation')]),
            'desktop': 'gnome'}
        if preferences['role'] == 'workstation':
            preferences['desktop'] = menu('Choose a desktop', [('gnome', 'GNOME'), ('cosmic', 'COSMIC')])
    result = plan(args, preferences)
    if not result['candidates']:
        print(json.dumps(result, indent=2))
        raise SetupError('No compatible candidate for these preferences. Run setup again to change them.')
    candidate = next((item for item in result['candidates'] if saved and item['image'] == saved['image']), None)
    candidate = candidate or result['recommended']
    if candidate:
        review(candidate, result['hardware'])
        if confirm('Choose a different compatible image?'):
            candidate = None
    if not candidate:
        for warning in result['warnings']:
            print('Warning: ' + warning)
        selected = menu('Compatible candidates (all experimental)', [
            (item['image'], item['image']) for item in result['candidates']])
        candidate = next(item for item in result['candidates'] if item['image'] == selected)
        review(candidate, result['hardware'])
    if args.dry_run:
        print('Dry run: no registry access, state writes, switch or reboot performed.')
        return
    if not confirm('Accept these experimental limitations and stage this image?'):
        return
    while True:
        try:
            # Re-discover/revalidate immediately before mutation, including resumed selections.
            fresh = plan(args, preferences)
            candidate = next((item for item in fresh['candidates'] if item['image'] == candidate['image']), None)
            if candidate is None:
                raise SetupError('Hardware/policy changed; restart selection')
            print('Checking registry metadata and signing policy, then staging the image. This can take several minutes.', flush=True)
            state = stage(store, candidate, fresh['hardware'])
            print('Validated destination staged: ' + state['target'])
            print('Reboot with sudo systemctl reboot when ready. Then run sudo current setup to confirm completion.')
            return
        except (SetupError, OSError, ValueError) as error:
            print('Setup failed: ' + str(error), file=sys.stderr)
            print('Your current deployment is retained. Inspect bootc status; configure networking with nmtui.')
            recovered = reconcile(store)
            if recovered['phase'] in ('image-staged', 'destination-booted'):
                print('Recovered the expected deployment; run current setup to continue.')
                return
            if candidate is None or not confirm('Retry this selection without repeating the questionnaire?'):
                return


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', nargs='?', choices=('wizard', 'plan', 'status', 'reconcile', 'complete'), default='wizard')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--fixture', type=Path, help='Synthetic hardware JSON; plan/dry-run only')
    parser.add_argument('--matrix', type=Path, default=MATRIX)
    parser.add_argument('--compatibility', type=Path, default=COMPATIBILITY)
    parser.add_argument('--channel', default='latest', help='Published Current channel, e.g. pr-123 for qualification')
    parser.add_argument('--distribution', choices=('auto', 'fedora', 'alma10', 'alma9'), default='auto')
    parser.add_argument('--role', choices=('server', 'workstation'), default='server')
    parser.add_argument('--desktop', choices=('gnome', 'cosmic'), default='gnome')
    args = parser.parse_args(argv)
    if not re.fullmatch(r'latest|pr-[0-9]+|br-[A-Za-z0-9_.-]+', args.channel):
        parser.error('Use latest, pr-N or a br-NAME channel')
    read_only = args.mode == 'plan' or (args.mode == 'wizard' and args.dry_run)
    if not read_only and (args.fixture or args.matrix != MATRIX or args.compatibility != COMPATIBILITY):
        parser.error('Fixture/catalogue overrides are restricted to plan and dry-run')
    try:
        if args.mode == 'plan':
            print(json.dumps(plan(args, {'distribution': args.distribution, 'role': args.role,
                                         'desktop': args.desktop}), indent=2))
        elif read_only:
            wizard(args)
        else:
            if os.geteuid() != 0:
                raise SetupError('Run sudo current setup to authenticate as an administrator')
            store = Store()
            with store.locked():
                if args.mode == 'wizard':
                    wizard(args, store)
                elif args.mode == 'status':
                    print(json.dumps(store.load(), indent=2))
                elif args.mode == 'reconcile':
                    print(json.dumps(reconcile(store), indent=2))
                elif args.mode == 'complete':
                    if not sys.stdin.isatty() or not confirm('Have networking and your intended login/session worked?'):
                        raise SetupError('Interactive user acceptance required')
                    print(json.dumps(complete(store), indent=2))
    except (SetupError, OSError, ValueError, KeyError, TypeError) as error:
        print('Current setup: ' + str(error), file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print('\nSetup paused. Resume with sudo current setup.')
        return 130
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

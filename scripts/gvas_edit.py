"""Edit scalar values in The Lantern of the Laughless Saint save files.

Only fixed-size values (int, float, double, bool) are editable. They are
patched in place, so no enclosing size fields need to change.

Fields are addressed by path, since offsets shift between saves:

    PlayerData.PawnData.SavedComponents[ComponentName=InventoryComponent].ByteData.SavedCurrency

- `Name` selects a property. `ByteData` blobs are parsed transparently.
- `[3]` selects an array element by index.
- `[Key=Pattern]` selects the array element whose `Key` (itself a dotted
  path, e.g. `SkillTag.TagName`) matches the glob `Pattern`.

Aliases for common player fields (see ALIASES):

    gold, xp, attr:<Name>, skill:<Name>.<Field>, skillpoints, perkpoints

Examples:

    python3 scripts/gvas_edit.py show QuickSave1.sav gold xp skill:Alchemy
    python3 scripts/gvas_edit.py set QuickSave1.sav gold=5000 attr:MaxHealth=200 skill:Alchemy.Level=25
"""
import argparse
import fnmatch
import os
import shutil
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gvas  # noqa: E402

PLAYER_STATE = 'PlayerData.PlayerStateData.SavedComponents'
ABILITY = PLAYER_STATE + '[ComponentName=AbilitySystemComponent].ByteData'
SKILLS = PLAYER_STATE + '[ComponentName=SkillComponent].ByteData'
SKILL_TREE = PLAYER_STATE + '[ComponentName=SkillTreeComponent].ByteData'

# Each alias expands to one or more paths; `set` writes all of them. Where the
# game stores a value twice (live copy and saved copy), both are listed.
ALIASES = {
    'gold': ['PlayerData.PawnData.SavedComponents[ComponentName=InventoryComponent].ByteData.SavedCurrency'],
    'xp': [ABILITY + '.SavedAttributes[AttributeName=XP].Value'],
    'skillpoints': [SKILLS + '.SkillPoints', SKILLS + '.SkillSaveData.SavedSkillPoints'],
    'perkpoints': [SKILL_TREE + '.SkillTreePoints', SKILL_TREE + '.SkillTreeSaveData.SavedSkillTreePoints'],
}
PREFIX_ALIASES = {
    'attr:': lambda rest: [ABILITY + f'.SavedAttributes[AttributeName={rest}].Value'],
    'skill:': lambda rest: [_skill_path(rest)],
}

INT_TYPES = {
    'IntProperty': ('<i', 4), 'UInt32Property': ('<I', 4),
    'Int64Property': ('<q', 8), 'UInt64Property': ('<Q', 8),
    'Int16Property': ('<h', 2), 'Int8Property': ('<b', 1),
}
FLOAT_TYPES = {'FloatProperty': '<f', 'DoubleProperty': '<d'}


class PathError(Exception):
    pass


def _skill_path(rest):
    name, _, field = rest.partition('.')
    path = SKILLS + f'.SkillSaveData.SavedSkills[SkillTag.TagName=Skill.*{name}]'
    return path + '.' + field if field else path


def expand(spec):
    if spec in ALIASES:
        return ALIASES[spec]
    for prefix, fn in PREFIX_ALIASES.items():
        if spec.startswith(prefix):
            return fn(spec[len(prefix):])
    return [spec]


def tokenize(path):
    """Split `A.B[x=y.z].C` into ['A', 'B', ('sel', 'x=y.z'), 'C']."""
    tokens, buf, i = [], '', 0
    while i < len(path):
        c = path[i]
        if c == '.':
            if buf:
                tokens.append(buf)
            buf = ''
        elif c == '[':
            if buf:
                tokens.append(buf)
            buf = ''
            j = path.find(']', i)
            if j < 0:
                raise PathError(f'unclosed [ in {path!r}')
            tokens.append(('sel', path[i + 1:j]))
            i = j
        else:
            buf += c
        i += 1
    if buf:
        tokens.append(buf)
    return tokens


class Node:
    """A position in the tree: a Prop, a struct (list of Props), or an array element."""

    def __init__(self, value, base, prop=None):
        self.value, self.base, self.prop = value, base, prop


def _descend(value, base):
    """Unwrap ByteData blobs into their nested property lists."""
    if isinstance(value, tuple) and value and value[0] == 'bytes':
        sub = gvas.parse_bytedata(value)
        if not sub:
            raise PathError('ByteData blob could not be parsed')
        return sub[0], base + sub[1]
    return value, base


def resolve(root, path):
    node = Node(root, 0)
    for tok in tokenize(path):
        value, base = _descend(node.value, node.base)
        if isinstance(tok, tuple):
            node = _select(value, base, tok[1], path)
        else:
            if not (isinstance(value, list) and all(isinstance(p, gvas.Prop) for p in value)):
                raise PathError(f'{tok!r} in {path!r}: parent is not a struct')
            match = [p for p in value if p.name == tok]
            if not match:
                names = ', '.join(sorted({p.name for p in value}))
                raise PathError(f'no property {tok!r} in {path!r}; available: {names}')
            node = Node(match[0].value, base, match[0])
    return node


def _select(value, base, sel, path):
    if not isinstance(value, list) or (value and not isinstance(value[0], list)):
        raise PathError(f'[{sel}] in {path!r}: parent is not an array of structs')
    if sel.isdigit():
        i = int(sel)
        if i >= len(value):
            raise PathError(f'[{sel}] in {path!r}: array has {len(value)} elements')
        return Node(value[i], base)
    key, eq, pattern = sel.partition('=')
    if not eq:
        raise PathError(f'[{sel}] in {path!r}: expected [index] or [Key=Pattern]')
    hits = []
    for elem in value:
        try:
            v = resolve_in(elem, base, key).value
        except PathError:
            continue
        if fnmatch.fnmatchcase(str(v), pattern):
            hits.append(elem)
    if len(hits) != 1:
        raise PathError(f'[{sel}] in {path!r} matched {len(hits)} elements, expected 1')
    return Node(hits[0], base)


def resolve_in(props, base, path):
    node = resolve(props, path)
    node.base += base
    return node


def format_node(node):
    p = node.prop
    if p is not None and not isinstance(p.value, (list, tuple)):
        return f'{node.base + p.value_offset:#010x} {gvas.type_str(p.type)} = {p.value!r}'
    return None


def show(props, spec):
    for path in expand(spec):
        try:
            node = resolve(props, path)
        except PathError as e:
            print(f'{spec}: {e}', file=sys.stderr)
            return False
        line = format_node(node)
        if line:
            print(f'{spec}: {line}' + (f'   ({path})' if path != spec else ''))
        else:
            value, base = _descend(node.value, node.base)
            print(f'{spec}:' + (f'   ({path})' if path != spec else ''))
            if isinstance(value, list) and value and isinstance(value[0], gvas.Prop):
                gvas.dump(value, base, depth=1)
            elif isinstance(value, list) and value and isinstance(value[0], list):
                for i, elem in enumerate(value):
                    print(f'  [{i}]')
                    gvas.dump(elem, base, depth=2)
            else:
                print(f'  {value!r}')
    return True


def encode(prop, text):
    """Return (offset_relative_to_base, bytes) for writing `text` into `prop`."""
    t = prop.type[0]
    if t in INT_TYPES:
        fmt, _ = INT_TYPES[t]
        try:
            v = int(text, 0)
            return prop.value_offset, struct.pack(fmt, v)
        except (ValueError, struct.error):
            raise PathError(f'{text!r} is not a valid {t}')
    if t in FLOAT_TYPES:
        try:
            return prop.value_offset, struct.pack(FLOAT_TYPES[t], float(text))
        except ValueError:
            raise PathError(f'{text!r} is not a valid number')
    if t == 'BoolProperty':
        low = text.lower()
        if low not in ('true', 'false', '1', '0'):
            raise PathError(f'{text!r} is not a valid bool (true/false)')
        return None, low in ('true', '1')
    raise PathError(f'{t} values change size and are not editable yet')


def apply_edits(data, props, edits):
    data = bytearray(data)
    changes = []
    for spec, text in edits:
        for path in expand(spec):
            node = resolve(props, path)
            p = node.prop
            if p is None or isinstance(p.value, (list, tuple)):
                raise PathError(f'{spec}: {path!r} is not a scalar value')
            off, payload = encode(p, text)
            if off is None:  # bool lives in bit 0x10 of the tag flags byte
                at = node.base + p.flags_offset
                data[at] = (data[at] | 0x10) if payload else (data[at] & ~0x10)
            else:
                at = node.base + off
                data[at:at + len(payload)] = payload
            changes.append((spec, path, p.value))
    return bytes(data), changes


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('show', help='print values or subtrees')
    s.add_argument('save')
    s.add_argument('paths', nargs='+')
    e = sub.add_parser('set', help='write PATH=VALUE edits')
    e.add_argument('save')
    e.add_argument('edits', nargs='+', metavar='PATH=VALUE')
    e.add_argument('-o', '--output', help='write to this file instead of editing in place')
    e.add_argument('--no-backup', action='store_true', help='skip the backup when editing in place')
    args = ap.parse_args()

    data = open(args.save, 'rb').read()
    _, r = gvas.read_header(data)
    props = gvas.read_props(r)

    if args.cmd == 'show':
        ok = all([show(props, spec) for spec in args.paths])
        sys.exit(0 if ok else 1)

    edits = []
    for item in args.edits:
        spec, eq, text = item.rpartition('=')
        if not eq or not spec:
            ap.error(f'{item!r} is not PATH=VALUE')
        edits.append((spec, text))
    try:
        new, changes = apply_edits(data, props, edits)
    except PathError as err:
        sys.exit(f'error: {err}')

    # Re-parse and confirm every edited field reads back as requested.
    _, r2 = gvas.read_header(new)
    props2 = gvas.read_props(r2)
    for spec, path, old in changes:
        got = resolve(props2, path).prop.value
        print(f'{spec}: {old!r} -> {got!r}' + (f'   ({path})' if path != spec else ''))

    out = args.output or args.save
    if out == args.save and not args.no_backup:
        backup = f'{args.save}.{time.strftime("%Y%m%d-%H%M%S")}.bak'
        shutil.copy2(args.save, backup)
        print(f'backup: {backup}')
    tmp = out + '.tmp'
    with open(tmp, 'wb') as f:
        f.write(new)
    os.replace(tmp, out)
    print(f'wrote: {out}')


if __name__ == '__main__':
    main()

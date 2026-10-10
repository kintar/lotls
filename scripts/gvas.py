"""Minimal GVAS (UE 5.4+ complete-type-name property tags) parser."""
import struct
import sys


class R:
    def __init__(self, data, pos=0, end=None):
        self.d = data
        self.p = pos
        self.end = len(data) if end is None else end

    def i32(self):
        v = struct.unpack_from('<i', self.d, self.p)[0]; self.p += 4; return v

    def u32(self):
        v = struct.unpack_from('<I', self.d, self.p)[0]; self.p += 4; return v

    def u16(self):
        v = struct.unpack_from('<H', self.d, self.p)[0]; self.p += 2; return v

    def u8(self):
        v = self.d[self.p]; self.p += 1; return v

    def raw(self, n):
        v = self.d[self.p:self.p + n]; self.p += n; return v

    def fstr(self):
        n = self.i32()
        if n == 0:
            return ''
        if n < 0:
            b = self.raw(-n * 2); return b[:-2].decode('utf-16-le')
        b = self.raw(n)
        return b[:-1].decode('latin-1')


def read_type(r):
    name = r.fstr()
    n = r.i32()
    return (name, [read_type(r) for _ in range(n)])


def type_str(t):
    name, inner = t
    return name + ('<' + ','.join(type_str(i) for i in inner) + '>' if inner else '')


class Prop:
    __slots__ = ('name', 'type', 'offset', 'flags_offset', 'value_offset', 'size', 'value', 'index')

    def __repr__(self):
        return f'{self.name}:{type_str(self.type)}@{self.value_offset:#x}={self.value!r}'


NATIVE_STRUCTS = {
    'Guid': lambda r: r.raw(16).hex(),
    'Vector': lambda r: struct.unpack('<3d', r.raw(24)),
    'Rotator': lambda r: struct.unpack('<3d', r.raw(24)),
    'Quat': lambda r: struct.unpack('<4d', r.raw(32)),
    'Vector2D': lambda r: struct.unpack('<2d', r.raw(16)),
    'DateTime': lambda r: struct.unpack('<q', r.raw(8))[0],
    'Timespan': lambda r: struct.unpack('<q', r.raw(8))[0],
    'GameplayTag': lambda r: r.fstr(),
    'LinearColor': lambda r: struct.unpack('<4f', r.raw(16)),
}


def read_value(r, t, size, flags, in_container=False):
    name, inner = t
    start = r.p
    if name == 'BoolProperty':
        return bool(flags & 0x10) if not in_container else bool(r.u8())
    if name == 'IntProperty':
        return r.i32()
    if name == 'UInt32Property':
        return r.u32()
    if name == 'Int64Property':
        return struct.unpack('<q', r.raw(8))[0]
    if name == 'UInt64Property':
        return struct.unpack('<Q', r.raw(8))[0]
    if name == 'Int16Property':
        return struct.unpack('<h', r.raw(2))[0]
    if name == 'Int8Property':
        return struct.unpack('<b', r.raw(1))[0]
    if name == 'FloatProperty':
        return struct.unpack('<f', r.raw(4))[0]
    if name == 'DoubleProperty':
        return struct.unpack('<d', r.raw(8))[0]
    if name in ('StrProperty', 'NameProperty'):
        return r.fstr()
    if name == 'EnumProperty':
        return r.fstr()
    if name == 'ByteProperty':
        if inner and inner[0][0] != 'None' and not in_container:
            return r.fstr() if size != 1 else r.u8()
        return r.u8()
    if name == 'ObjectProperty':
        return r.fstr()
    if name == 'SoftObjectProperty':
        a = r.fstr(); b = r.fstr(); r.i32(); return (a, b)
    if name == 'StructProperty':
        sname = inner[0][0] if inner else '?'
        if flags & 0x08 or (in_container and sname in NATIVE_STRUCTS and sname != 'GameplayTag'):
            if sname in NATIVE_STRUCTS:
                return NATIVE_STRUCTS[sname](r)
            if size is None:
                raise ValueError(f'unknown native struct {sname} in container')
            return ('raw', r.raw(size).hex())
        return read_props(r)
    if name in ('ArrayProperty', 'SetProperty'):
        et = inner[0]
        if name == 'SetProperty':
            r.i32()  # num removed
        n = r.i32()
        if et[0] == 'ByteProperty':
            data = r.raw(n)
            return ('bytes', start + 4, data)
        return [read_value(r, et, None, 0, True) for _ in range(n)]
    if name == 'MapProperty':
        kt, vt = inner
        nrem = r.i32()
        for _ in range(nrem):
            read_value(r, kt, None, 0, True)
        n = r.i32()
        return [(read_value(r, kt, None, 0, True), read_value(r, vt, None, 0, True)) for _ in range(n)]
    if size is None:
        raise ValueError(f'cannot read {type_str(t)} in container')
    return ('raw', r.raw(size).hex())


def read_props(r):
    props = []
    while True:
        off = r.p
        name = r.fstr()
        if name == 'None' or name == '':
            break
        t = read_type(r)
        size = r.i32()
        flags_offset = r.p
        flags = r.u8()
        idx = 0
        if flags & 0x01:
            idx = r.i32()
        if flags & 0x02:
            r.raw(16)
        if flags & 0x04:
            ext = r.u8()
            if ext & 0x02:
                r.u8(); r.u8()  # overridable operation + experimental
        p = Prop()
        p.name, p.type, p.offset, p.value_offset, p.size, p.index = name, t, off, r.p, size, idx
        p.flags_offset = flags_offset
        vstart = r.p
        try:
            p.value = read_value(r, t, size, flags)
        except Exception as e:  # fall back to raw on anything we can't decode
            p.value = ('error', str(e))
        if t[0] != 'BoolProperty' and r.p != vstart + size:
            if not (isinstance(p.value, tuple) and p.value and p.value[0] == 'error'):
                p.value = ('sizemismatch', r.p - vstart, size, p.value)
            r.p = vstart + size
        props.append(p)
    return props


def parse_bytedata(value):
    """ByteData arrays hold nested tagged property lists; parse them in place."""
    _, off, data = value
    r = R(data, 1)  # leading flag byte
    try:
        props = read_props(r)
    except Exception:
        return None
    return props, off


def read_header(d):
    r = R(d)
    assert r.raw(4) == b'GVAS'
    h = {'save_ver': r.i32(), 'ue4': r.i32()}
    if h['save_ver'] >= 3:
        h['ue5'] = r.i32()
    h['engine'] = (r.u16(), r.u16(), r.u16(), r.u32(), r.fstr())
    h['cv_format'] = r.i32()
    n = r.i32()
    r.raw(n * 20)
    h['class'] = r.fstr()
    h['flag'] = r.u8()
    return h, r


def load(path):
    d = open(path, 'rb').read()
    h, r = read_header(d)
    return h, read_props(r)


def dump(props, base=0, depth=0, out=sys.stdout, maxdepth=99):
    pad = '  ' * depth
    for p in props:
        v = p.value
        loc = f'{base + p.value_offset:#010x}'
        ts = type_str(p.type)
        if isinstance(v, list) and v and isinstance(v[0], list):
            print(f'{pad}{loc} {p.name} : {ts} [{len(v)}]', file=out)
            if depth < maxdepth:
                for i, e in enumerate(v):
                    print(f'{pad}  [{i}]', file=out)
                    dump(e, base, depth + 2, out, maxdepth)
        elif isinstance(v, list) and v and isinstance(v[0], Prop):
            print(f'{pad}{loc} {p.name} : {ts}', file=out)
            if depth < maxdepth:
                dump(v, base, depth + 1, out, maxdepth)
        elif isinstance(v, tuple) and v and v[0] == 'bytes':
            sub = parse_bytedata(v)
            if sub and sub[0]:
                print(f'{pad}{loc} {p.name} : {ts} (nested, {len(v[2])} bytes)', file=out)
                if depth < maxdepth:
                    dump(sub[0], base + v[1], depth + 1, out, maxdepth)
            else:
                print(f'{pad}{loc} {p.name} : {ts} ({len(v[2])} raw bytes) {v[2][:64].hex()}', file=out)
        else:
            s = repr(v)
            if len(s) > 200:
                s = s[:200] + '...'
            print(f'{pad}{loc} {p.name} : {ts} = {s}', file=out)


if __name__ == '__main__':
    h, props = load(sys.argv[1])
    print(h)
    dump(props)

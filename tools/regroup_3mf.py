"""Regroup a Fusion 3MF export of the Wook lightbox into 6 multi-part objects for Bambu Studio.

Usage: python3 -I regroup_3mf.py <fusion_export.3mf> <output.3mf>

Each group becomes one 3MF object built from components (Bambu Studio shows it as one
object with several parts, same as its Assemble command). Geometry is converted to mm.
"""
import re, sys, uuid, zipfile

GROUPS = [
    ("W Body",  ["W", "W back face"]),
    ("W Cap",   ["Front W lip", "Front W cap"]),
    ("OO Body", ["oo", "o1 back face", "o2 back face", "oo window o1", "oo window o2"]),
    ("OO Cap",  ["Front o1 lip", "Front o1 cap", "Front o2 lip", "Front o2 cap"]),
    ("K Body",  ["K", "k back face"]),
    ("K Cap",   ["Front k lip", "Front k cap"]),
]
UNIT_MM = {"micron": 0.001, "millimeter": 1.0, "centimeter": 10.0, "inch": 25.4, "foot": 304.8, "meter": 1000.0}

def main(src, dst):
    zin = zipfile.ZipFile(src)
    model = zin.read("3D/3dmodel.model").decode("utf-8")

    unit = re.search(r'<model\b[^>]*\bunit="([^"]+)"', model).group(1)
    k = UNIT_MM[unit]
    if k != 1.0:
        num = lambda m: "%s=\"%.6f\"" % (m.group(1), float(m.group(2)) * k)
        model = re.sub(r'<vertex\b[^>]*/>', lambda v: re.sub(r'\b([xyz])="([-0-9.eE+]+)"', num, v.group(0)), model)
        model = re.sub(r'(<model\b[^>]*\bunit=)"[^"]+"', r'\1"millimeter"', model, count=1)

    ids = {name: int(oid) for oid, name in re.findall(r'<object id="(\d+)" name="([^"]+)"', model)}
    used = [n for _, members in GROUPS for n in members]
    missing = [n for n in used if n not in ids]
    extra = [n for n in ids if n not in used]
    assert not missing, "missing in export: %s" % missing
    assert not extra, "export has parts not assigned to a group: %s" % extra
    assert len(used) == len(set(used)), "part listed twice"

    nid = max(ids.values()) + 1
    objs, items = [], []
    for gname, members in GROUPS:
        comps = "".join('\n\t\t\t\t<component objectid="%d" p:UUID="%s"/>' % (ids[m], uuid.uuid4()) for m in members)
        objs.append('\t\t<object id="%d" name="%s" type="model" p:UUID="%s">\n\t\t\t<components>%s\n\t\t\t</components>\n\t\t</object>\n'
                    % (nid, gname, uuid.uuid4(), comps))
        items.append('\t\t<item objectid="%d" p:UUID="%s"/>\n' % (nid, uuid.uuid4()))
        nid += 1

    model = model.replace("</resources>", "".join(objs) + "\t</resources>", 1)
    model = re.sub(r'(<build\b[^>]*>).*?(</build>)', lambda m: m.group(1) + "\n" + "".join(items) + "\t" + m.group(2), model, count=1, flags=re.S)

    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = model.encode("utf-8") if info.filename == "3D/3dmodel.model" else zin.read(info.filename)
            zout.writestr(info, data)
    print("unit %s -> millimeter (x%g); %d parts -> %d objects: %s" % (unit, k, len(used), len(GROUPS), ", ".join(g for g, _ in GROUPS)))

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])

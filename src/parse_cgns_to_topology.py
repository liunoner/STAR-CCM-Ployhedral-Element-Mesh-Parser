import json
import math
import re
import sys
from pathlib import Path

import h5py


def parse_ngon(connectivity):
    faces = []
    i = 0
    n = len(connectivity)
    while i < n:
        count = int(connectivity[i])
        i += 1
        faces.append([int(x) for x in connectivity[i:i + count]])
        i += count
    if i != n:
        raise ValueError("NGON connectivity ended at an unexpected offset")
    return faces


def parse_nface(connectivity):
    cells = []
    i = 0
    n = len(connectivity)
    while i < n:
        count = int(connectivity[i])
        i += 1
        cells.append([int(x) for x in connectivity[i:i + count]])
        i += count
    if i != n:
        raise ValueError("NFACE connectivity ended at an unexpected offset")
    return cells


def label_of(node):
    label = node.attrs.get("label", b"")
    if hasattr(label, "decode"):
        return label.decode("utf-8", "ignore")
    return str(label)


def find_zone(handle):
    for base in handle.values():
        if not isinstance(base, h5py.Group) or label_of(base) != "CGNSBase_t":
            continue
        for zone in base.values():
            if isinstance(zone, h5py.Group) and label_of(zone) == "Zone_t":
                return zone
    raise ValueError("No CGNS Zone_t found")


def element_type(section):
    return int(section[" data"][0])


def element_range(section):
    values = section["ElementRange"][" data"][...]
    return int(values[0]), int(values[1])


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def norm(a):
    return math.sqrt(dot(a, a))


def center(points):
    inv = 1.0 / len(points)
    return (
        sum(p[0] for p in points) * inv,
        sum(p[1] for p in points) * inv,
        sum(p[2] for p in points) * inv,
    )


def newell_normal(points):
    nx = ny = nz = 0.0
    count = len(points)
    for i in range(count):
        current = points[i]
        nxt = points[(i + 1) % count]
        nx += (current[1] - nxt[1]) * (current[2] + nxt[2])
        ny += (current[2] - nxt[2]) * (current[0] + nxt[0])
        nz += (current[0] - nxt[0]) * (current[1] + nxt[1])
    return (nx, ny, nz)


def safe_filename(name):
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("._")
    return safe or "unnamed"


def fmt_float(value):
    return format(float(value), ".17g")


def load_cgns(cgns_path):
    with h5py.File(cgns_path, "r") as handle:
        zone = find_zone(handle)
        zone_name = zone.name.rsplit("/", 1)[-1]

        coords = zone["GridCoordinates"]
        xs = coords["CoordinateX"][" data"][...]
        ys = coords["CoordinateY"][" data"][...]
        zs = coords["CoordinateZ"][" data"][...]

        raw_nodes = {
            i + 1: (float(xs[i]), float(ys[i]), float(zs[i]))
            for i in range(len(xs))
        }

        nface_section = None
        ngon_sections = []
        boundary_sections = []

        for name, child in zone.items():
            if not isinstance(child, h5py.Group) or label_of(child) != "Elements_t":
                continue
            etype = element_type(child)
            start, _ = element_range(child)
            if etype == 22:
                ngon_sections.append((name, child))
                if start != 1:
                    boundary_sections.append((name, child))
            elif etype == 23:
                nface_section = child

        if not ngon_sections:
            raise ValueError("No NGON face sections found")
        if nface_section is None:
            raise ValueError("No NFACE cell section found")

        raw_faces = {}
        for section_name, section in ngon_sections:
            section_start, section_end = element_range(section)
            face_nodes = parse_ngon(section["ElementConnectivity"][" data"][...])
            expected = section_end - section_start + 1
            if len(face_nodes) != expected:
                raise ValueError(
                    f"Section {section_name} range expects {expected} faces, got {len(face_nodes)}"
                )
            is_boundary = section_start != 1
            for offset, node_ids in enumerate(face_nodes):
                raw_faces[section_start + offset] = {
                    "raw_id": section_start + offset,
                    "raw_node_ids": node_ids,
                    "boundary": section_name if is_boundary else None,
                    "occurrences": [],
                }

        nface_start, _ = element_range(nface_section)
        nface_cells = parse_nface(nface_section["ElementConnectivity"][" data"][...])
        raw_cells = {}
        for offset, signed_face_ids in enumerate(nface_cells):
            raw_cell_id = nface_start + offset
            raw_cells[raw_cell_id] = {
                "raw_id": raw_cell_id,
                "raw_signed_face_ids": [int(x) for x in signed_face_ids],
            }
            for signed_face_id in signed_face_ids:
                raw_face_id = abs(int(signed_face_id))
                raw_faces[raw_face_id]["occurrences"].append({
                    "raw_cell_id": raw_cell_id,
                    "sign": -1 if int(signed_face_id) < 0 else 1,
                })

        raw_boundaries = []
        for boundary_name, section in boundary_sections:
            start, end = element_range(section)
            raw_boundaries.append({
                "name": boundary_name,
                "raw_face_ids": list(range(start, end + 1)),
                "source_element_range": [start, end],
            })

        return zone_name, raw_nodes, raw_faces, raw_cells, raw_boundaries


def build_topology(cgns_path):
    zone_name, raw_nodes, raw_faces, raw_cells, raw_boundaries = load_cgns(cgns_path)

    raw_node_ids = sorted(raw_nodes)
    raw_face_ids = sorted(raw_faces)
    raw_cell_ids = sorted(raw_cells)

    node_id_map = {raw_id: i + 1 for i, raw_id in enumerate(raw_node_ids)}
    face_id_map = {raw_id: i + 1 for i, raw_id in enumerate(raw_face_ids)}
    cell_id_map = {raw_id: i + 1 for i, raw_id in enumerate(raw_cell_ids)}

    nodes = [
        {
            "id": node_id_map[raw_id],
            "cgns_id": raw_id,
            "x": raw_nodes[raw_id][0],
            "y": raw_nodes[raw_id][1],
            "z": raw_nodes[raw_id][2],
        }
        for raw_id in raw_node_ids
    ]
    node_points = {node["id"]: (node["x"], node["y"], node["z"]) for node in nodes}

    raw_cell_node_sets = {}
    for raw_cell_id, raw_cell in raw_cells.items():
        node_set = set()
        for signed_face_id in raw_cell["raw_signed_face_ids"]:
            node_set.update(node_id_map[n] for n in raw_faces[abs(signed_face_id)]["raw_node_ids"])
        raw_cell_node_sets[raw_cell_id] = node_set

    cell_centers = {
        cell_id_map[raw_cell_id]: center([node_points[n] for n in sorted(node_set)])
        for raw_cell_id, node_set in raw_cell_node_sets.items()
    }

    faces = []
    orientation_warnings = []
    for raw_face_id in raw_face_ids:
        raw_face = raw_faces[raw_face_id]
        face_index = face_id_map[raw_face_id]
        node_ids = [node_id_map[n] for n in raw_face["raw_node_ids"]]
        occurrences = raw_face["occurrences"]
        cell_ids = [cell_id_map[o["raw_cell_id"]] for o in occurrences]

        if not occurrences:
            raise ValueError(f"Face {raw_face_id} has no adjacent cells")

        face_points = [node_points[n] for n in node_ids]
        face_center = center(face_points)
        normal = newell_normal(face_points)

        inward_occurrences = [o for o in occurrences if o["sign"] < 0]
        if inward_occurrences:
            cell1 = cell_id_map[inward_occurrences[0]["raw_cell_id"]]
        elif len(cell_ids) == 1:
            cell1 = cell_ids[0]
        else:
            cell1 = max(cell_ids, key=lambda cid: dot(normal, sub(cell_centers[cid], face_center)))

        remaining = [cid for cid in cell_ids if cid != cell1]
        cell2 = remaining[0] if remaining else 0

        if len(cell_ids) > 2:
            orientation_warnings.append(
                f"Face {face_index} has more than two adjacent cells: {cell_ids}"
            )

        direction_to_cell1 = sub(cell_centers[cell1], face_center)
        normal_length = norm(normal)
        if normal_length == 0.0:
            orientation_warnings.append(f"Face {face_index} has near-zero Newell normal")
        elif dot(normal, direction_to_cell1) <= 0.0:
            node_ids = list(reversed(node_ids))
            face_points = [node_points[n] for n in node_ids]
            normal = newell_normal(face_points)
            if dot(normal, direction_to_cell1) <= 0.0:
                orientation_warnings.append(
                    f"Face {face_index} orientation could not be confirmed geometrically"
                )

        faces.append({
            "id": face_index,
            "cgns_id": raw_face_id,
            "node_ids": node_ids,
            "cell_ids": [cell1] + ([cell2] if cell2 else []),
            "cell1": cell1,
            "cell2": cell2,
            "boundary": raw_face["boundary"],
        })

    cells = []
    for raw_cell_id in raw_cell_ids:
        raw_cell = raw_cells[raw_cell_id]
        cell_index = cell_id_map[raw_cell_id]
        face_indices = [face_id_map[abs(fid)] for fid in raw_cell["raw_signed_face_ids"]]
        cells.append({
            "id": cell_index,
            "cgns_id": raw_cell_id,
            "face_ids": face_indices,
            "oriented_face_ids": [
                face_id_map[abs(fid)] * (-1 if int(fid) < 0 else 1)
                for fid in raw_cell["raw_signed_face_ids"]
            ],
        })

    boundaries = []
    for raw_boundary in raw_boundaries:
        face_indices = [face_id_map[raw_id] for raw_id in raw_boundary["raw_face_ids"]]
        boundaries.append({
            "name": raw_boundary["name"],
            "source_element_range": raw_boundary["source_element_range"],
            "face_ids": face_indices,
            "missing_face_matches": 0,
            "txt_file": f"{safe_filename(raw_boundary['name'])}.txt",
        })

    return {
        "schema": "starccm-cgns-mesh-topology-v0.3",
        "source": str(cgns_path),
        "zone": zone_name,
        "counts": {
            "nodes": len(nodes),
            "faces": len(faces),
            "cells": len(cells),
            "boundaries": len(boundaries),
            "orientation_warnings": len(orientation_warnings),
        },
        "nodes": nodes,
        "faces": faces,
        "cells": cells,
        "boundaries": boundaries,
        "id_maps": {
            "nodes": [{"id": node_id_map[raw_id], "cgns_id": raw_id} for raw_id in raw_node_ids],
            "faces": [{"id": face_id_map[raw_id], "cgns_id": raw_id} for raw_id in raw_face_ids],
            "cells": [{"id": cell_id_map[raw_id], "cgns_id": raw_id} for raw_id in raw_cell_ids],
        },
        "orientation_warnings": orientation_warnings,
    }


def face_line(face):
    values = [len(face["node_ids"])] + face["node_ids"] + [face["cell1"], face["cell2"]]
    return " ".join(str(v) for v in values)


def write_mesh_txt(data, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cleanup_stale_boundary_files(data, out_dir)

    nodes_path = out_dir / "nodes.txt"
    with nodes_path.open("w", encoding="utf-8", newline="\n") as f:
        for node in data["nodes"]:
            f.write(
                f"{node['id']} {fmt_float(node['x'])} {fmt_float(node['y'])} {fmt_float(node['z'])}\n"
            )

    face_by_id = {face["id"]: face for face in data["faces"]}

    faces_path = out_dir / "faces.txt"
    with faces_path.open("w", encoding="utf-8", newline="\n") as f:
        for face in data["faces"]:
            f.write(face_line(face) + "\n")

    cells_path = out_dir / "cells.txt"
    with cells_path.open("w", encoding="utf-8", newline="\n") as f:
        for cell in data["cells"]:
            values = [len(cell["face_ids"])] + cell["face_ids"]
            f.write(" ".join(str(v) for v in values) + "\n")

    model_info_path = out_dir / "model_info.txt"
    with model_info_path.open("w", encoding="utf-8", newline="\n") as model_info:
        model_info.write("MODEL\n")
        model_info.write(f"zone\t{data['zone']}\n")
        model_info.write(f"nodes\t{len(data['nodes'])}\n")
        model_info.write(f"faces\t{len(data['faces'])}\n")
        model_info.write(f"cells\t{len(data['cells'])}\n")
        model_info.write(f"boundaries\t{len(data['boundaries'])}\n")
        model_info.write(f"orientation_warnings\t{len(data['orientation_warnings'])}\n")
        model_info.write("\nBOUNDARIES\n")
        model_info.write("boundary_name\tfile\tface_count\tnode_count\n")
        for boundary in data["boundaries"]:
            boundary_path = out_dir / boundary["txt_file"]
            boundary_node_ids = set()
            with boundary_path.open("w", encoding="utf-8", newline="\n") as f:
                for face_id in boundary["face_ids"]:
                    face = dict(face_by_id[face_id])
                    face["cell2"] = 0
                    boundary_node_ids.update(face["node_ids"])
                    f.write(face_line(face) + "\n")
            model_info.write(
                f"{boundary['name']}\t{boundary['txt_file']}\t"
                f"{len(boundary['face_ids'])}\t{len(boundary_node_ids)}\n"
            )

    maps_path = out_dir / "id_maps.txt"
    with maps_path.open("w", encoding="utf-8", newline="\n") as f:
        for section_name in ("nodes", "faces", "cells"):
            maps = data["id_maps"][section_name]
            f.write(f"{section_name.upper()} {len(maps)}\n")
            f.write("id cgns_id\n")
            for item in maps:
                f.write(f"{item['id']} {item['cgns_id']}\n")

    warnings_path = out_dir / "orientation_warnings.txt"
    with warnings_path.open("w", encoding="utf-8", newline="\n") as f:
        for warning in data["orientation_warnings"]:
            f.write(warning + "\n")

    return {
        "nodes": str(nodes_path),
        "faces": str(faces_path),
        "cells": str(cells_path),
        "model_info": str(model_info_path),
        "id_maps": str(maps_path),
        "orientation_warnings": str(warnings_path),
    }


def cleanup_stale_boundary_files(data, out_dir):
    reserved = {
        "nodes.txt",
        "faces.txt",
        "cells.txt",
        "model_info.txt",
        "id_maps.txt",
        "orientation_warnings.txt",
    }
    current_boundary_files = {boundary["txt_file"] for boundary in data["boundaries"]}
    legacy_files = {"topology.txt", "boundary_manifest.txt"}
    manifest = out_dir / "model_info.txt"
    legacy_manifest = out_dir / "boundary_manifest.txt"
    old_manifest_files = set()
    if manifest.exists():
        for line in manifest.read_text(encoding="utf-8").splitlines():
            if not line or line.startswith("boundary_name"):
                continue
            parts = line.split("\t")
            if len(parts) >= 3 and parts[1].endswith(".txt"):
                old_manifest_files.add(parts[1])
    if legacy_manifest.exists():
        for line in legacy_manifest.read_text(encoding="utf-8").splitlines()[1:]:
            parts = line.split("\t")
            if len(parts) >= 2 and parts[1].endswith(".txt"):
                old_manifest_files.add(parts[1])

    for path in out_dir.glob("*.txt"):
        if path.name in reserved or path.name in current_boundary_files:
            continue
        if path.name in legacy_files or path.name.startswith("boundary_") or path.name in old_manifest_files:
            path.unlink()


def main():
    if len(sys.argv) not in (2, 3, 4):
        print(
            "Usage: python parse_cgns_to_topology.py "
            "<mesh.cgns> [output.json] [info_dir]"
        )
        return 2

    cgns_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2]) if len(sys.argv) >= 3 else cgns_path.with_suffix(".topology.json")
    txt_dir = Path(sys.argv[3]) if len(sys.argv) == 4 else output_path.parent / "info"

    data = build_topology(cgns_path)
    txt_outputs = write_mesh_txt(data, txt_dir)
    data["txt_outputs"] = txt_outputs

    output_path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    counts = data["counts"]
    print(f"wrote {output_path}")
    print(f"wrote_txt_dir {txt_dir}")
    print(f"nodes={counts['nodes']} faces={counts['faces']} cells={counts['cells']} boundaries={counts['boundaries']}")
    print(f"orientation_warnings={counts['orientation_warnings']}")
    for boundary in data["boundaries"]:
        print(
            f"boundary {boundary['name']}: faces={len(boundary['face_ids'])} "
            f"file={boundary['txt_file']} missing={boundary['missing_face_matches']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

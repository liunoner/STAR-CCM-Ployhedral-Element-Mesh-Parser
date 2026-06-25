import json
import sys
from pathlib import Path


def read_int_line(line, context):
    try:
        return [int(x) for x in line.strip().split()]
    except ValueError as exc:
        raise ValueError(f"{context} contains non-integer values: {line!r}") from exc


def validate_json(data):
    errors = []
    warnings = []

    nodes = data.get("nodes", [])
    faces = data.get("faces", [])
    cells = data.get("cells", [])
    boundaries = data.get("boundaries", [])

    if not nodes:
        errors.append("nodes is empty")
    if not faces:
        errors.append("faces is empty")
    if not cells:
        errors.append("cells is empty")

    node_ids = {int(n.get("id")) for n in nodes}
    face_ids = {int(f.get("id")) for f in faces}
    cell_ids = {int(c.get("id")) for c in cells}

    for face in faces:
        fid = int(face.get("id"))
        face_nodes = [int(x) for x in face.get("node_ids", [])]
        face_cells = [int(x) for x in face.get("cell_ids", [])]
        if len(face_nodes) < 3:
            errors.append(f"face {fid} has fewer than 3 nodes")
        for nid in face_nodes:
            if nid not in node_ids:
                errors.append(f"face {fid} references missing node {nid}")
        if not face_cells:
            errors.append(f"face {fid} has no adjacent cell")
        if len(face_cells) > 2:
            warnings.append(f"face {fid} has more than 2 adjacent cells: {face_cells}")
        for cid in face_cells:
            if cid not in cell_ids:
                errors.append(f"face {fid} references missing cell {cid}")

    for cell in cells:
        cid = int(cell.get("id"))
        cell_faces = [int(x) for x in cell.get("face_ids", [])]
        if not cell_faces:
            errors.append(f"cell {cid} has no face ids")
        for fid in cell_faces:
            if fid not in face_ids:
                errors.append(f"cell {cid} references missing face {fid}")

    for boundary in boundaries:
        name = boundary.get("name", "<unnamed>")
        for fid in boundary.get("face_ids", []):
            if int(fid) not in face_ids:
                errors.append(f"boundary {name} references missing face {fid}")

    return errors, warnings


def validate_txt(data, txt_dir):
    errors = []
    warnings = []

    txt_dir = Path(txt_dir)
    if not txt_dir.exists():
        return [f"mesh TXT directory not found: {txt_dir}"], warnings

    node_count = int(data["counts"]["nodes"])
    face_count = int(data["counts"]["faces"])
    cell_count = int(data["counts"]["cells"])

    nodes_path = txt_dir / "nodes.txt"
    faces_path = txt_dir / "faces.txt"
    cells_path = txt_dir / "cells.txt"
    model_info_path = txt_dir / "model_info.txt"

    for path in (nodes_path, faces_path, cells_path, model_info_path, txt_dir / "id_maps.txt"):
        if not path.exists():
            errors.append(f"missing required TXT output: {path}")
    if errors:
        return errors, warnings

    node_lines = [line for line in nodes_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(node_lines) != node_count:
        errors.append(f"nodes.txt line count {len(node_lines)} != expected {node_count}")
    for expected_id, line in enumerate(node_lines, start=1):
        parts = line.split()
        if len(parts) != 4:
            errors.append(f"nodes.txt line {expected_id} should have 4 columns")
            continue
        if int(parts[0]) != expected_id:
            errors.append(f"nodes.txt line {expected_id} has node id {parts[0]}")
        for value in parts[1:]:
            float(value)

    face_lines = [line for line in faces_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not face_lines:
        errors.append("faces.txt is empty")
        return errors, warnings
    face_rows = face_lines[1:] if face_lines[0] == f"FACES {face_count}" else face_lines
    if len(face_rows) != face_count:
        errors.append(f"faces.txt row count {len(face_rows)} != expected {face_count}")

    cell_lines = [line for line in cells_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not cell_lines:
        errors.append("cells.txt is empty")
        return errors, warnings
    cell_rows = cell_lines[1:] if cell_lines[0] == f"CELLS {cell_count}" else cell_lines
    if len(cell_rows) != cell_count:
        errors.append(f"cells.txt row count {len(cell_rows)} != expected {cell_count}")

    valid_nodes = set(range(1, node_count + 1))
    valid_cells = set(range(1, cell_count + 1))
    valid_faces = set(range(1, face_count + 1))

    for face_index, line in enumerate(face_rows, start=1):
        values = read_int_line(line, f"topology face row {face_index}")
        if len(values) < 6:
            errors.append(f"faces.txt row {face_index} is too short")
            continue
        node_n = values[0]
        if len(values) != node_n + 3:
            errors.append(f"faces.txt row {face_index} length does not match node count")
            continue
        for nid in values[1:1 + node_n]:
            if nid not in valid_nodes:
                errors.append(f"faces.txt row {face_index} references invalid node {nid}")
        cell1, cell2 = values[-2], values[-1]
        if cell1 not in valid_cells:
            errors.append(f"faces.txt row {face_index} references invalid cell1 {cell1}")
        if cell2 != 0 and cell2 not in valid_cells:
            errors.append(f"faces.txt row {face_index} references invalid cell2 {cell2}")

    for cell_index, line in enumerate(cell_rows, start=1):
        values = read_int_line(line, f"topology cell row {cell_index}")
        if len(values) < 2:
            errors.append(f"cells.txt row {cell_index} is too short")
            continue
        face_n = values[0]
        if len(values) != face_n + 1:
            errors.append(f"cells.txt row {cell_index} length does not match face count")
            continue
        for fid in values[1:]:
            if fid not in valid_faces:
                errors.append(f"cells.txt row {cell_index} references invalid face {fid}")

    info_lines = [
        line for line in model_info_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if "MODEL" not in info_lines or "BOUNDARIES" not in info_lines:
        errors.append("model_info.txt missing MODEL or BOUNDARIES section")
        return errors, warnings
    expected_info = {
        "nodes": str(node_count),
        "faces": str(face_count),
        "cells": str(cell_count),
        "boundaries": str(len(data.get("boundaries", []))),
    }
    info_pairs = {}
    for line in info_lines:
        parts = line.split("\t")
        if len(parts) == 2:
            info_pairs[parts[0]] = parts[1]
    for key, value in expected_info.items():
        if info_pairs.get(key) != value:
            errors.append(f"model_info.txt {key}={info_pairs.get(key)} != expected {value}")

    try:
        boundary_header_index = info_lines.index("boundary_name\tfile\tface_count\tnode_count")
    except ValueError:
        errors.append("model_info.txt missing boundary table header")
        return errors, warnings

    manifest_face_total = 0
    for line in info_lines[boundary_header_index + 1:]:
        parts = line.split("\t")
        if len(parts) != 4:
            errors.append(f"bad model_info boundary row: {line}")
            continue
        boundary_name, filename, expected_count_text, expected_node_count_text = parts
        expected_count = int(expected_count_text)
        expected_node_count = int(expected_node_count_text)
        boundary_path = txt_dir / filename
        if not boundary_path.exists():
            errors.append(f"boundary file missing for {boundary_name}: {filename}")
            continue
        rows = [row for row in boundary_path.read_text(encoding="utf-8").splitlines() if row.strip()]
        node_ids = set()
        manifest_face_total += len(rows)
        if len(rows) != expected_count:
            errors.append(f"boundary {boundary_name} row count {len(rows)} != model_info {expected_count}")
        for i, row in enumerate(rows, start=1):
            values = read_int_line(row, f"boundary {boundary_name} row {i}")
            if len(values) < 6:
                errors.append(f"boundary {boundary_name} row {i} is too short")
                continue
            node_n = values[0]
            if len(values) != node_n + 3:
                errors.append(f"boundary {boundary_name} row {i} length does not match node count")
                continue
            node_ids.update(values[1:1 + node_n])
            if values[-1] != 0:
                errors.append(f"boundary {boundary_name} row {i} has second cell {values[-1]}, expected 0")
        if len(node_ids) != expected_node_count:
            errors.append(
                f"boundary {boundary_name} node count {len(node_ids)} != model_info {expected_node_count}"
            )

    expected_boundary_total = sum(len(b.get("face_ids", [])) for b in data.get("boundaries", []))
    if manifest_face_total != expected_boundary_total:
        errors.append(
            f"boundary file total {manifest_face_total} != JSON boundary total {expected_boundary_total}"
        )

    return errors, warnings


def main():
    if len(sys.argv) not in (2, 3):
        print("Usage: python src/validate_export.py <mesh_topology.json> [info_dir]")
        return 2

    json_path = Path(sys.argv[1])
    if not json_path.exists():
        print(f"ERROR: file not found: {json_path}")
        return 2

    data = json.loads(json_path.read_text(encoding="utf-8"))
    if len(sys.argv) == 3:
        txt_dir = Path(sys.argv[2])
    else:
        txt_dir = Path(data.get("txt_outputs", {}).get("nodes", "")).parent
        default_txt_dir = json_path.parent / "info"
        if str(txt_dir) == "." or (not txt_dir.exists() and default_txt_dir.exists()):
            txt_dir = default_txt_dir

    errors, warnings = validate_json(data)
    txt_errors, txt_warnings = validate_txt(data, txt_dir)
    errors.extend(txt_errors)
    warnings.extend(txt_warnings)

    counts = data.get("counts", {})
    print("STAR-CCM+ mesh export validation")
    print(f"schema: {data.get('schema', '<missing>')}")
    print(f"nodes: {counts.get('nodes', len(data.get('nodes', [])))}")
    print(f"faces: {counts.get('faces', len(data.get('faces', [])))}")
    print(f"cells: {counts.get('cells', len(data.get('cells', [])))}")
    print(f"boundaries: {counts.get('boundaries', len(data.get('boundaries', [])))}")
    print(f"txt_dir: {txt_dir}")
    print(f"errors: {len(errors)}")
    print(f"warnings: {len(warnings)}")

    if errors:
        print("\nERRORS")
        for item in errors[:100]:
            print(f"- {item}")
        if len(errors) > 100:
            print(f"- ... {len(errors) - 100} more")

    if warnings:
        print("\nWARNINGS")
        for item in warnings[:100]:
            print(f"- {item}")
        if len(warnings) > 100:
            print(f"- ... {len(warnings) - 100} more")

    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

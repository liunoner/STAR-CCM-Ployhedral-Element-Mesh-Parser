import argparse
from pathlib import Path


SIM_NAME = "XiaoWanRock"


def project_root():
    return Path(__file__).resolve().parent.parent


def parse_args():
    root = project_root()
    parser = argparse.ArgumentParser(
        description="Create a legacy VTK POLYDATA file from nodes/faces/cells TXT exports."
    )
    parser.add_argument(
        "sim_name",
        nargs="?",
        help="Optional simulation name or .sim path. Defaults to SIM_NAME in this script.",
    )
    parser.add_argument(
        "--info-dir",
        default=None,
        help="Directory containing nodes.txt, faces.txt, and cells.txt.",
    )
    parser.add_argument(
        "--vtk-dir",
        default=str(root / "vtk"),
        help="Directory where the VTK file will be written.",
    )
    parser.add_argument(
        "--output",
        help="Optional explicit VTK output path. Overrides --vtk-dir and sim name.",
    )
    parser.add_argument(
        "--scale",
        type=float,
        default=100.0,
        help="Coordinate scale factor. Use 100.0 to match the provided D3Mesh.vtk reference.",
    )
    parser.add_argument(
        "--keep-face-order",
        action="store_true",
        help="Write face nodes exactly as stored in faces.txt instead of matching the D3Mesh.vtk order.",
    )
    return parser.parse_args()


def normalize_sim_name(name):
    sim_name = Path(name).stem if name else SIM_NAME
    if not sim_name:
        raise SystemExit("ERROR: SIM_NAME is empty.")
    return sim_name


def split_data_lines(path):
    for line_no, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if parts and not parts[0].lstrip("-").isdigit():
            continue
        yield line_no, parts


def read_nodes(path):
    nodes = []
    expected_id = 1
    for line_no, parts in split_data_lines(path):
        if len(parts) != 4:
            raise ValueError(f"{path}:{line_no}: expected 'id x y z'")
        node_id = int(parts[0])
        if node_id != expected_id:
            raise ValueError(f"{path}:{line_no}: node id {node_id} != expected {expected_id}")
        nodes.append((float(parts[1]), float(parts[2]), float(parts[3])))
        expected_id += 1
    if not nodes:
        raise ValueError(f"{path}: no nodes found")
    return nodes


def read_faces(path, node_count):
    faces = []
    face_cells = []
    for line_no, parts in split_data_lines(path):
        if len(parts) < 4:
            raise ValueError(f"{path}:{line_no}: expected 'node_count node... cell1 cell2'")
        point_count = int(parts[0])
        expected_len = 1 + point_count + 2
        if len(parts) != expected_len:
            raise ValueError(f"{path}:{line_no}: expected {expected_len} columns, got {len(parts)}")

        node_ids = [int(value) for value in parts[1 : 1 + point_count]]
        for node_id in node_ids:
            if node_id < 1 or node_id > node_count:
                raise ValueError(f"{path}:{line_no}: node id {node_id} is outside 1..{node_count}")

        faces.append([node_id - 1 for node_id in node_ids])
        face_cells.append((int(parts[-2]), int(parts[-1])))
    if not faces:
        raise ValueError(f"{path}: no faces found")
    return faces, face_cells


def read_cells(path, face_count):
    cells = []
    for line_no, parts in split_data_lines(path):
        if len(parts) < 2:
            raise ValueError(f"{path}:{line_no}: expected 'face_count face_id...'")
        cell_face_count = int(parts[0])
        expected_len = 1 + cell_face_count
        if len(parts) != expected_len:
            raise ValueError(f"{path}:{line_no}: expected {expected_len} columns, got {len(parts)}")

        face_ids = [int(value) for value in parts[1:]]
        for face_id in face_ids:
            if face_id < 1 or face_id > face_count:
                raise ValueError(f"{path}:{line_no}: face id {face_id} is outside 1..{face_count}")
        cells.append(face_ids)
    if not cells:
        raise ValueError(f"{path}: no cells found")
    return cells


def vtk_output_path(args, root):
    if args.output:
        return Path(args.output)

    sim_name = normalize_sim_name(args.sim_name)
    return Path(args.vtk_dir) / f"{sim_name}.vtk"


def vtk_face_order(face, keep_face_order):
    if keep_face_order or len(face) <= 2:
        return face
    return [face[0]] + list(reversed(face[1:]))


def write_polydata_vtk(path, nodes, faces, face_cells, scale, keep_face_order):
    polygon_size = sum(1 + len(face) for face in faces)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8", newline="\n") as vtk:
        vtk.write("# vtk DataFile Version 2.0\n")
        vtk.write("vtk from starccm mesh txt\n")
        vtk.write("ASCII\n")
        vtk.write("DATASET POLYDATA\n")
        vtk.write(f"POINTS {len(nodes)} float\n")
        for x, y, z in nodes:
            vtk.write(f"{x * scale:.9g} {y * scale:.9g} {z * scale:.9g}\n")

        vtk.write(f"POLYGONS {len(faces)} {polygon_size}\n")
        for face in faces:
            ordered_face = vtk_face_order(face, keep_face_order)
            vtk.write(f"{len(ordered_face)} {' '.join(str(node_id) for node_id in ordered_face)}\n")

        vtk.write(f"CELL_DATA {len(faces)}\n")
        vtk.write("SCALARS face_id int 1\n")
        vtk.write("LOOKUP_TABLE default\n")
        for face_id in range(1, len(faces) + 1):
            vtk.write(f"{face_id}\n")

        vtk.write("SCALARS cell1 int 1\n")
        vtk.write("LOOKUP_TABLE default\n")
        for cell1, _cell2 in face_cells:
            vtk.write(f"{cell1}\n")

        vtk.write("SCALARS cell2 int 1\n")
        vtk.write("LOOKUP_TABLE default\n")
        for _cell1, cell2 in face_cells:
            vtk.write(f"{cell2}\n")


def main():
    args = parse_args()
    root = project_root()
    sim_name = normalize_sim_name(args.sim_name)
    info_dir = Path(args.info_dir) if args.info_dir else root / "res" / sim_name / "info"

    nodes_path = info_dir / "nodes.txt"
    faces_path = info_dir / "faces.txt"
    cells_path = info_dir / "cells.txt"
    for path in (nodes_path, faces_path, cells_path):
        if not path.exists():
            raise SystemExit(f"ERROR: missing required file: {path}")

    nodes = read_nodes(nodes_path)
    faces, face_cells = read_faces(faces_path, len(nodes))
    cells = read_cells(cells_path, len(faces))

    output_path = vtk_output_path(args, root)
    write_polydata_vtk(output_path, nodes, faces, face_cells, args.scale, args.keep_face_order)

    print(f"wrote {output_path}")
    print(f"points={len(nodes)} polygons={len(faces)} cells_checked={len(cells)} scale={args.scale:g}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

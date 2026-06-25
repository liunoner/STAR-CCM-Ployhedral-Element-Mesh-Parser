# STAR-CCM+ Mesh Parser

This project parses STAR-CCM+ mesh data, extracts mesh topology, writes fully readable TXT files, and generates VTK files for validation in ParaView.

It is intended for common STAR-CCM+ mesh types such as:

- Octree meshes
- Polyhedral meshes
- Prism-layer boundary meshes
- Hybrid cell meshes
- Three-dimensional volume meshes with multiple boundary surfaces

The goal is to convert STAR-CCM+ internal mesh data into open, inspectable files that can be reviewed manually, processed by scripts, and validated visually in ParaView.

## Features

- Run a STAR-CCM+ Java Macro to export a CGNS mesh file
- Parse CGNS mesh topology with Python
- Extract nodes, faces, cells, boundaries, and ID mappings
- Write mesh data to clear TXT files
- Group outputs by `.sim` model name to avoid overwriting results from other models
- Generate legacy VTK `POLYDATA` files for ParaView inspection
- Validate consistency across JSON, TXT, and boundary files

## Project Layout

```text
star/
  src/
    starccm_cgns_export_read_gui.java
    parse_cgns_to_topology.py
    validate_export.py
    create_vtk_from_info.py

  model/
    <sim_name>.sim
    *.cgns

  res/
    <sim_name>/
      mesh_export.cgns
      mesh_topology.json
      run_log.txt
      info/

  vtk/
    <sim_name>.vtk
```

`src` contains the Java Macro and Python utility scripts.

`model` contains STAR-CCM+ simulation files and manually preserved CGNS files.

`res` contains exported and parsed mesh results grouped by simulation name.

`vtk` contains ParaView validation files generated from `res/<sim_name>/info`.

## Requirements

- STAR-CCM+, used to run the Java Macro and export CGNS
- Python 3
- Python dependencies required by `src/parse_cgns_to_topology.py` for CGNS reading
- ParaView, optional, used to open generated `.vtk` files for visual validation

## Workflow

### 1. Export and Parse from STAR-CCM+

Run the STAR-CCM+ batch macro from a terminal, for example:

```powershell
& '<STARCCM_INSTALL>\star\bin\starccm+.bat' -batch '<PROJECT_DIR>\src\starccm_cgns_export_read_gui.java' '<PROJECT_DIR>\model\<sim_name>.sim'
```

Replace `<STARCCM_INSTALL>`, `<PROJECT_DIR>`, and `<sim_name>` with paths and names from your local setup.

The macro creates an output directory based on the active `.sim` model name:

```text
res/<sim_name>/
```

For example, `cube.sim` writes results to:

```text
res/cube/
```

### 2. Validate TXT Outputs

```powershell
python src\validate_export.py res\cube\mesh_topology.json
```

The validator automatically reads the sibling TXT directory:

```text
res/cube/info/
```

### 3. Generate a ParaView VTK File

Set `SIM_NAME` in `src/create_vtk_from_info.py`:

```python
SIM_NAME = "cube"
```

Then run:

```powershell
python src\create_vtk_from_info.py
```

You can also override the simulation name from the command line:

```powershell
python src\create_vtk_from_info.py cube
```

Output:

```text
vtk/cube.vtk
```

## Main Outputs

Each model uses this output directory:

```text
res/<sim_name>/
  mesh_export.cgns
  mesh_topology.json
  run_log.txt
  info/
```

The `info` directory contains:

```text
nodes.txt
faces.txt
cells.txt
<boundary_name>.txt
model_info.txt
id_maps.txt
orientation_warnings.txt
```

## TXT File Formats

`nodes.txt`:

```text
node_id x y z
```

`faces.txt`:

```text
node_count node1 node2 ... nodeN cell1 cell2
```

`cells.txt`:

```text
face_count face_index1 face_index2 ... face_indexM
```

Boundary files:

```text
node_count node1 node2 ... nodeN cell1 0
```

Notes:

- Node, face, and cell IDs are continuous 1-based IDs.
- Each row in `faces.txt` describes one mesh face, including face nodes and adjacent cells.
- Each row in `cells.txt` describes one volume cell, including all faces used by that cell.
- Boundary faces use `0` as the second cell ID.
- `model_info.txt` records model totals and per-boundary statistics.
- `id_maps.txt` records mappings between continuous IDs and original CGNS IDs.

## ParaView Validation

`create_vtk_from_info.py` generates a legacy VTK `POLYDATA` file from the TXT files:

- `POINTS` comes from `nodes.txt`
- `POLYGONS` comes from `faces.txt`
- `CELL_DATA` contains `face_id`, `cell1`, and `cell2`
- The default coordinate scale factor is `100.0`, matching the reference file `vtk/D3Mesh.vtk`

The generated `.vtk` file can be opened directly in ParaView. Use it to inspect mesh faces, color by `cell1` or `cell2`, and verify that STAR-CCM+ mesh topology was extracted correctly.

## GitHub Publishing Notes

Large model files, exported results, and VTK files can make the repository heavy. For public GitHub repositories, consider storing large `.sim`, `.cgns`, `res/`, and `vtk/` files in Releases, external storage, or Git LFS when the project grows.

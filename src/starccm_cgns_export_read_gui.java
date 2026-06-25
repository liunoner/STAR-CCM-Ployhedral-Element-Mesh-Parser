import star.common.*;

import javax.swing.BorderFactory;
import javax.swing.JButton;
import javax.swing.JFrame;
import javax.swing.JLabel;
import javax.swing.JOptionPane;
import javax.swing.JPanel;
import javax.swing.JScrollPane;
import javax.swing.JTable;
import javax.swing.JTextArea;
import javax.swing.SwingUtilities;
import javax.swing.table.DefaultTableModel;
import java.awt.BorderLayout;
import java.awt.Desktop;
import java.awt.Dimension;
import java.awt.FlowLayout;
import java.awt.Font;
import java.awt.GraphicsEnvironment;
import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.io.File;
import java.io.FileReader;
import java.io.FileWriter;
import java.io.InputStreamReader;
import java.io.PrintWriter;
import java.util.ArrayList;
import java.util.Collection;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class starccm_cgns_export_read_gui extends StarMacro {

    private PrintWriter log;

    public void execute() {
        Simulation sim = getActiveSimulation();
        String simName = getSimulationFolderName(sim);
        File outDir = new File(new File(getProjectRoot(), "res"), simName);
        if (!outDir.exists()) {
            outDir.mkdirs();
        }

        try {
            log = new PrintWriter(new BufferedWriter(new FileWriter(new File(outDir, "run_log.txt"))));
            log.println("STAR-CCM+ CGNS export/read/gui macro");
            log.println("Simulation name: " + simName);
            log.println("Output directory: " + outDir.getAbsolutePath());

            File cgnsFile = new File(outDir, "mesh_export.cgns");
            File jsonFile = new File(outDir, "mesh_topology.json");
            File txtDir = new File(outDir, "info");

            ExportSummary exportSummary = exportCgns(sim, cgnsFile);
            MeshSummary meshSummary = parseCgnsWithPython(cgnsFile, jsonFile, txtDir);

            log.println("Parsed mesh summary:");
            log.println("nodes=" + meshSummary.nodes);
            log.println("faces=" + meshSummary.faces);
            log.println("cells=" + meshSummary.cells);
            log.println("boundaries=" + meshSummary.boundaries.size());
            log.println("txt_dir=" + txtDir.getAbsolutePath());

            if (GraphicsEnvironment.isHeadless()) {
                sim.println("CGNS export/read completed in headless mode.");
                sim.println("JSON: " + jsonFile.getAbsolutePath());
                sim.println("Mesh TXT: " + txtDir.getAbsolutePath());
                sim.println("nodes=" + meshSummary.nodes
                        + ", faces=" + meshSummary.faces
                        + ", cells=" + meshSummary.cells
                        + ", boundaries=" + meshSummary.boundaries.size());
            } else {
                showGui(exportSummary, meshSummary, cgnsFile, jsonFile, txtDir, outDir);
            }
        } catch (Exception ex) {
            if (log != null) {
                ex.printStackTrace(log);
            }
            sim.println("CGNS export/read/gui failed: " + ex.getMessage());
            if (!GraphicsEnvironment.isHeadless()) {
                JOptionPane.showMessageDialog(
                        null,
                        ex.getMessage(),
                        "CGNS Export/Read Failed",
                        JOptionPane.ERROR_MESSAGE);
            }
        } finally {
            if (log != null) {
                log.close();
            }
        }
    }

    private ExportSummary exportCgns(Simulation sim, File cgnsFile) throws Exception {
        sim.loadCaeExport();

        Collection<Region> regions = sim.getRegionManager().getRegions();
        List<Boundary> boundaries = new ArrayList<Boundary>();
        for (Region region : regions) {
            boundaries.addAll(region.getBoundaryManager().getBoundaries());
        }

        sim.getExportManager().export(
                cgnsFile.getAbsolutePath(),
                regions,
                boundaries,
                new ArrayList<Part>(),
                new ArrayList<FieldFunction>(),
                false);

        ExportSummary summary = new ExportSummary();
        summary.regionCount = regions.size();
        summary.boundaryCount = boundaries.size();
        summary.cgnsBytes = cgnsFile.length();

        log.println("CGNS export completed.");
        log.println("file=" + cgnsFile.getAbsolutePath());
        log.println("regions=" + summary.regionCount);
        log.println("boundaries=" + summary.boundaryCount);
        log.println("bytes=" + summary.cgnsBytes);
        return summary;
    }

    private MeshSummary parseCgnsWithPython(File cgnsFile, File jsonFile, File txtDir) throws Exception {
        File parser = findParserScript();
        if (parser == null) {
            throw new Exception("Cannot find parse_cgns_to_topology.py. Keep this macro in the src directory.");
        }

        List<String> command = new ArrayList<String>();
        command.add("python");
        command.add(parser.getAbsolutePath());
        command.add(cgnsFile.getAbsolutePath());
        command.add(jsonFile.getAbsolutePath());
        command.add(txtDir.getAbsolutePath());

        ProcessBuilder pb = new ProcessBuilder(command);
        pb.redirectErrorStream(true);
        Process process = pb.start();

        StringBuilder output = new StringBuilder();
        BufferedReader reader = new BufferedReader(new InputStreamReader(process.getInputStream()));
        String line;
        while ((line = reader.readLine()) != null) {
            output.append(line).append("\n");
            log.println("[parser] " + line);
        }

        int exitCode = process.waitFor();
        if (exitCode != 0) {
            throw new Exception("CGNS parser failed with exit code " + exitCode + "\n" + output);
        }
        if (!jsonFile.exists()) {
            throw new Exception("CGNS parser completed but JSON was not created: " + jsonFile.getAbsolutePath());
        }

        MeshSummary summary = readMeshSummary(jsonFile);
        summary.txtDir = txtDir.getAbsolutePath();
        return summary;
    }

    private File findParserScript() {
        File projectRoot = getProjectRoot();
        String[] candidates = new String[] {
                resolvePath("parse_cgns_to_topology.py"),
                resolvePath("src/parse_cgns_to_topology.py"),
                new File(projectRoot, "src/parse_cgns_to_topology.py").getAbsolutePath(),
                new File("src/parse_cgns_to_topology.py").getAbsolutePath(),
                new File("parse_cgns_to_topology.py").getAbsolutePath()
        };
        for (String candidate : candidates) {
            File file = new File(candidate);
            if (file.exists()) {
                return file;
            }
        }
        return null;
    }

    private File getProjectRoot() {
        try {
            File resolved = new File(resolvePath(".")).getCanonicalFile();
            if ("src".equalsIgnoreCase(resolved.getName())) {
                return resolved.getParentFile();
            }
            if (new File(resolved, "src").exists()) {
                return resolved;
            }
            File parent = resolved.getParentFile();
            if (parent != null && new File(parent, "src").exists()) {
                return parent;
            }
            return resolved;
        } catch (Exception ex) {
            return new File(".").getAbsoluteFile();
        }
    }

    private String getSimulationFolderName(Simulation sim) {
        String name = sim.getPresentationName();
        if (name == null || name.trim().length() == 0) {
            name = "simulation";
        }
        name = name.trim();
        if (name.toLowerCase().endsWith(".sim")) {
            name = name.substring(0, name.length() - 4);
        }
        name = name.replaceAll("[\\\\/:*?\"<>|]+", "_");
        name = name.replaceAll("\\s+", "_");
        name = name.replaceAll("_+", "_");
        name = name.replaceAll("^_+|_+$", "");
        if (name.length() == 0) {
            name = "simulation";
        }
        return name;
    }

    private MeshSummary readMeshSummary(File jsonFile) throws Exception {
        String text = readText(jsonFile);

        MeshSummary summary = new MeshSummary();
        summary.schema = matchString(text, "\"schema\"\\s*:\\s*\"([^\"]+)\"");
        summary.source = matchString(text, "\"source\"\\s*:\\s*\"([^\"]+)\"");
        summary.zone = matchString(text, "\"zone\"\\s*:\\s*\"([^\"]+)\"");
        summary.nodes = matchInt(text, "\"nodes\"\\s*:\\s*(\\d+)");
        summary.faces = matchInt(text, "\"faces\"\\s*:\\s*(\\d+)");
        summary.cells = matchInt(text, "\"cells\"\\s*:\\s*(\\d+)");

        Pattern boundaryPattern = Pattern.compile(
                "\\{\"name\"\\s*:\\s*\"([^\"]+)\"\\s*,\\s*\"source_element_range\"\\s*:\\s*\\[(\\d+)\\s*,\\s*(\\d+)\\]\\s*,\\s*\"face_ids\"\\s*:\\s*\\[(.*?)\\]\\s*,\\s*\"missing_face_matches\"\\s*:\\s*(\\d+)(?:\\s*,\\s*\"txt_file\"\\s*:\\s*\"([^\"]+)\")?\\}",
                Pattern.DOTALL);
        Matcher matcher = boundaryPattern.matcher(text);
        while (matcher.find()) {
            BoundarySummary boundary = new BoundarySummary();
            boundary.name = matcher.group(1);
            boundary.startFaceId = Integer.parseInt(matcher.group(2));
            boundary.endFaceId = Integer.parseInt(matcher.group(3));
            boundary.faceCount = countJsonArrayItems(matcher.group(4));
            boundary.missingFaceMatches = Integer.parseInt(matcher.group(5));
            boundary.txtFile = matcher.group(6) == null ? "" : matcher.group(6);
            summary.boundaries.add(boundary);
        }

        return summary;
    }

    private String readText(File file) throws Exception {
        StringBuilder sb = new StringBuilder();
        BufferedReader reader = new BufferedReader(new FileReader(file));
        try {
            String line;
            while ((line = reader.readLine()) != null) {
                sb.append(line).append("\n");
            }
        } finally {
            reader.close();
        }
        return sb.toString();
    }

    private int countJsonArrayItems(String arrayBody) {
        String trimmed = arrayBody.trim();
        if (trimmed.length() == 0) {
            return 0;
        }
        int count = 1;
        for (int i = 0; i < trimmed.length(); i++) {
            if (trimmed.charAt(i) == ',') {
                count++;
            }
        }
        return count;
    }

    private int matchInt(String text, String regex) {
        Matcher matcher = Pattern.compile(regex).matcher(text);
        if (!matcher.find()) {
            return 0;
        }
        return Integer.parseInt(matcher.group(1));
    }

    private String matchString(String text, String regex) {
        Matcher matcher = Pattern.compile(regex).matcher(text);
        if (!matcher.find()) {
            return "";
        }
        return matcher.group(1);
    }

    private void showGui(final ExportSummary exportSummary, final MeshSummary meshSummary,
                         final File cgnsFile, final File jsonFile, final File txtDir, final File outDir) {
        SwingUtilities.invokeLater(new Runnable() {
            public void run() {
                JFrame frame = new JFrame("STAR-CCM+ CGNS Mesh Information");
                frame.setDefaultCloseOperation(JFrame.DISPOSE_ON_CLOSE);
                frame.setLayout(new BorderLayout(10, 10));

                JPanel summaryPanel = new JPanel(new BorderLayout(8, 8));
                summaryPanel.setBorder(BorderFactory.createEmptyBorder(12, 12, 0, 12));

                JLabel title = new JLabel("CGNS Mesh Export and Read Result");
                title.setFont(title.getFont().deriveFont(Font.BOLD, 16.0f));
                summaryPanel.add(title, BorderLayout.NORTH);

                JTextArea summaryText = new JTextArea();
                summaryText.setEditable(false);
                summaryText.setFont(new Font(Font.MONOSPACED, Font.PLAIN, 13));
                summaryText.setText(
                        "Schema:     " + meshSummary.schema + "\n"
                                + "Zone:       " + meshSummary.zone + "\n"
                                + "Regions:    " + exportSummary.regionCount + "\n"
                                + "Nodes:      " + meshSummary.nodes + "\n"
                                + "Faces:      " + meshSummary.faces + "\n"
                                + "Cells:      " + meshSummary.cells + "\n"
                                + "Boundaries: " + meshSummary.boundaries.size() + "\n"
                                + "CGNS file:  " + cgnsFile.getAbsolutePath() + "\n"
                                + "JSON file:  " + jsonFile.getAbsolutePath() + "\n"
                                + "TXT dir:    " + txtDir.getAbsolutePath());
                summaryPanel.add(summaryText, BorderLayout.CENTER);
                frame.add(summaryPanel, BorderLayout.NORTH);

                DefaultTableModel model = new DefaultTableModel(
                        new Object[] {"Boundary", "Face Count", "Start Face ID", "End Face ID", "Missing Matches", "TXT File"},
                        0);
                for (BoundarySummary boundary : meshSummary.boundaries) {
                    model.addRow(new Object[] {
                            boundary.name,
                            boundary.faceCount,
                            boundary.startFaceId,
                            boundary.endFaceId,
                            boundary.missingFaceMatches,
                            boundary.txtFile
                    });
                }
                JTable table = new JTable(model);
                table.setAutoCreateRowSorter(true);
                frame.add(new JScrollPane(table), BorderLayout.CENTER);

                JPanel buttonPanel = new JPanel(new FlowLayout(FlowLayout.RIGHT));
                JButton openFolder = new JButton("Open Output Folder");
                openFolder.addActionListener(e -> openFile(outDir));
                JButton openTxtFolder = new JButton("Open TXT Folder");
                openTxtFolder.addActionListener(e -> openFile(txtDir));
                JButton openJson = new JButton("Open JSON");
                openJson.addActionListener(e -> openFile(jsonFile));
                JButton close = new JButton("Close");
                close.addActionListener(e -> frame.dispose());
                buttonPanel.add(openFolder);
                buttonPanel.add(openTxtFolder);
                buttonPanel.add(openJson);
                buttonPanel.add(close);
                frame.add(buttonPanel, BorderLayout.SOUTH);

                frame.setMinimumSize(new Dimension(860, 520));
                frame.setLocationRelativeTo(null);
                frame.setVisible(true);
            }
        });
    }

    private void openFile(File file) {
        try {
            if (Desktop.isDesktopSupported()) {
                Desktop.getDesktop().open(file);
            }
        } catch (Exception ex) {
            JOptionPane.showMessageDialog(null, ex.getMessage(), "Open File Failed", JOptionPane.ERROR_MESSAGE);
        }
    }

    private static class ExportSummary {
        int regionCount;
        int boundaryCount;
        long cgnsBytes;
    }

    private static class MeshSummary {
        String schema = "";
        String source = "";
        String zone = "";
        String txtDir = "";
        int nodes;
        int faces;
        int cells;
        List<BoundarySummary> boundaries = new ArrayList<BoundarySummary>();
    }

    private static class BoundarySummary {
        String name;
        int faceCount;
        int startFaceId;
        int endFaceId;
        int missingFaceMatches;
        String txtFile = "";
    }
}

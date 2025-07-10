import FreeCADGui  # type: ignore
from SatelliteImporter import ImportSatellite, UpdateSatellite


class SatelliteImporterWorkbench(FreeCADGui.Workbench):
    MenuText = "Satellite Importer"
    ToolTip = "Workbench for importing satellite structures"
    Icon = r"C:\git\VirtualSatellite-FreeCAD\Icons\satellite.svg"

    def Initialize(self):
        self.appendToolbar("Satellite", ["ImportSatellite", "UpdateSatellite"])
        self.appendMenu("Satellite", ["ImportSatellite", "UpdateSatellite"])

    def GetClassName(self):
        return "Gui::PythonWorkbench"


FreeCADGui.addWorkbench(SatelliteImporterWorkbench())

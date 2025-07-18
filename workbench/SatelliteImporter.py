import FreeCAD
import FreeCADGui
import json
import os
from PySide import QtGui
import Part
import requests
from config import BASE_URL, USERNAME, PASSWORD
import time
import traceback

# --- Configuration ---
PROJECT_DIR = r"C:\git\VirtualSatellite5_FreeCAD"
JSON_PATH = os.path.join(PROJECT_DIR, "satellite_structure.json")
API_SESSION = None


# --- AUTHENTICATION AND API HELPERS ---
def get_auth_session():
    """Establishes and caches an authenticated session with the server."""
    global API_SESSION
    if API_SESSION is None:
        API_SESSION = requests.Session()
        login_url = f"{BASE_URL}/api/authorize"
        try:
            response = API_SESSION.post(
                login_url, json={"username": USERNAME, "password": PASSWORD}
            )
            response.raise_for_status()
            if 'access_token' not in response.json():
                raise Exception("Login failed: No access token received")
        except Exception as e:
            msg = f"Could not authenticate with server:\n{e}"
            QtGui.QMessageBox.critical(None, "Authentication Failed", msg)
            API_SESSION = None  # Reset on failure
            return None
    return API_SESSION


def get_projects():
    """Fetches a list of projects from the server."""
    session = get_auth_session()
    if not session:
        return []
    url = f"{BASE_URL}/api/projects"
    try:
        response = session.get(url)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error fetching projects: {e}")
        return []


# --- Universal Helper ---
def get_numeric_value(prop_val):
    """
    Safely gets the numeric value from a FreeCAD property, which could be a
    Quantity object or a standard float/int. Returns the value in FreeCAD's
    internal base unit (mm for length, degrees for angle).
    """
    return prop_val.Value if hasattr(prop_val, 'Value') else prop_val


# --- Main FeaturePython Class ---
class SatellitePart:
    """A proxy class to control the behavior of a satellite part."""
    def __init__(self, obj):
        obj.Proxy = self
        self.Type = "SatellitePart"
        obj.addProperty(
            "App::PropertyBool", "Updating", "Satellite",
            "Internal update flag"
        ).Updating = True
        self.init_properties(obj)
        obj.Updating = False

    def init_properties(self, obj):
        """Adds all necessary properties to the FreeCAD object."""
        obj.addProperty("App::PropertyString", "UUID",
                        "Satellite", "Component ID")
        obj.addProperty("App::PropertyString", "ShapeType",
                        "Satellite", "Shape type")
        obj.addProperty(
            "App::PropertyInteger", "ColorValue",
            "Satellite", "Part color"
        ).setEditorMode("ColorValue", 1)
        obj.addProperty(
            "App::PropertyFloat", "Transparency",
            "Satellite", "Part transparency"
        )

        # Use unit-aware properties for correct UI display
        props_len = [
            "posX", "posY", "posZ", "LengthX", "LengthY", "LengthZ", "Radius",
            "CylinderHeight", "Radius1", "Radius2", "ConeHeight"
        ]
        props_ang = ["rotX", "rotY", "rotZ"]

        for prop in props_len:
            if not hasattr(obj, prop):
                obj.addProperty("App::PropertyLength", prop, "Satellite")
        for prop in props_ang:
            if not hasattr(obj, prop):
                obj.addProperty("App::PropertyAngle", prop, "Satellite")

    def onChanged(self, obj, prop):
        """Called when a property of the object is changed."""
        if obj.Updating:
            return

        shape_props = [
            "LengthX", "LengthY", "LengthZ", "Radius", "CylinderHeight",
            "Radius1", "Radius2", "ConeHeight"
        ]
        placement_props = ["posX", "posY", "posZ", "rotX", "rotY", "rotZ"]

        if prop in shape_props:
            self.build_shape(obj)
        elif prop in placement_props:
            self.update_placement(obj)

        if FreeCAD.GuiUp and hasattr(obj, 'ViewObject'):
            if prop == "Transparency":
                trans_val = get_numeric_value(obj.Transparency)
                obj.ViewObject.Transparency = int(trans_val * 100)
            elif prop == "ColorValue":
                obj.ViewObject.ShapeColor = get_color(obj.ColorValue)
            obj.ViewObject.update()

    def update_placement(self, obj):
        """Recalculates and sets the object's placement from its properties."""
        try:
            rotation = FreeCAD.Rotation(
                get_numeric_value(obj.rotX),
                get_numeric_value(obj.rotY),
                get_numeric_value(obj.rotZ)
            )
            position = FreeCAD.Vector(
                get_numeric_value(obj.posX),
                get_numeric_value(obj.posY),
                get_numeric_value(obj.posZ)
            )
            obj.Placement = FreeCAD.Placement(position, rotation)
        except Exception as e:
            print(f"Error updating placement for {obj.Label}: {e}")

    def build_shape(self, obj):
        """Rebuilds the object's geometry based
        on its ShapeType and dimensions."""
        try:
            shape_type = obj.ShapeType
            if shape_type == "BOX":
                obj.Shape = create_box(obj.LengthX, obj.LengthY, obj.LengthZ)
            elif shape_type == "CYLINDER":
                obj.Shape = create_cylinder(obj.Radius, obj.CylinderHeight)
            elif shape_type == "SPHERE":
                obj.Shape = create_sphere(obj.Radius)
            elif shape_type == "CONE":
                obj.Shape = create_cone(obj.Radius1, obj.Radius2,
                                        obj.ConeHeight)
            else:
                obj.Shape = create_none_shape()
        except Exception as e:
            print(f"Error rebuilding shape for {obj.Label}: {e}")
            obj.Shape = create_none_shape()

    def execute(self, obj):
        """Called when obj.recompute() is executed."""
        self.build_shape(obj)


# --- View Provider ---
class SatellitePartViewProvider:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.ViewObject = vobj
        self.updateData(vobj.Object, "ColorValue")
        self.updateData(vobj.Object, "Transparency")

    def updateData(self, fp, prop):
        if prop == "ColorValue":
            self.ViewObject.ShapeColor = get_color(fp.ColorValue)
        elif prop == "Transparency":
            trans_val = get_numeric_value(fp.Transparency)
            self.ViewObject.Transparency = int(trans_val * 100)

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        return None


# --- Shape Creation Helpers ---
def create_box(len, width, height):
    """Creates a box shape with the given dimensions."""
    len, width, height = get_numeric_value(len), get_numeric_value(width),
    get_numeric_value(width)
    if all(d > 1e-9 for d in (len, width, width)):
        return Part.makeBox(len, width, height,
                            FreeCAD.Vector(-len/2, -width/2, -height/2))
    return create_none_shape()


def create_cylinder(r, h):
    r, h = get_numeric_value(r), get_numeric_value(h)
    if all(d > 1e-9 for d in (r, h)):
        return Part.makeCylinder(r, h, FreeCAD.Vector(0, 0, -h/2))
    return create_none_shape()


def create_sphere(r):
    r = get_numeric_value(r)
    if r > 1e-9:
        return Part.makeSphere(r)
    return create_none_shape()


def create_cone(r1, r2, h):
    r1, r2, h = get_numeric_value(r1), get_numeric_value(r2),
    get_numeric_value(h)
    if h > 1e-9 and (r1 > 1e-9 or r2 > 1e-9):
        return Part.makeCone(r1, r2, h, FreeCAD.Vector(0, 0, -h/2))
    return create_none_shape()


def create_none_shape():
    return Part.makeBox(0.001, 0.001, 0.001)


def get_color(color_int):
    r = ((color_int >> 16) & 0xFF) / 255.0
    g = ((color_int >> 8) & 0xFF) / 255.0
    b = (color_int & 0xFF) / 255.0
    return (r, g, b)


# --- CORRECTED HIERARCHICAL IMPORT LOGIC ---
def create_local_placement(node):
    """Creates a LOCAL placement. Converts meters from JSON to mm for FreeCAD."""
    pos_x_m = float(node.get("posX", 0))
    pos_y_m = float(node.get("posY", 0))
    pos_z_m = float(node.get("posZ", 0))
    rot_x_deg = float(node.get("rotX", 0))
    rot_y_deg = float(node.get("rotY", 0))
    rot_z_deg = float(node.get("rotZ", 0))

    position = FreeCAD.Vector(pos_x_m * 1000, pos_y_m * 1000, pos_z_m * 1000)
    rotation = FreeCAD.Rotation(rot_x_deg, rot_y_deg, rot_z_deg)
    return FreeCAD.Placement(position, rotation)


def build_fc_tree_recursively(node_data, parent_fc_obj, parts_dict):
    """Recursively builds the FreeCAD object tree."""
    doc = parent_fc_obj.Document
    is_part = "partUuid" in node_data and not node_data.get("children")
    fc_obj = None

    if is_part:
        part_uuid = node_data["partUuid"]
        if part_uuid not in parts_dict:
            return
        part_info = parts_dict[part_uuid]

        fc_obj = doc.addObject("Part::FeaturePython", f"Part_{node_data['uuid']}")
        SatellitePart(fc_obj)
        if FreeCAD.GuiUp:
            SatellitePartViewProvider(fc_obj.ViewObject)

        fc_obj.Updating = True
        fc_obj.Label = node_data['name']
        fc_obj.UUID = node_data['uuid']
        fc_obj.ShapeType = part_info.get("shape", "BOX").upper()
        fc_obj.ColorValue = part_info.get("color", 12632256)
        fc_obj.Transparency = float(node_data.get("transparency", 0.0)) / 100.0

        shape_type = fc_obj.ShapeType
        if shape_type == "BOX":
            fc_obj.LengthX = part_info.get("lengthX", 0.1) * 1000
            fc_obj.LengthY = part_info.get("lengthY", 0.1) * 1000
            fc_obj.LengthZ = part_info.get("lengthZ", 0.1) * 1000
        elif shape_type == "CYLINDER":
            fc_obj.Radius = part_info.get("radius", 0.05) * 1000
            fc_obj.CylinderHeight = part_info.get("lengthY", 0.1) * 1000
        elif shape_type == "SPHERE":
            fc_obj.Radius = part_info.get("radius", 0.05) * 1000
        elif shape_type == "CONE":
            fc_obj.Radius1 = part_info.get("radius1", 0.05) * 1000
            fc_obj.Radius2 = part_info.get("radius2", 0) * 1000
            fc_obj.ConeHeight = part_info.get("coneHeight", 0.1) * 1000

        fc_obj.Placement = create_local_placement(node_data)
        fc_obj.Updating = False
    else:  # It's an assembly
        fc_obj = doc.addObject("App::Part", f"Assy_{node_data['uuid']}")
        fc_obj.Label = node_data['name']
        if not hasattr(fc_obj, "UUID"):
            fc_obj.addProperty("App::PropertyString", "UUID", "Satellite")
        fc_obj.UUID = node_data["uuid"]
        fc_obj.Placement = create_local_placement(node_data)

        for child_node in node_data.get("children", []):
            build_fc_tree_recursively(child_node, fc_obj, parts_dict)

    if fc_obj:
        parent_fc_obj.addObject(fc_obj)


def import_satellite(filename, project_id, target_doc=None):
    """Imports satellite structure, building the hierarchical model."""
    try:
        print(f"Importing satellite from: {filename}")
        if not os.path.exists(filename):
            msg = f"JSON file not found at:\n{filename}"
            QtGui.QMessageBox.critical(None, "File Not Found", msg)
            return False

        if target_doc is None:
            doc = FreeCAD.ActiveDocument
            if doc is None:
                doc = FreeCAD.newDocument("Satellite")
        else:
            doc = target_doc

        with open(filename) as f:
            data = json.load(f)

        if not hasattr(doc, "SatelliteProjectID"):
            doc.addProperty("App::PropertyString",
                            "SatelliteProjectID", "Satellite")
        doc.SatelliteProjectID = str(project_id)
        if not hasattr(doc, "SatelliteModelID"):
            doc.addProperty("App::PropertyString",
                            "SatelliteModelID", "Satellite")
        doc.SatelliteModelID = str(data["Products"]["uuid"])
        if not hasattr(doc, "SatelliteJSONPath"):
            doc.addProperty("App::PropertyString",
                            "SatelliteJSONPath", "Satellite")
        doc.SatelliteJSONPath = filename
        if not hasattr(doc, "SatelliteTimestamp"):
            doc.addProperty("App::PropertyFloat",
                            "SatelliteTimestamp", "Satellite")
        doc.SatelliteTimestamp = data.get("timestamp", time.time())

        parts_dict = {part["uuid"]: part for part in data["Parts"]}
        root_node_data = data["Products"]

        root_fc_obj = doc.addObject("App::Part", f"Assy_{root_node_data['uuid']}")
        root_fc_obj.Label = root_node_data['name']
        if not hasattr(root_fc_obj, "UUID"):
            root_fc_obj.addProperty("App::PropertyString", "UUID", "Satellite")
        root_fc_obj.UUID = root_node_data["uuid"]
        root_fc_obj.Placement = create_local_placement(root_node_data)

        for child_node in root_node_data.get("children", []):
            build_fc_tree_recursively(child_node, root_fc_obj, parts_dict)

        doc.recompute()
        if FreeCAD.GuiUp:
            FreeCADGui.SendMsgToActiveView("ViewFit")
        msg = f"Satellite structure imported from:\n{filename}"
        QtGui.QMessageBox.information(
            QtGui.QApplication.activeWindow(), "Import Successful", msg
        )
        return True
    except Exception as e:
        msg = (
            f"Failed to import satellite structure:\n{str(e)}\n\n"
            f"Traceback:\n{traceback.format_exc()}"
        )
        QtGui.QMessageBox.critical(
            QtGui.QApplication.activeWindow(), "Import Error", msg
        )
        return False


# --- UPDATE LOGIC (WITH FIXES FOR FALSE POSITIVES) ---
def find_satellite_objects(doc):
    """Finds all satellite objects in the document."""
    return [obj for obj in doc.Objects if hasattr(obj, "UUID")]


def get_object_by_uuid(doc, uuid):
    """Finds an object by its UUID."""
    for obj in doc.Objects:
        if hasattr(obj, "UUID") and obj.UUID == uuid:
            return obj
    return None


def update_part_properties(obj, node, part_data):
    """Compares properties and updates if changed. Returns True if changed."""
    changed = False
    obj.Updating = True
    try:
        new_placement = create_local_placement(node)
        if not obj.Placement.isSame(new_placement, 1e-6):
            obj.Placement = new_placement
            changed = True

        if obj.ColorValue != part_data.get("color", 12632256):
            obj.ColorValue = part_data.get("color", 12632256)
            changed = True
        trans_val = float(node.get("transparency", 0)) / 100.0
        if abs(get_numeric_value(obj.Transparency) - trans_val) > 1e-6:
            obj.Transparency = trans_val
            changed = True

        new_shape_type = part_data.get("shape", "BOX").upper()
        if obj.ShapeType != new_shape_type:
            obj.ShapeType = new_shape_type
            changed = True

        if new_shape_type == "BOX":
            props = [
                ("LengthX", part_data.get("lengthX", 0.1)),
                ("LengthY", part_data.get("lengthY", 0.1)),
                ("LengthZ", part_data.get("lengthZ", 0.1)),
            ]
            for prop, val_m in props:
                if abs(get_numeric_value(getattr(obj, prop)) - val_m * 1000) > 1e-6:
                    setattr(obj, prop, val_m * 1000)
                    changed = True
        # Add other shapes here...

        if changed:
            obj.recompute()
    finally:
        obj.Updating = False
    return changed


def update_satellite_document(doc, updated_data):
    """Incrementally updates the satellite structure in the document."""
    try:
        def normalize_uuid(uuid):
            return str(uuid).strip().lower() if uuid else ""

        parts = updated_data.get("Parts", [])
        updated_parts = {normalize_uuid(p.get("uuid")): p for p in parts}
        updated_nodes = {}

        def index_nodes(node):
            if node and isinstance(node, dict):
                uuid = normalize_uuid(node.get("uuid"))
                if uuid:
                    updated_nodes[uuid] = node
                for child in node.get("children", []):
                    index_nodes(child)
        index_nodes(updated_data.get("Products"))

        existing_uuids = {normalize_uuid(o.UUID) for o in
                          find_satellite_objects(doc)}
        updated_uuids = set(updated_nodes.keys())
        uuids_to_remove = existing_uuids - updated_uuids
        removed = 0
        for obj_uuid in uuids_to_remove:
            obj = get_object_by_uuid(doc, obj_uuid)
            if obj:
                try:
                    doc.removeObject(obj.Name)
                    removed += 1
                except Exception as e:
                    print(f"Error removing object {obj.Name}: {str(e)}")

        added, updated, moved = 0, 0, 0

        def process_node_for_update(node_data, parent_fc_obj):
            nonlocal added, updated, moved
            uuid = normalize_uuid(node_data.get("uuid"))
            if not uuid:
                return

            obj = get_object_by_uuid(doc, uuid)
            is_part = "partUuid" in node_data and not node_data.get("children")

            if not obj:
                build_fc_tree_recursively(node_data, parent_fc_obj,
                                          updated_parts)
                added += 1
            else:
                if obj.getParent() != parent_fc_obj:
                    parent_fc_obj.addObject(obj)
                    moved += 1

                prop_changed = False
                if is_part:
                    part_uuid = normalize_uuid(node_data.get("partUuid"))
                    part_info = updated_parts.get(part_uuid)
                    if part_info and update_part_properties(obj, node_data,
                                                            part_info):
                        prop_changed = True
                else:
                    new_placement = create_local_placement(node_data)
                    if not obj.Placement.isSame(new_placement, 1e-6):
                        obj.Placement = new_placement
                        prop_changed = True
                    if obj.Label != node_data["name"]:
                        obj.Label = node_data["name"]
                        prop_changed = True
                if prop_changed:
                    updated += 1

            current_fc_obj = get_object_by_uuid(doc, uuid)
            if current_fc_obj:
                for child_node in node_data.get("children", []):
                    process_node_for_update(child_node, current_fc_obj)

        root_node_data = updated_data["Products"]
        root_fc_obj = get_object_by_uuid(doc, normalize_uuid(
            root_node_data["uuid"]))
        if root_fc_obj:
            for child_node in root_node_data.get("children", []):
                process_node_for_update(child_node, root_fc_obj)
        else:
            msg = "Root satellite object not found in the document."
            QtGui.QMessageBox.critical(None, "Update Error", msg)
            return 0, 0

        doc.recompute()
        if FreeCAD.GuiUp:
            FreeCADGui.updateGui()

        msg = (
            f"Satellite structure updated!\n\n"
            f"Added: {added}\n"
            f"Updated: {updated}\n"
            f"Moved: {moved}\n"
            f"Removed: {removed}"
        )
        QtGui.QMessageBox.information(None, "Update Successful", msg)
        return added + updated + moved, removed
    except Exception as e:
        msg = (
            f"Failed to update satellite structure:\n{str(e)}\n\n"
            f"Traceback:\n{traceback.format_exc()}"
        )
        QtGui.QMessageBox.critical(None, "Update Error", msg)
        return 0, 0


# --- UI Classes and Registration ---
class UpdateSatellite:
    """Command to update the satellite model from the server."""
    def GetResources(self):
        icon_path = os.path.join(
            PROJECT_DIR, 'workbench', 'resources', 'icons',
            'updateSatellite.png'
        )
        return {
            'Pixmap': icon_path,
            'MenuText': "Update Satellite",
            'ToolTip': "Updates satellite structure from server"
        }

    def Activated(self):
        doc = FreeCAD.ActiveDocument
        if not doc or not hasattr(doc, "SatelliteProjectID"):
            msg = "The active document is not a valid satellite model."
            QtGui.QMessageBox.warning(None, "Update Failed", msg)
            return

        project_id, model_id = doc.SatelliteProjectID, doc.SatelliteModelID
        msg = "Update satellite structure from server?"
        reply = QtGui.QMessageBox.question(
            None, "Update Structure", msg,
            QtGui.QMessageBox.Yes | QtGui.QMessageBox.No
        )
        if reply != QtGui.QMessageBox.Yes:
            return

        try:
            import sys
            if PROJECT_DIR not in sys.path:
                sys.path.append(PROJECT_DIR)
            import crawler

            updated_output = crawler.generate_satellite_data(project_id, model_id)
            if not updated_output or "error" in updated_output:
                err = updated_output.get('error', '')
                QtGui.QMessageBox.warning(
                    None, "Update Failed", f"No updated data available: {err}"
                )
                return

            current_ts = getattr(doc, "SatelliteTimestamp", 0)
            new_ts = updated_output.get("timestamp", 0)
            if new_ts and new_ts <= current_ts:
                msg = "Satellite model has not changed since the last update."
                QtGui.QMessageBox.information(None, "No Changes", msg)
                return

            doc.SatelliteTimestamp = new_ts
            update_satellite_document(doc, updated_output)
        except Exception as e:
            msg = (
                f"An error occurred during update:\n{str(e)}\n\n"
                f"{traceback.format_exc()}"
            )
            QtGui.QMessageBox.critical(
                QtGui.QApplication.activeWindow(), "Update Failed", msg
            )

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None and hasattr(
            FreeCAD.ActiveDocument, "SatelliteProjectID"
        )


class ImportSatellite:
    """Command to import a new satellite model."""
    def GetResources(self):
        icon_path = os.path.join(
            PROJECT_DIR, 'workbench', 'resources', 'icons',
            'importSatellite.png'
        )
        return {
            'Pixmap': icon_path,
            'MenuText': "Import Satellite",
            'ToolTip': "Imports satellite structure from JSON file"
        }

    def Activated(self):
        try:
            dialog = ProjectSelectionDialog()
            if not dialog.exec_():
                return

            project_id = dialog.selected_project_id()
            if not project_id:
                msg = "No project selected!"
                QtGui.QMessageBox.critical(
                    QtGui.QApplication.activeWindow(), "Import Failed", msg
                )
                return

            import sys
            if PROJECT_DIR not in sys.path:
                sys.path.append(PROJECT_DIR)
            import crawler
            crawler_output = crawler.generate_satellite_data(project_id)

            if crawler_output is None or "error" in crawler_output:
                err = crawler_output.get('error', '')
                msg = f"No model available for extraction: {err}"
                QtGui.QMessageBox.warning(
                    QtGui.QApplication.activeWindow(), "Import Failed", msg
                )
                return

            if 'models' in crawler_output:
                dialog = ModelSelectionDialog(crawler_output['models'])
                if not dialog.exec_():
                    return
                selected_model_id = dialog.selected_model_id()
                if selected_model_id is None:
                    msg = "No valid model selected."
                    QtGui.QMessageBox.warning(
                        QtGui.QApplication.activeWindow(),
                        "Selection Error", msg
                    )
                    return
                crawler_output = crawler.generate_satellite_data(
                    project_id, selected_model_id
                )

            with open(JSON_PATH, 'w') as f:
                json.dump(crawler_output, f, indent=2)
            import_satellite(JSON_PATH, project_id)
        except Exception as e:
            msg = (
                f"An error occurred:\n{e}\n\n"
                f"{traceback.format_exc()}"
            )
            QtGui.QMessageBox.critical(
                QtGui.QApplication.activeWindow(), "Import Failed", msg
            )

    def IsActive(self):
        return True


class ModelSelectionDialog(QtGui.QDialog):
    """Dialog for selecting a model from a list."""
    def __init__(self, models, parent=None):
        super(ModelSelectionDialog, self).__init__(parent)
        self.setWindowTitle("Select Model")
        self.layout = QtGui.QVBoxLayout(self)
        self.model_table = QtGui.QTableWidget()
        self.model_table.setColumnCount(3)
        self.model_table.setHorizontalHeaderLabels(["Model Name",
                                                    "Type", "ID"])
        self.model_table.setRowCount(len(models))
        self.model_table.setSelectionMode(
            QtGui.QAbstractItemView.SingleSelection)
        self.model_table.setSelectionBehavior(
            QtGui.QAbstractItemView.SelectRows)
        for i, model in enumerate(models):
            self.model_table.setItem(i, 0, QtGui.QTableWidgetItem(model['name']))
            self.model_table.setItem(i, 1, QtGui.QTableWidgetItem(
                model.get('type', 'Unknown')))
            self.model_table.setItem(i, 2, QtGui.QTableWidgetItem(
                str(model['id'])))
        self.model_table.resizeColumnsToContents()
        self.model_table.setCurrentCell(0, 0)
        buttons = QtGui.QDialogButtonBox.Ok | QtGui.QDialogButtonBox.Cancel
        button_box = QtGui.QDialogButtonBox(buttons)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        self.layout.addWidget(QtGui.QLabel("Select a model to import:"))
        self.layout.addWidget(self.model_table)
        self.layout.addWidget(button_box)

    def selected_model_id(self):
        if self.model_table.currentRow() >= 0:
            try:
                id_item = self.model_table.item(self.model_table.currentRow(), 2)
                return int(id_item.text())
            except (ValueError, AttributeError):
                return None
        return None


class ProjectSelectionDialog(QtGui.QDialog):
    """Dialog for selecting a project."""
    def __init__(self, parent=None):
        super(ProjectSelectionDialog, self).__init__(parent)
        self.setWindowTitle("Select Project")
        self.layout = QtGui.QVBoxLayout(self)
        self.project_label = QtGui.QLabel("Select a satellite project:")
        self.project_combo = QtGui.QComboBox()
        buttons = QtGui.QDialogButtonBox.Ok | QtGui.QDialogButtonBox.Cancel
        self.button_box = QtGui.QDialogButtonBox(buttons)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        self.layout.addWidget(self.project_label)
        self.layout.addWidget(self.project_combo)
        self.layout.addWidget(self.button_box)
        self.load_projects()

    def load_projects(self):
        projects = get_projects()
        self.project_combo.clear()
        for project in projects:
            self.project_combo.addItem(project['name'], project['id'])

    def selected_project_id(self):
        return self.project_combo.itemData(self.project_combo.currentIndex())


FreeCADGui.addCommand('ImportSatellite', ImportSatellite())
FreeCADGui.addCommand('UpdateSatellite', UpdateSatellite())

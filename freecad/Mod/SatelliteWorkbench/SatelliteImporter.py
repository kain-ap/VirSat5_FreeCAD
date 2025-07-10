import FreeCAD
import FreeCADGui  # type: ignore
import json
import os
from PySide import QtGui
import Part
import requests
from config import BASE_URL, USERNAME, PASSWORD
import math
import time
import traceback
import logging

# Configuration
PROJECT_DIR = r"C:\git\VirtualSatellite-FreeCAD"
JSON_PATH = os.path.join(PROJECT_DIR, "satellite_structure.json")
SCALE_FACTOR = 1000  # Convert mm to meters

# Global session for API requests
API_SESSION = None


def get_auth_session():
    global API_SESSION
    if API_SESSION is None:
        API_SESSION = requests.Session()
        login_url = f"{BASE_URL}/api/authorize"
        try:
            response = API_SESSION.post(
                login_url,
                json={"username": USERNAME, "password": PASSWORD}
            )
            response.raise_for_status()
            if 'access_token' not in response.json():
                raise Exception("Login failed: No access token received")
        except Exception as e:
            QtGui.QMessageBox.critical(
                None,
                "Authentication Failed",
                f"Could not authenticate with server:\n{e}"
            )
            return None
    return API_SESSION


class SatellitePart:
    def __init__(self, obj):
        obj.Proxy = self
        self.Type = "SatellitePart"
        self.init_properties(obj)

    def init_properties(self, obj):
        obj.addProperty("App::PropertyString",
                        "UUID", "Satellite", "Component ID")
        obj.addProperty("App::PropertyString",
                        "ShapeType", "Satellite", "Shape type")
        obj.addProperty("App::PropertyInteger",
                        "ColorValue", "Satellite", "Part color")
        obj.setEditorMode("ColorValue", 1)
        obj.addProperty("App::PropertyFloat",
                        "Transparency", "Satellite", "Part transparency")
        obj.Transparency = 0.0

        for prop in ["posX", "posY", "posZ", "rotX", "rotY", "rotZ"]:
            obj.addProperty("App::PropertyFloat",
                            prop, "Satellite", f"{prop} position")
            setattr(obj, prop, 0.0)

    def onChanged(self, obj, prop):
        if prop in ["LengthX", "LengthY", "LengthZ",
                    "Radius", "CylinderHeight", "Radius1",
                    "Radius2", "ConeHeight"]:
            self.build_shape(obj)

    def build_shape(self, obj):
        try:
            shape_type = obj.ShapeType
            if shape_type == "BOX":
                obj.Shape = create_box(obj.LengthX, obj.LengthY, obj.LengthZ)
            elif shape_type == "CYLINDER":
                obj.Shape = create_cylinder(obj.Radius, obj.CylinderHeight)
            elif shape_type == "SPHERE":
                obj.Shape = create_sphere(obj.Radius)
            elif shape_type == "CONE":
                obj.Shape = create_cone(obj.Radius1,
                                        obj.Radius2, obj.ConeHeight)

            if hasattr(obj, "ViewObject") and hasattr(obj.ViewObject,
                                                      "ShapeColor"):
                obj.ViewObject.ShapeColor = get_color(obj.ColorValue)
                obj.ViewObject.Transparency = int(obj.Transparency)
        except Exception as e:
            print(f"Error rebuilding shape: {e}")

    def execute(self, obj):
        self.build_shape(obj)


class SatellitePartViewProvider:
    def __init__(self, vobj):
        vobj.Proxy = self

    def getIcon(self):
        return ":/icons/Part_Box.svg"

    def attach(self, vobj):
        self.ViewObject = vobj
        self.Object = vobj.Object

    def updateData(self, fp, prop):
        pass

    def onChanged(self, vp, prop):
        pass

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        return None


# Helper functions
def create_box(lengthX, lengthY, lengthZ):
    if any(dim <= 0 for dim in (lengthX, lengthY, lengthZ)):
        return create_none_shape()
    return Part.makeBox(
        lengthX * SCALE_FACTOR,
        lengthY * SCALE_FACTOR,
        lengthZ * SCALE_FACTOR,
        FreeCAD.Vector(
            -lengthX * SCALE_FACTOR / 2,
            -lengthY * SCALE_FACTOR / 2,
            -lengthZ * SCALE_FACTOR / 2
        )
    )


def create_cylinder(radius, height):
    if radius <= 0 or height <= 0:
        return create_none_shape()
    return Part.makeCylinder(
        radius * SCALE_FACTOR,
        height * SCALE_FACTOR,
        FreeCAD.Vector(0, 0, -height * SCALE_FACTOR / 2),
        FreeCAD.Vector(0, 0, 1)
    )


def create_cone(radius1, radius2, height):
    if height <= 0 or (radius1 <= 0 and radius2 <= 0):
        return create_none_shape()
    radius1 = max(radius1, 0)
    radius2 = max(radius2, 0)
    return Part.makeCone(
        radius1 * SCALE_FACTOR,
        radius2 * SCALE_FACTOR,
        height * SCALE_FACTOR,
        FreeCAD.Vector(0, 0, -height * SCALE_FACTOR / 2),
        FreeCAD.Vector(0, 0, 1)
    )


def create_sphere(radius):
    if radius <= 0:
        return create_none_shape()
    return Part.makeSphere(radius * SCALE_FACTOR, FreeCAD.Vector(0, 0, 0))


def create_none_shape():
    box = Part.makeBox(0.001, 0.001, 0.001)
    placement = FreeCAD.Placement(
        FreeCAD.Vector(-0.0005, -0.0005, -0.0005),
        FreeCAD.Rotation()
    )
    box.Placement = placement
    return box


def get_color(color_int):
    r = ((color_int >> 16) & 0xFF) / 255.0
    g = ((color_int >> 8) & 0xFF) / 255.0
    b = (color_int & 0xFF) / 255.0
    return (r, g, b)


def create_placement(node):
    """Create placement with proper handling of missing values"""
    posX = float(node.get("posX", 0)) * SCALE_FACTOR
    posY = float(node.get("posY", 0)) * SCALE_FACTOR
    posZ = float(node.get("posZ", 0)) * SCALE_FACTOR
    
    rotX = float(node.get("rotX", 0))
    rotY = float(node.get("rotY", 0))
    rotZ = float(node.get("rotZ", 0))
    
    # Convert rotations to radians
    rotation = FreeCAD.Rotation(
        math.radians(rotX),
        math.radians(rotY),
        math.radians(rotZ)
    )
    
    return FreeCAD.Placement(
        FreeCAD.Vector(posX, posY, posZ),
        rotation
    )


def get_projects():
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


def import_satellite(filename, project_id, target_doc=None):
    try:
        if target_doc is None:
            doc = FreeCAD.ActiveDocument
            if doc is None:
                doc = FreeCAD.newDocument("Satellite")
        else:
            doc = target_doc

        with open(filename) as f:
            data = json.load(f)

        # Store project ID in document
        if not hasattr(doc, "SatelliteProjectID"):
            doc.addProperty("App::PropertyString", "SatelliteProjectID",
                            "Satellite", "Project ID")
        doc.SatelliteProjectID = str(project_id)

        if not hasattr(doc, "SatelliteModelID"):
            doc.addProperty("App::PropertyString", "SatelliteModelID",
                            "Satellite", "Model ID")
        doc.SatelliteModelID = str(data["Products"]["uuid"])

        if not hasattr(doc, "SatelliteJSONPath"):
            doc.addProperty("App::PropertyString", "SatelliteJSONPath",
                            "Satellite", "Source JSON path")
        doc.SatelliteJSONPath = filename

        if not hasattr(doc, "SatelliteTimestamp"):
            doc.addProperty("App::PropertyFloat", "SatelliteTimestamp",
                            "Satellite", "Last update timestamp")
        doc.SatelliteTimestamp = data.get("timestamp", time.time())

        # Create a dictionary to map part UUIDs to their data
        parts_dict = {part["uuid"]: part for part in data["Parts"]}

        # Create all App::Part containers first
        assembly_nodes = {}
        placement_cache = {}

        def create_assembly_node(node, parent=None, parent_placement=None):
            assembly = doc.addObject("App::Part", f"Assy_{node['uuid']}")
            assembly.Label = node['name']

            # Add UUID property
            assembly.addProperty("App::PropertyString", "UUID",
                                 "Satellite", "Component ID")
            assembly.UUID = node["uuid"]

            placement = create_placement(node)

            if parent_placement:
                placement = parent_placement * placement
            assembly.Placement = placement
            placement_cache[node["uuid"]] = placement

            # Store in dictionary
            assembly_nodes[node["uuid"]] = assembly

            # Add to parent if exists
            if parent:
                parent.addObject(assembly)

            return assembly, placement

        # Create root assembly
        root, root_placement = create_assembly_node(data["Products"])
        assembly_nodes[data["Products"]["uuid"]] = root
        placement_cache[data["Products"]["uuid"]] = root_placement

        # Recursively create all child assemblies
        def process_children(node, parent, parent_placement):
            for child in node.get("children", []):
                child_assembly, child_placement = create_assembly_node(
                    child, parent, parent_placement)
                assembly_nodes[child["uuid"]] = child_assembly
                placement_cache[child["uuid"]] = child_placement
                process_children(child, child_assembly, child_placement)

        process_children(data["Products"], root, root_placement)

        # Function to process nodes and create parts
        def process_node(node, parent_placement):
            if "partUuid" in node:
                part_uuid = node["partUuid"]
                if part_uuid in parts_dict:
                    base_part_data = parts_dict[part_uuid]

                    # Create override properties dictionary
                    override_props = {}
                    for prop in ['sizeX', 'sizeY', 'sizeZ',
                                 'radius', 'transparency']:
                        if prop in node:
                            override_props[prop] = node[prop]

                    # Merge base properties with overrides
                    part_data = {**base_part_data, **override_props}

                    parent_assembly = assembly_nodes.get(node["uuid"])

                    if parent_assembly:
                        # Create custom part object
                        part_obj = doc.addObject(
                            "Part::FeaturePython", f"Part_{node['uuid']}"
                        )
                        SatellitePart(part_obj)
                        if FreeCAD.GuiUp:
                            SatellitePartViewProvider(part_obj.ViewObject)

                        part_obj.Label = node["name"]
                        part_obj.UUID = node["uuid"]
                        part_obj.ShapeType = part_data["shape"].upper()
                        part_obj.ColorValue = part_data["color"]
                        part_obj.Transparency = part_data.get("transparency",
                                                              0.0)

                        part_placement = create_placement(node)

                        if parent_placement:
                            part_placement = parent_placement * part_placement

                        part_obj.Placement = part_placement

                        # Set shape-specific properties
                        shape_type = part_obj.ShapeType
                        if shape_type == "BOX":
                            part_obj.addProperty("App::PropertyFloat",
                                                 "LengthX",
                                                 "Satellite",
                                                 "Length in X")
                            part_obj.addProperty("App::PropertyFloat",
                                                 "LengthY",
                                                 "Satellite",
                                                 "Length in Y")
                            part_obj.addProperty("App::PropertyFloat",
                                                 "LengthZ",
                                                 "Satellite",
                                                 "Length in Z")
                            part_obj.LengthX = part_data["lengthX"]
                            part_obj.LengthY = part_data["lengthY"]
                            part_obj.LengthZ = part_data["lengthZ"]

                        elif shape_type == "CYLINDER":
                            part_obj.addProperty("App::PropertyFloat",
                                                 "Radius",
                                                 "Satellite",
                                                 "Cylinder radius")
                            part_obj.addProperty("App::PropertyFloat",
                                                 "CylinderHeight",
                                                 "Satellite",
                                                 "Cylinder height")
                            part_obj.Radius = part_data["radius"]
                            part_obj.CylinderHeight = part_data["lengthY"]

                        elif shape_type == "SPHERE":
                            part_obj.addProperty("App::PropertyFloat",
                                                 "Radius",
                                                 "Satellite",
                                                 "Sphere radius")
                            part_obj.Radius = part_data["radius"]

                        # Build initial shape and set placement
                        part_obj.Proxy.build_shape(part_obj)

                        # Add to parent assembly
                        parent_assembly.addObject(part_obj)

            # Process children
            for child in node.get("children", []):
                child_placement = placement_cache.get(child["uuid"],
                                                      FreeCAD.Placement())
                process_node(child, child_placement)

        # Now create and place all parts
        for child in data["Products"]["children"]:
            child_placement = placement_cache.get(child["uuid"],
                                                  FreeCAD.Placement())
            process_node(child, child_placement)

        # Set root assembly name
        root.Label = data["Products"]["name"]

        doc.recompute()
        FreeCADGui.SendMsgToActiveView("ViewFit")

        QtGui.QMessageBox.information(
            QtGui.QApplication.activeWindow(),
            "Import Successful",
            f"Satellite structure imported from:\n{filename}"
        )
        return True

    except Exception as e:
        import traceback
        error_msg = (
            f"Failed to import satellite structure:\n{str(e)}\n\n"
            f"Traceback:\n{traceback.format_exc()}"
        )
        if target_doc is None:
            QtGui.QMessageBox.critical(
                QtGui.QApplication.activeWindow(),
                "Import Error",
                error_msg
            )
        return False


def find_satellite_objects(doc):
    """Find all satellite objects in the document"""
    return [obj for obj in doc.Objects if hasattr(obj, "UUID")]


def get_object_by_uuid(doc, uuid):
    """Find object by UUID"""
    for obj in doc.Objects:
        if hasattr(obj, "UUID") and obj.UUID == uuid:
            return obj
    return None


def update_satellite_document(doc, updated_data):
    """Update satellite structure incrementally with full UUID handling"""
    try:
        # Validate updated data
        if not updated_data:
            QtGui.QMessageBox.critical(
                None,
                "Update Failed",
                "No update data received from server."
            )
            return 0, 0

        if "Products" not in updated_data or not updated_data["Products"]:
            QtGui.QMessageBox.critical(
                None,
                "Update Failed",
                "Invalid update data: Missing 'Products' structure."
            )
            return 0, 0

        # Normalize UUIDs for consistent matching
        def normalize_uuid(uuid):
            return str(uuid).strip().lower() if uuid else ""

        # Create UUID maps
        updated_parts = {}
        if "Parts" in updated_data:
            for part in updated_data["Parts"]:
                uuid = normalize_uuid(part.get("uuid"))
                if uuid:
                    updated_parts[uuid] = part

        updated_nodes = {}

        def index_nodes(node):
            """Index nodes with UUID normalization and validation"""
            if not node or not isinstance(node, dict):
                return

            uuid = normalize_uuid(node.get("uuid"))
            if uuid:
                updated_nodes[uuid] = node

            for child in node.get("children", []):
                if isinstance(child, dict):
                    index_nodes(child)

        # Index nodes with validation and normalization
        index_nodes(updated_data["Products"])

        # Find existing satellite objects
        existing_objects = find_satellite_objects(doc)
        uuid_map = {}
        for obj in existing_objects:
            uuid = normalize_uuid(getattr(obj, "UUID", ""))
            if uuid:
                uuid_map[uuid] = obj

        # Track changes
        added_count = 0
        updated_count = 0
        removed_count = 0
        moved_count = 0
        
        # 1. Process removals first
        for obj_uuid, obj in list(uuid_map.items()):
            if obj_uuid not in updated_nodes:
                try:
                    # Remove from parent first
                    parent = obj.getParent()
                    if parent and hasattr(parent, "removeObject"):
                        parent.removeObject(obj)
                    
                    # Then remove from document
                    doc.removeObject(obj.Name)
                    removed_count += 1
                    
                    # Remove from UUID map
                    del uuid_map[obj_uuid]
                except Exception as e:
                    print(f"Error removing object {obj.Name}: {str(e)}")
        
        # 2. Create/update assemblies hierarchy
        assembly_objects = {}
        
        def create_or_update_assembly(node, parent=None):
            nonlocal added_count, updated_count, moved_count
            uuid = normalize_uuid(node["uuid"])
            obj = uuid_map.get(uuid)
            
            # Create new assembly if needed
            if not obj:
                obj = create_assembly_object(doc, node)
                added_count += 1
                uuid_map[uuid] = obj
                assembly_objects[uuid] = obj
            
            # Update existing assembly
            if obj:
                # Update label if changed
                if hasattr(obj, "Label") and obj.Label != node["name"]:
                    obj.Label = node["name"]
                    updated_count += 1

                new_placement = create_placement(node)
                
                # Only update if placement has changed
                if hasattr(obj, "Placement") and not obj.Placement.isSame(new_placement, 1e-6):
                    obj.Placement = new_placement
                    updated_count += 1
                
                # Check parent relationship
                current_parent = obj.getParent()
                if parent and current_parent != parent:
                    try:
                        # Remove from current parent
                        if current_parent and hasattr(current_parent, "removeObject"):
                            current_parent.removeObject(obj)
                        
                        # Add to new parent
                        parent.addObject(obj)
                        moved_count += 1
                    except Exception as e:
                        logging.error(f"Error reparenting assembly: {str(e)}")
            
            return obj
        
        # Build assembly hierarchy
        def build_assembly_hierarchy(node, parent=None):
            """Recursively build assembly hierarchy"""
            assembly = create_or_update_assembly(node, parent)
            for child in node.get("children", []):
                # Only process assembly nodes (non-parts)
                if "partUuid" not in child:
                    build_assembly_hierarchy(child, assembly)

        # 3. Process parts and leaf nodes
        def process_parts(node, parent_assembly=None):
            """Process part nodes and their properties with change detection"""
            nonlocal added_count, updated_count, moved_count
            uuid = normalize_uuid(node["uuid"])
            
            if "partUuid" in node:
                part_uuid = normalize_uuid(node["partUuid"])
                part_data = updated_parts.get(part_uuid, {})
                
                obj = uuid_map.get(uuid)
                
                if not obj:
                    # New object - create with proper name
                    obj = create_part_object(doc, node, part_data)
                    added_count += 1
                    uuid_map[uuid] = obj
                else:
                    if obj and hasattr(obj, "ShapeType"):
                        # Record original state
                        original_placement = obj.Placement
                        original_color = obj.ColorValue
                        original_transparency = obj.Transparency
                        
                        # Apply placement change
                        new_placement = create_placement(node)
                        current_parent = obj.getParent()
                        if parent_assembly and parent_assembly == current_parent:
                            if not obj.Placement.isSame(new_placement, 1e-9):
                                obj.Placement = new_placement
                        
                        # Check property changes
                        property_changed = update_part_properties(obj, part_data)
                        
                        # Check parent relationship
                        target_parent = parent_assembly or assembly_objects.get(
                            normalize_uuid(node.get("parentId", ""))
                        )
                        parent_changed = False
                        if target_parent and current_parent != target_parent:
                            try:
                                if current_parent and hasattr(current_parent, "removeObject"):
                                    current_parent.removeObject(obj)
                                target_parent.addObject(obj)
                                moved_count += 1
                                parent_changed = True
                            except Exception as e:
                                print(f"Error reparenting part: {str(e)}")
                        
                        # Check if anything changed (excluding label)
                        state_changed = (
                            not obj.Placement.isSame(original_placement, 1e-9) or
                            obj.ColorValue != original_color or
                            abs(obj.Transparency - original_transparency) > 1e-6
                        )
                        
                        # Only count as update if something changed
                        if state_changed or property_changed or parent_changed:
                            updated_count += 1
                            logging.info(f"Updated part: {obj.Label} ({obj.UUID})")
                            if not obj.Placement.isSame(original_placement, 1e-9):
                                logging.info("  - Placement changed")
                            if obj.ColorValue != original_color:
                                logging.info(f"  - Color changed: {original_color} → {obj.ColorValue}")
                            if abs(obj.Transparency - original_transparency) > 1e-6:
                                logging.info(f"  - Transparency changed: {original_transparency} → {obj.Transparency}")
                            if property_changed:
                                logging.info("  - Properties changed")
                            if parent_changed:
                                logging.info("  - Parent changed")
                    # Handle case where we have an assembly instead of part
                    elif obj:
                        logging.warning(f"Object {obj.Name} is not a part but has partUuid")
            
            # Process children
            for child in node.get("children", []):
                # For parts, use current parent assembly
                current_parent = parent_assembly or assembly_objects.get(uuid)
                process_parts(child, current_parent)
        
        # Start processing parts from root
        process_parts(updated_data["Products"])
        
        # 4. Update document properties
        root_uuid = normalize_uuid(updated_data["Products"]["uuid"])
        doc.SatelliteModelID = root_uuid
        doc.SatelliteTimestamp = updated_data.get("timestamp", time.time())
        
        # 5. Recompute and report
        doc.recompute()
        
        # Report results
        QtGui.QMessageBox.information(
            None,
            "Update Successful",
            f"Satellite structure updated!\n\n"
            f"Added: {added_count}\n"
            f"Updated: {updated_count}\n"
            f"Moved: {moved_count}\n"
            f"Removed: {removed_count}"
        )
        
        return added_count + updated_count, removed_count
        
    except Exception as e:
        import traceback
        error_msg = (
            f"Failed to update satellite structure:\n{str(e)}\n\n"
            f"Traceback:\n{traceback.format_exc()}"
        )
        QtGui.QMessageBox.critical(
            None,
            "Update Error",
            error_msg
        )
        return 0, 0


def create_assembly_object(doc, node):
    """Create an assembly container"""
    assembly = doc.addObject("App::Part", f"Assy_{node['uuid']}")
    assembly.Label = node['name']

    # Add UUID property
    assembly.addProperty("App::PropertyString", "UUID",
                         "Satellite", "Component ID")
    assembly.UUID = node["uuid"]

    # Set placement
    assembly.Placement = create_placement(node)

    return assembly


def create_part_object(doc, node, part_data):
    """Create a satellite part object"""
    obj = doc.addObject("Part::FeaturePython", f"Part_{node['uuid']}")
    SatellitePart(obj)
    if FreeCAD.GuiUp:
        SatellitePartViewProvider(obj.ViewObject)
    
    obj.Label = node["name"]
    obj.UUID = node["uuid"]
    
    # Set common properties
    obj.ShapeType = part_data.get("shape", "BOX").upper()
    obj.ColorValue = part_data.get("color", 12632256)  # Default gray
    obj.Transparency = part_data.get("transparency", 0.0)
    obj.Placement = create_placement(node)
    
    # Set shape-specific properties
    update_part_properties(obj, part_data)
    
    # Build initial shape
    obj.Proxy.build_shape(obj)
    
    return obj


def update_part_properties(obj, part_data):
    """Update part-specific properties with change detection"""
    if not hasattr(obj, "ShapeType"):
        return False
    
    changed = False
    shape_type = part_data.get("shape", "BOX").upper()
    
    # Update color if changed
    new_color = part_data.get("color", 12632256)
    if obj.ColorValue != new_color:
        obj.ColorValue = new_color
        changed = True
    
    # Update transparency if changed
    new_transparency = part_data.get("transparency", 0.0)
    if abs(obj.Transparency - new_transparency) > 1e-6:
        obj.Transparency = new_transparency
        changed = True
    
    # Shape-specific property updates
    if shape_type == "BOX":
        # Add properties if missing
        for prop in ["LengthX", "LengthY", "LengthZ"]:
            if not hasattr(obj, prop):
                obj.addProperty("App::PropertyFloat", prop, "Satellite", f"{prop} dimension")
                setattr(obj, prop, 0.1)
        
        # Update properties if changed
        for prop, value in [("LengthX", part_data.get("lengthX", 0.1)),
                            ("LengthY", part_data.get("lengthY", 0.1)),
                            ("LengthZ", part_data.get("lengthZ", 0.1))]:
            current_val = getattr(obj, prop)
            if abs(current_val - value) > 1e-6:
                setattr(obj, prop, value)
                changed = True
    
    elif shape_type == "CYLINDER":
        # Add properties if missing
        for prop in ["Radius", "CylinderHeight"]:
            if not hasattr(obj, prop):
                obj.addProperty("App::PropertyFloat", prop, "Satellite", prop)
                setattr(obj, prop, 0.1)
        
        # Update properties if changed
        if not hasattr(obj, "Radius") or abs(obj.Radius - part_data.get("radius", 0.05)) > 1e-6:
            obj.Radius = part_data.get("radius", 0.05)
            changed = True
        
        if not hasattr(obj, "CylinderHeight") or abs(obj.CylinderHeight - part_data.get("lengthY", 0.1)) > 1e-6:
            obj.CylinderHeight = part_data.get("lengthY", 0.1)
            changed = True
    
    # Only rebuild shape if properties changed
    if changed:
        obj.Proxy.build_shape(obj)
    
    return changed


class UpdateSatellite:
    def GetResources(self):
        return {
            'Pixmap': os.path.join(PROJECT_DIR, 'Icons', 'updateSatellite.png'),
            'MenuText': "Update Satellite",
            'ToolTip': "Updates satellite structure from server"
        }

    def Activated(self):
        doc = FreeCAD.ActiveDocument
        if not doc:
            QtGui.QMessageBox.warning(None, "Update Failed", "No active document")
            return

        # Check if this document was imported by our tool
        if not hasattr(doc, "SatelliteProjectID") or not hasattr(doc, "SatelliteModelID"):
            QtGui.QMessageBox.warning(
                None,
                "Update Failed",
                "This document was not imported by the satellite importer"
            )
            return

        if not hasattr(doc, "SatelliteJSONPath"):
            doc.addProperty("App::PropertyString", "SatelliteJSONPath", "Satellite", "Source JSON path")
        doc.SatelliteJSONPath = "update_path.json"

        project_id = doc.SatelliteProjectID
        model_id = doc.SatelliteModelID

        # Confirm with user
        reply = QtGui.QMessageBox.question(
            None,
            "Update Structure",
            "Update satellite structure from server?",
            QtGui.QMessageBox.Yes | QtGui.QMessageBox.No
        )

        if reply != QtGui.QMessageBox.Yes:
            return

        try:
            # Import and run the crawler script
            import sys
            if PROJECT_DIR not in sys.path:
                sys.path.append(PROJECT_DIR)
            import crawler

            # Get updated data
            updated_output = crawler.generate_satellite_data(project_id, model_id)

            if not updated_output:
                QtGui.QMessageBox.warning(
                    None,
                    "Update Failed",
                    "No updated data available"
                )
                return

            # Check if update is needed
            current_timestamp = getattr(doc, "SatelliteTimestamp", 0)
            new_timestamp = updated_output.get("timestamp", 0)

            if new_timestamp <= current_timestamp:
                QtGui.QMessageBox.information(
                    None,
                    "No Changes",
                    "Satellite model has not changed since last update"
                )
                return

            # Update the document
            update_satellite_document(doc, updated_output)

        except Exception as e:
            QtGui.QMessageBox.critical(
                QtGui.QApplication.activeWindow(),
                "Update Failed",
                f"An error occurred during update:\n{str(e)}\n\n{traceback.format_exc()}"
            )

    def IsActive(self):
        if FreeCAD.ActiveDocument is None:
            return False
        return hasattr(FreeCAD.ActiveDocument, "SatelliteProjectID")


# ImportSatellite
class ImportSatellite:
    def GetResources(self):
        return {
            'Pixmap': os.path.join(PROJECT_DIR, 'Icons', 'importSatellite.png'),
            'MenuText': "Import Satellite",
            'ToolTip': "Imports satellite structure from JSON file"
        }

    def Activated(self):
        try:
            # Show project selection dialog
            dialog = ProjectSelectionDialog()
            if not dialog.exec_():
                return  # User canceled

            project_id = dialog.selected_project_id()
            if not project_id:
                QtGui.QMessageBox.critical(
                    QtGui.QApplication.activeWindow(),
                    "Import Failed",
                    "No project selected!"
                )
                return

            # Import and run the crawler script
            import sys
            if PROJECT_DIR not in sys.path:
                sys.path.append(PROJECT_DIR)
            import crawler
            crawler_output = crawler.generate_satellite_data(project_id)

            # Handle no model case
            if crawler_output is None:
                QtGui.QMessageBox.warning(
                    QtGui.QApplication.activeWindow(),
                    "Import Failed",
                    "No model available for extraction"
                )
                return

            # Handle model selection
            if 'models' in crawler_output:  # Multiple models available
                dialog = ModelSelectionDialog(crawler_output['models'])
                if dialog.exec_():
                    selected_model_id = dialog.selected_model_id()
                    if selected_model_id is None:
                        QtGui.QMessageBox.warning(
                            QtGui.QApplication.activeWindow(),
                            "Selection Error",
                            "No valid model selected. Please select a model."
                        )
                        return
                    # Generate with selected model
                    crawler_output = crawler.generate_satellite_data(
                        project_id, selected_model_id
                    )
                else:
                    return  # User canceled

            # Save JSON and import
            with open(JSON_PATH, 'w') as f:
                json.dump(crawler_output, f, indent=2)

            import_satellite(JSON_PATH, project_id)

        except Exception as e:
            import traceback
            QtGui.QMessageBox.critical(
                QtGui.QApplication.activeWindow(),
                "Import Failed",
                f"An error occurred:\n{e}\n\n{traceback.format_exc()}"
            )

    def IsActive(self):
        return True


# UI Dialogs
class ModelSelectionDialog(QtGui.QDialog):
    """Dialog for selecting a model"""
    def __init__(self, models, parent=None):
        super(ModelSelectionDialog, self).__init__(parent)
        self.setWindowTitle("Select Model")
        self.layout = QtGui.QVBoxLayout(self)

        # Create table
        self.model_table = QtGui.QTableWidget()
        self.model_table.setColumnCount(3)
        self.model_table.setHorizontalHeaderLabels(
            ["Model Name", "Type", "ID"]
        )
        self.model_table.setRowCount(len(models))
        self.model_table.setSelectionMode(
            QtGui.QAbstractItemView.SingleSelection
        )

        # Populate table
        for i, model in enumerate(models):
            self.model_table.setItem(
                i, 0, QtGui.QTableWidgetItem(model['name']))
            item_type = QtGui.QTableWidgetItem(model['type'])
            self.model_table.setItem(i, 1, item_type)
            model_id_item = QtGui.QTableWidgetItem(str(model['id']))
            self.model_table.setItem(i, 2, model_id_item)

        self.model_table.resizeColumnsToContents()
        self.model_table.setCurrentCell(0, 0)

        # Add buttons
        button_box = QtGui.QDialogButtonBox(
            QtGui.QDialogButtonBox.Ok | QtGui.QDialogButtonBox.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)

        self.layout.addWidget(QtGui.QLabel("Select a model to import:"))
        self.layout.addWidget(self.model_table)
        self.layout.addWidget(button_box)

    def selected_model_id(self):
        """Get the ID of the selected model"""
        selected_row = self.model_table.currentRow()
        if selected_row >= 0:
            id_item = self.model_table.item(selected_row, 2)
            if id_item:
                try:
                    return int(id_item.text())
                except ValueError:
                    pass
        return None


class ProjectSelectionDialog(QtGui.QDialog):
    """Dialog for selecting a project"""
    def __init__(self, parent=None):
        super(ProjectSelectionDialog, self).__init__(parent)
        self.setWindowTitle("Select Project")
        self.layout = QtGui.QVBoxLayout(self)

        # Project selection
        self.project_label = QtGui.QLabel("Select a satellite project:")
        self.layout.addWidget(self.project_label)

        self.project_combo = QtGui.QComboBox()
        self.layout.addWidget(self.project_combo)

        # Button box
        self.button_box = QtGui.QDialogButtonBox(
            QtGui.QDialogButtonBox.Ok | QtGui.QDialogButtonBox.Cancel
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        self.layout.addWidget(self.button_box)

        # Load projects
        self.load_projects()

    def load_projects(self):
        """Load projects from API"""
        projects = get_projects()
        self.project_combo.clear()
        for project in projects:
            self.project_combo.addItem(project['name'], project['id'])

    def selected_project_id(self):
        """Get selected project ID"""
        return self.project_combo.itemData(self.project_combo.currentIndex())


# Register commands
FreeCADGui.addCommand('ImportSatellite', ImportSatellite())
FreeCADGui.addCommand('UpdateSatellite', UpdateSatellite())

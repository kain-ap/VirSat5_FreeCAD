import requests
import json
from collections import defaultdict, deque
from config import BASE_URL, USERNAME, PASSWORD
import math
import time
import logging
import traceback

# Configure logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# Global session for API requests
API_SESSION = None


def get_auth_session():
    """Create authenticated session with username/password"""
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

            # Verify we got a token in the response
            if 'access_token' not in response.json():
                raise Exception("Login failed: No access token received")

            logging.info("Authentication successful")
        except Exception as e:
            logging.error(f"Authentication failed: {e}")
            return None
    return API_SESSION


def fetch_data(endpoint):
    """Fetch JSON data from API endpoint with authentication"""
    session = get_auth_session()
    if not session:
        return None

    url = f"{endpoint}"
    try:
        response = session.get(url)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching {url}: {e}")
        if response:
            logging.debug(f"Response content: {response.text[:500]}")
        return None


def build_entity_tree(entities):
    """Build parent-child tree structure
    from entities with UUID normalization"""
    tree = defaultdict(list)
    for entity in entities:
        if 'parentId' in entity and entity['parentId']:
            # Normalize UUIDs to strings
            parent_id = str(entity['parentId'])
            tree[parent_id].append(entity)
    return tree


def extract_visualization(categories, entity_id, all_categories,
                          base_entities_map, entities):
    """Extract visualization properties with full entity inheritance support"""
    # Create category map
    category_map = {cat['id']: cat for cat in all_categories}

    # Find entity by ID (normalized to string)
    entity_id = str(entity_id)
    entity = next((e for e in entities if str(e['id']) == entity_id), None)
    if not entity:
        logging.warning(f"Entity {entity_id} not found in entities list")
        return None

    # First: Get properties from inherited base entities
    base_props = {}
    if 'inheritsFrom' in entity and entity['inheritsFrom']:
        for base_id in entity['inheritsFrom']:
            base_id = str(base_id)
            # Get base entity's visualization
            base_vis = extract_visualization(
                categories,
                base_id,
                all_categories,
                base_entities_map,
                entities
            ) or {}
            # Merge properties (base first, current overrides)
            base_props = {**base_props, **base_vis}

    # Second: Get this entity's own visualization
    vis_candidates = []
    for category in all_categories:
        cat_entity_id = str(category.get('entityId', ''))
        if (
            cat_entity_id == entity_id and
            category['name'].lower() in ["visualization", "geometry"]
        ):

            # Collect properties with category inheritance
            properties = {}
            stack = deque([category])
            visited = set()

            while stack:
                current = stack.popleft()
                if current['id'] in visited:
                    continue
                visited.add(current['id'])

                # Merge properties (child overrides parent)
                for prop in current.get('properties', []):
                    prop_name = prop['name']
                    value = prop['value']

                    # Handle different value types
                    if isinstance(value, dict) and 'value' in value:
                        prop_value = value['value']
                    else:
                        prop_value = value

                    # Only set if not already defined (child overrides parent)
                    if prop_name not in properties:
                        # Special handling for transparency
                        if prop_name == 'transparency':
                            try:
                                # Convert to float and clamp between 0-100
                                prop_value = float(prop_value)
                                prop_value = max(0.0, min(100.0, prop_value))
                            except (ValueError, TypeError):
                                prop_value = 0.0
                        properties[prop_name] = prop_value

                # Add parent categories to processing stack
                if 'inheritsFrom' in current and current['inheritsFrom']:
                    parent_id = current['inheritsFrom']
                    if parent_id in category_map:
                        stack.append(category_map[parent_id])

            vis_candidates.append((category['id'], properties))

    # Third: Combine base entity properties with current entity properties
    combined_props = {**base_props}
    if vis_candidates:
        vis_candidates.sort(key=lambda x: x[0], reverse=True)
        current_props = vis_candidates[0][1]
        combined_props = {**combined_props, **current_props}

    return combined_props if combined_props else None


def get_part_data(entity, categories, all_categories,
                  base_entities_map, entities):
    """Generate complete part data with inheritance support"""
    # Normalize entity ID
    entity_id = str(entity['id'])

    # Get visualization with inheritance
    vis = extract_visualization(
        categories, entity_id, all_categories, base_entities_map, entities
    )
    if not vis:
        logging.debug(f"No visualization for entity {entity_id}")
        return None

    # Handle shape detection
    shape = str(vis.get('shape', '')).strip().upper()
    if not shape or shape == "NONE":
        # Skip entities without a valid shape
        return None

    # Get dimensions with better defaults
    sizeX = float(vis.get('sizeX', 0.1))
    sizeY = float(vis.get('sizeY', 0.1))
    sizeZ = float(vis.get('sizeZ', 0.1))
    radius = float(vis.get('radius', 0))

    # Handle color conversion
    color_str = vis.get('color', '')
    try:
        color = int(color_str) if color_str else 12632256  # Default gray
    except (ValueError, TypeError):
        color = 12632256  # Fallback to default gray

    transparency = float(vis.get('transparency', 0.0))

    part_data = {
        "shape": shape,
        "uuid": str(entity['id']),
        "name": entity['name'],
        "color": color,
        "transparency": transparency
    }

    # Shape-specific property handling
    if shape == "BOX":
        part_data.update({
            "lengthX": sizeX,
            "lengthY": sizeY,
            "lengthZ": sizeZ,
            "radius": radius
        })
    elif shape == "SPHERE":
        effective_radius = radius if radius > 0 else (
            max(sizeX, sizeY, sizeZ) / 2
        )
        part_data.update({
            "radius": effective_radius,
            "lengthX": 0.0,
            "lengthY": 0.0,
            "lengthZ": 0.0
        })
    elif shape == "CYLINDER":
        effective_radius = radius if radius > 0 else max(sizeX, sizeZ) / 2
        part_data.update({
            "radius": effective_radius,
            "lengthY": sizeY,  # Height
            "lengthX": 0.0,
            "lengthZ": 0.0
        })
    else:  # Fallback to box
        part_data.update({
            "shape": "BOX",
            "lengthX": sizeX,
            "lengthY": sizeY,
            "lengthZ": sizeZ,
            "radius": radius
        })

    return part_data


def build_output_tree(entity_id, entities, tree, categories, base_entities_map,
                      parent=None, name_counts=None, all_categories=None):
    # Normalize entity ID to string
    entity_id = str(entity_id)

    if all_categories is None:
        all_categories = categories

    if name_counts is None:
        name_counts = {}

    # Find entity with normalized ID comparison
    entity = next((e for e in entities
                   if str(e.get('id', '')) == entity_id), None)
    if not entity:
        logging.error(f"Entity {entity_id} not found in build_output_tree")
        return None

    # Handle duplicate names
    entity_name = entity['name']
    if parent and 'uuid' in parent:
        parent_id = parent['uuid']
        name_counts.setdefault(parent_id, {})
        name_counts[parent_id][entity_name] = (
            name_counts[parent_id].get(entity_name, 0) + 1)
        count = name_counts[parent_id][entity_name]
        if count > 1:
            entity_name = f"{entity_name}_{count}"

    node = {
        "name": entity_name,
        "uuid": str(entity['id']),
        "children": []
    }

    # Add visualization properties with full inheritance support
    vis = extract_visualization(
        all_categories, entity_id, all_categories,
        base_entities_map, entities
    )
    if vis:
        # Convert rotations from degrees to radians
        for prop in ['rotX', 'rotY', 'rotZ']:
            if prop in vis:
                degrees = float(vis.get(prop, 0.0))
                radians = math.radians(degrees)
                node[prop] = radians

        # Positions stay in meters
        for prop in ['posX', 'posY', 'posZ']:
            if prop in vis:
                node[prop] = float(vis.get(prop, 0.0))

        for prop in ['sizeX', 'sizeY', 'sizeZ', 'radius',
                     'transparency']:
            if prop in vis:
                node[prop] = vis[prop]

    # Process children
    for child in tree.get(entity_id, []):
        child_node = build_output_tree(
            child['id'], entities, tree, categories, base_entities_map,
            parent=node, name_counts=name_counts, all_categories=all_categories
        )
        if child_node:
            node['children'].append(child_node)

    # Handle part reference for ALL entities with visualization
    if vis:
        # Check if this entity inherits from a base entity
        if 'inheritsFrom' in entity and entity['inheritsFrom']:
            base_id = entity['inheritsFrom'][0]
            base_entity = base_entities_map.get(base_id)
            if base_entity:
                node['partUuid'] = str(base_id)
                node['partName'] = base_entity['name']
            else:
                # Fallback to own ID if base not found
                node['partUuid'] = str(entity['id'])
                node['partName'] = entity['name']
        else:
            # Regular entity without inheritance
            node['partUuid'] = str(entity['id'])
            node['partName'] = entity['name']

    return node


def get_root_models(entity_types):
    """Identify root models excluding Product Tree and Modes
    with ID normalization"""
    root_models = []
    for et in entity_types:
        if (
            et.get('isRoot', False) and
            et.get('name', '') not in ["Product Tree",
                                       "Product Tree Domain", "Modes"]
        ):
            root_models.append({
                'id': str(et['id']),  # Normalize to string
                'name': et.get('name', 'Unnamed'),
                'isRoot': et.get('isRoot', False)
            })
    return root_models


def generate_satellite_data(project_id, selected_model_id=None):
    """Generate satellite data for a specific project
    with enhanced error handling"""
    logging.info(f"Generating satellite data for project ID: {project_id}")

    # Build endpoints for this project
    endpoints = {
        "entity_types": f"{BASE_URL}/api/projects/{project_id}/entity-types",
        "entities": f"{BASE_URL}/api/projects/{project_id}/entities",
        "categories": f"{BASE_URL}/api/projects/{project_id}/categories",
    }

    try:
        # Fetch data with error checking
        logging.info("Fetching entity types...")
        entity_types = fetch_data(endpoints['entity_types'])
        if not entity_types:
            logging.error("No entity types found")
            return {"error": "No entity types returned from API"}

        logging.info("Fetching entities...")
        entities_data = fetch_data(endpoints['entities'])
        if not entities_data or not entities_data.get('entities'):
            logging.error("No entities found")
            return {"error": "No entities returned from API"}
        entities_data = entities_data['entities']

        # Normalize all IDs to strings
        for entity in entities_data:
            entity['id'] = str(entity.get('id', ''))
            if 'parentId' in entity:
                entity['parentId'] = str(entity['parentId'])

        logging.info(f"Found {len(entities_data)} entities")

        for i, entity in enumerate(entities_data[:5]):
            logging.debug(f"Entity {i+1}: ID={entity['id']}, Name={entity.get('name')}, " f"Type={entity.get('entityTypeId')}, Parent={entity.get('parentId', 'None')}")

        logging.info("Fetching categories...")
        categories = fetch_data(endpoints['categories'])
        if not categories:
            logging.warning("No categories found")

        # Find root model types with more robust filtering
        root_models = []
        for et in entity_types:
            # Check if this entity type is marked as root
            if et.get('isRoot', False):
                # Skip specific types that shouldn't be considered as root models
                if et.get('name') in ["Product Tree", "Product Tree Domain", "Modes"]:
                    logging.debug(f"Skipping root model: {et.get('name')}")
                    continue

                root_models.append({
                    'id': str(et['id']),
                    'name': et.get('name', 'Unnamed'),
                    'isRoot': et.get('isRoot', False)
                })

        root_model_ids = [rm['id'] for rm in root_models]
        logging.info(f"Found {len(root_models)} root models: {[rm['name'] for rm in root_models]}")
        logging.debug(f"Root model IDs: {root_model_ids}")

        # Find root entities with more flexible criteria
        root_entities = []
        for entity in entities_data:
            # Check if entity type matches root model
            entity_type = str(entity.get('entityTypeId', ''))
            if entity_type not in root_model_ids:
                continue

            # Check if entity has no parent or parent is empty
            parent_id = entity.get('parentId', '')
            if not parent_id or parent_id == 'None' or parent_id == 'null':
                root_entities.append(entity)
                logging.debug(f"Found root entity: ID={entity['id']}, Name={entity.get('name')}")

        logging.info(f"Found {len(root_entities)} root entities")

        if not root_entities:
            # Try fallback: entities with no parent at all
            logging.warning("No root entities found with standard criteria, trying fallback...")
            root_entities = [e for e in entities_data if 'parentId' not in e or not e['parentId']]
            logging.info(f"Found {len(root_entities)} root entities with fallback criteria")

            if not root_entities:
                logging.error("No root entities found after fallback")
                # Try last resort: use all entities of root model type
                root_entities = [e for e in entities_data if str(e.get('entityTypeId', '')) in root_model_ids]
                logging.info(f"Using {len(root_entities)} entities of root model type as root entities")

        # Handle model selection
        if selected_model_id is None:
            if len(root_entities) == 1:
                selected_model_id = root_entities[0]['id']
                logging.info(f"Auto-selected model: {selected_model_id}")
            else:
                logging.info("Multiple root models available")
                return {
                    "models": [
                        {
                            "id": e['id'],
                            "name": e.get('name', 'Unnamed'),
                            "type": next(
                                (et['name'] for et in entity_types
                                 if str(et['id']) == e['entityTypeId']),
                                "Unknown"
                            )
                        } for e in root_entities
                    ]
                }
        else:
            # Normalize selected model ID
            selected_model_id = str(selected_model_id)
            logging.info(f"Using selected model: {selected_model_id}")

        # Verify selected model exists
        if not any(str(e['id']) == selected_model_id for e in entities_data):
            logging.error(
                f"Selected model {selected_model_id} not found in entities")
            return {"error": f"Selected model {selected_model_id} not found"}

        # Create map of base entities
        base_entities = [e for e in entities_data
                         if e.get('entityTypeId') == "ProductDefinition"]
        if not base_entities:
            base_entities = entities_data
        base_entities_map = {str(e['id']): e for e in base_entities}

        # Build tree structure
        tree = build_entity_tree(entities_data)
        logging.info(f"Built tree with {len(tree)} parent-child relationships")

        # Build Parts list
        parts_list = []
        for entity in base_entities:
            part_data = get_part_data(
                entity, categories, categories, base_entities_map,
                entities_data
            )
            if part_data:
                parts_list.append(part_data)
        logging.info(f"Created {len(parts_list)} parts")

        # Build Products tree
        products_tree = build_output_tree(
            selected_model_id,
            entities_data,
            tree,
            categories,
            base_entities_map,
            all_categories=categories
        )

        if not products_tree or not isinstance(products_tree, dict):
            logging.error("Invalid products tree generated")
            return {"error": "Failed to generate valid products tree"}

        if "uuid" not in products_tree:
            logging.error("Root node missing UUID")
            return {"error": "Root node missing UUID in products tree"}

        # Return in the desired structure
        return {
            "Products": products_tree,
            "Parts": parts_list,
            "timestamp": time.time()
        }

    except Exception as e:
        logging.exception("Failed to generate satellite data")
        return {
            "error": f"Failed to generate satellite data: {str(e)}",
            "traceback": traceback.format_exc()
        }


def main(project_id=None):
    print("Starting satellite data crawler...")
    print(f"Using API: {BASE_URL}")

    # Authenticate first
    if not get_auth_session():
        print("Authentication failed. Aborting.")
        return

    # If no project ID provided, just return without generating JSON
    if project_id is None:
        print("No project ID provided. Skipping JSON generation.")
        return

    output = generate_satellite_data(project_id)
    if not output:
        return

    output_path = r"C:\git\VirtualSatellite-FreeCAD\satellite_structure.json"
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)
        print(f"Satellite JSON saved to: {output_path}")


if __name__ == "__main__":
    # For standalone execution, use first project by default
    session = get_auth_session()
    if session:
        projects = session.get(f"{BASE_URL}/api/projects").json()
        if projects:
            main(projects[0]['id'])
        else:
            print("No projects found!")

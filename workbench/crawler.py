import requests
import json
from collections import defaultdict, deque
import logging
import time
import traceback
from config import BASE_URL, USERNAME, PASSWORD


# Configure logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

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
            logging.info("Authentication successful")
        except Exception as e:
            logging.error(f"Authentication failed: {e}")
            return None
    return API_SESSION


def fetch_data(endpoint):
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
    tree = defaultdict(list)
    for entity in entities:
        if 'parentId' in entity and entity['parentId']:
            parent_id = str(entity['parentId'])
            tree[parent_id].append(entity)
    return tree


def extract_visualization(categories, entity_id, all_categories, base_entities_map, entities, skip_entity_inheritance=False):
    """Extract visualization properties with inheritance control"""
    category_map = {cat['id']: cat for cat in all_categories}
    entity_id = str(entity_id)
    entity = next((e for e in entities if str(e['id']) == entity_id), None)
    if not entity:
        return None

    # Get base entity properties if not skipped
    base_props = {}
    if not skip_entity_inheritance and 'inheritsFrom' in entity and entity['inheritsFrom']:
        for base_id in entity['inheritsFrom']:
            base_id = str(base_id)
            base_vis = extract_visualization(
                categories, base_id, all_categories, base_entities_map, entities
            ) or {}
            base_props = {**base_props, **base_vis}

    # Get entity's own visualization
    vis_candidates = []
    for category in all_categories:
        cat_entity_id = str(category.get('entityId', ''))
        if cat_entity_id == entity_id and category['name'].lower() in ["visualization", "geometry"]:
            properties = {}
            stack = deque([category])
            visited = set()

            while stack:
                current = stack.popleft()
                if current['id'] in visited:
                    continue
                visited.add(current['id'])

                for prop in current.get('properties', []):
                    prop_name = prop['name']
                    value = prop['value']

                    # Extract value from nested structure
                    if isinstance(value, dict) and 'value' in value:
                        prop_value = value['value']
                    else:
                        prop_value = value

                    # Only set if not already defined
                    if prop_name not in properties:
                        properties[prop_name] = prop_value

                # Add parent categories to processing stack
                if 'inheritsFrom' in current and current['inheritsFrom']:
                    parent_id = current['inheritsFrom']
                    if parent_id in category_map:
                        stack.append(category_map[parent_id])

            vis_candidates.append((category['id'], properties))

    # Combine base and current properties
    combined_props = {**base_props}
    if vis_candidates:
        vis_candidates.sort(key=lambda x: x[0], reverse=True)
        current_props = vis_candidates[0][1]
        combined_props = {**combined_props, **current_props}

    return combined_props if combined_props else None


def get_part_data(entity, categories, all_categories, base_entities_map, entities,type_map):
    """Generate part data for Product Definitions only"""
    PRODUCT_DEFINITION = type_map.get("Product Definition")
    # Only process Product Definitions
    if str(entity.get('entityTypeId', '')) != PRODUCT_DEFINITION:
        return None

    # Get visualization with inheritance
    vis = extract_visualization(
        categories, entity['id'], all_categories, base_entities_map, entities
    )
    if not vis:
        return None

    # Handle shape detection
    shape = str(vis.get('shape', '')).strip().upper()
    if not shape or shape == "NONE":
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
        color = 12632256

    part_data = {
        "shape": shape,
        "uuid": str(entity['id']),
        "name": entity['name'],
        "color": color,
        "lengthX": sizeX,
        "lengthY": sizeY,
        "lengthZ": sizeZ,
        "radius": radius
    }

    return part_data


def build_configuration_tree(entity_id, entities, tree, categories, base_entities_map, type_map, all_categories, name_counts=None, parent=None):
    """Build Products tree with placement and part references"""
    entity_id = str(entity_id)
    if all_categories is None:
        all_categories = categories
    if name_counts is None:
        name_counts = {}

    # Find entity
    entity = next((e for e in entities if str(e.get('id', '')) == entity_id), None)
    if not entity:
        return None

    # Handle duplicate names
    entity_name = entity['name']
    if parent and 'uuid' in parent:
        parent_id = parent['uuid']
        name_counts.setdefault(parent_id, {})
        name_counts[parent_id][entity_name] = name_counts[parent_id].get(entity_name, 0) + 1
        count = name_counts[parent_id][entity_name]
        if count > 1:
            entity_name = f"{entity_name}_{count}"

    node = {
        "name": entity_name,
        "uuid": str(entity['id']),
        "children": []
    }

    # Get visualization for this entity - allow inheritance
    vis = extract_visualization(
        all_categories, entity_id, all_categories,
        base_entities_map, entities, skip_entity_inheritance=False
    )
    ELEMENT_CONFIGURATION = type_map.get("Element Configuration")

    # Add placement properties
    if vis:
        for prop in ['posX', 'posY', 'posZ', 'rotX', 'rotY', 'rotZ', 'transparency']:
            if prop in vis:
                node[prop] = float(vis.get(prop, 0.0))

    # Add part reference for Configuration Tree elements
    if str(entity.get('entityTypeId', '')) == ELEMENT_CONFIGURATION:  # Element Configuration
        base_id = None
        if not tree.get(entity_id, []):
            if 'inheritsFrom' in entity and entity['inheritsFrom']:
                base_id = str(entity['inheritsFrom'][0])
                base_entity = base_entities_map.get(base_id)
                if base_entity:
                    node['partUuid'] = base_id
                    node['partname'] = base_entity['name']
                else:
                    node['partUuid'] = entity_id
    
    # Get visualization for base part if exists
    if 'partUuid' in node:
        base_entity_id = node['partUuid']
        if base_entity_id != entity_id:  # Avoid recursion
            base_vis = extract_visualization(
                all_categories, base_entity_id, all_categories,
                base_entities_map, entities, skip_entity_inheritance=False
            )
            if base_vis:
                # Add base part's visualization properties if not already set
                for prop in ['posX', 'posY', 'posZ', 'rotX', 'rotY', 'rotZ', 'transparency']:
                    if prop in base_vis and prop not in node:
                        node[prop] = float(base_vis.get(prop, 0.0))

    # Process children
    for child in tree.get(entity_id, []):
        child_node = build_configuration_tree(
            child['id'], entities, tree, categories, base_entities_map,
            parent=node, name_counts=name_counts, type_map=type_map, all_categories=all_categories
        )
        if child_node:
            node['children'].append(child_node)

    return node

def get_root_models(entity_types):
    root_models = []
    for et in entity_types:
        if (
            et.get('isRoot', False) and
            et.get('name', '') not in ["Product Tree", "Product Tree Domain", "Modes"]
        ):
            root_models.append({
                'id': str(et['id']),
                'name': et.get('name', 'Unnamed'),
                'isRoot': et.get('isRoot', False)
            })
    return root_models

def generate_satellite_data(project_id, selected_model_id=None):
    """Generate satellite data in the desired structure"""
    try:
        # Build endpoints
        endpoints = {
            "entity_types": f"{BASE_URL}/api/projects/{project_id}/entity-types",
            "entities": f"{BASE_URL}/api/projects/{project_id}/entities",
            "categories": f"{BASE_URL}/api/projects/{project_id}/categories",
        }

        # Fetch data
        entity_types = fetch_data(endpoints['entity_types'])
        if not entity_types:
            return {"error": "No entity types found"}

        entities_data = fetch_data(endpoints['entities'])
        if not entities_data or not entities_data.get('entities'):
            return {"error": "No entities found"}
        entities_data = entities_data['entities']

        # Normalize IDs to strings
        for entity in entities_data:
            entity['id'] = str(entity.get('id', ''))
            if 'parentId' in entity:
                entity['parentId'] = str(entity['parentId'])

        categories = fetch_data(endpoints['categories']) or []

        # Create entity type map
        type_map = get_entity_type_map(entity_types)

        # Define entity types by name
        PRODUCT_DEFINITION = type_map.get("Product Definition")
        ELEMENT_CONFIGURATION = type_map.get("Element Configuration")
        CONFIGURATION_TREE = type_map.get("Configuration Tree")
        MODE = type_map.get("Mode")

        id_to_entity = {str(et['id']): et['name'] for et in entity_types}

        root_models = []
        for et in entity_types:
            if et.get('isRoot', False) and et.get('name', '') not in ["Product Tree", "Product Tree Domain", "Modes"]:
                root_models.append({
                    'id': str(et['id']),
                    'name': et['name'],
                    'isRoot': et.get('isRoot', False)
                })

        root_entities = []
        for entity in entities_data:
            entity_type = str(entity.get('entityTypeId', ''))
            if entity_type in [PRODUCT_DEFINITION, CONFIGURATION_TREE]:
                parent_id = entity.get('parentId', '')
                if not parent_id or parent_id in ['None', 'null']:
                    entity_type_name = id_to_entity.get(entity_type, 'Unknown')
                    root_entities.append({
                        'id': entity['id'],
                        'name': entity.get('name', 'Unnamed'),
                        'type': entity_type_name
                    })

        # Handle model selection
        if selected_model_id is None:
            if len(root_entities) == 1:
                selected_model_id = root_entities[0]['id']
            else:
                return {
                    "models": root_entities
                }
        else:
            selected_model_id = str(selected_model_id)

        # Verify selected model exists
        if not any(str(e['id']) == selected_model_id for e in entities_data):
            return {"error": f"Selected model {selected_model_id} not found"}

        # Create map of base entities (Product Definitions)
        base_entities = [e for e in entities_data if str(e.get('entityTypeId', '')) == PRODUCT_DEFINITION]
        base_entities_map = {str(e['id']): e for e in base_entities}

        # Build Parts list from base entities only
        parts_list = []
        for entity in base_entities:
            if str(entity.get('entityTypeId', '')) == PRODUCT_DEFINITION:
                part_data = get_part_data(
                    entity, categories, categories, base_entities_map, entities_data, type_map
                )
                if part_data:
                    parts_list.append(part_data)
            logging.info(f"Created {len(parts_list)} unique parts")

        # Build tree structure for all entities
        tree = build_entity_tree(entities_data)

        # Build Products tree starting from selected root
        products_tree = build_configuration_tree(
            selected_model_id,
            entities_data,
            tree,
            categories,
            base_entities_map,
            type_map,
            all_categories=categories
        )

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

def get_entity_type_map(entity_types):
    """Create a map of entity types by ID for quick lookup"""
    return {et['name']: str(et['id']) for et in entity_types}

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

    output_path = r"C:\git\VirtualSatellite5_FreeCAD\satellite_structure.json"
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
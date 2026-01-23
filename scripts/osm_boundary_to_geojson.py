import requests
import xml.etree.ElementTree as ET
import json

def get_osm_relation_xml(relation_id):
    url = f"https://api.openstreetmap.org/api/0.6/relation/{relation_id}"
    response = requests.get(url)
    response.raise_for_status()
    return response.content

def get_osm_full_xml(relation_id):
    url = f"https://api.openstreetmap.org/api/0.6/relation/{relation_id}/full"
    response = requests.get(url)
    response.raise_for_status()
    return response.content

def parse_osm_boundary(xml_content):
    tree = ET.ElementTree(ET.fromstring(xml_content))
    root = tree.getroot()
    nodes = {}
    for node in root.findall('node'):
        node_id = node.attrib['id']
        lat = float(node.attrib['lat'])
        lon = float(node.attrib['lon'])
        nodes[node_id] = (lon, lat)
    # Find outer way(s) for the boundary
    outer_ways = []
    for relation in root.findall('relation'):
        for member in relation.findall('member'):
            if member.attrib['type'] == 'way' and member.attrib.get('role') == 'outer':
                outer_ways.append(member.attrib['ref'])
    # Get way node refs
    ways = {}
    for way in root.findall('way'):
        way_id = way.attrib['id']
        nds = [nd.attrib['ref'] for nd in way.findall('nd')]
        ways[way_id] = nds
    # Build coordinates for each outer way
    polygons = []
    for way_id in outer_ways:
        coords = [nodes[nd] for nd in ways[way_id] if nd in nodes]
        polygons.append(coords)
    return polygons

def build_geojson_feature(name, polygons):
    return {
        "type": "Feature",
        "properties": {"name": name},
        "geometry": {
            "type": "Polygon" if len(polygons) == 1 else "MultiPolygon",
            "coordinates": polygons if len(polygons) > 1 else polygons[0]
        }
    }

def main():
    # Több kerület feldolgozása egy listából
    districts = [
        ("I. kerület", 221984),
        ("II. kerület", 221980),
        ("III. kerület", 221976),
        ("IV. kerület", 367963),
        ("V. kerület", 1606103),
        ("VI. kerület", 1606101),
        ("VII. kerület", 1606102),
        ("VIII. kerület", 1606100),
        ("IX. kerület", 1552462),
        ("X. kerület", 1552463),
        ("XI. kerület", 221998),
        ("XII. kerület", 221995),
        ("XIII. kerület", 1605916),
        ("XIV. kerület", 1606043),
        ("XV. kerület", 1606009),
        ("XVI. kerület", 1552464),
        ("XVII. kerület", 1550599),
        ("XVIII. kerület", 1550598),
        ("XIX. kerület", 1551290),
        ("XX. kerület", 1551291),
        ("XXI. kerület", 215618),
        ("XXII. kerület", 215621),
        ("XXIII. kerület", 1550597)
    ]
    features = []
    for name, relation_id in districts:
        print(f"Letöltés: {name} (relation_id: {relation_id})")
        xml_content = get_osm_full_xml(relation_id)
        polygons = parse_osm_boundary(xml_content)
        feature = build_geojson_feature(name, polygons)
        features.append(feature)
    feature_collection = {
        "type": "FeatureCollection",
        "features": features
    }
    # GeoJSON mentése
    with open("budapest_districts.geojson", "w", encoding="utf-8") as f:
        json.dump(feature_collection, f, ensure_ascii=False, indent=2)
    print("\nA kerülethatárok elmentve: budapest_districts.geojson")

    # Python dict mentése importálható formában
    with open("districts_features.py", "w", encoding="utf-8") as f:
        f.write("BUDAPEST_DISTRICTS_FEATURES = ")
        f.write(json.dumps(feature_collection, ensure_ascii=False, indent=2))
    print("A kerülethatárok elmentve: districts_features.py (Python import)")

if __name__ == "__main__":
    main()

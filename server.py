import logging
import configparser
import json
import os
from typing import Union

from bottle import route, run, request, response, hook
from gdal_interfaces import GDALTileInterface

logging.basicConfig(level=logging.INFO,
  format='%(asctime)s %(levelname)s: %(message)s',datefmt='[%Y-%m-%d %I:%M:%S %z]')

class InternalException(ValueError):
    """
    Utility exception class to handle errors internally and return error codes to the client
    """
    pass

print('Reading config file ...')
parser = configparser.ConfigParser()
parser.read('config.ini')

HOST = parser.get('server', 'host')
PORT = parser.getint('server', 'port')
NUM_WORKERS = parser.getint('server', 'workers')
DATA_FOLDER = parser.get('server', 'data-folder')
OPEN_INTERFACES_SIZE = parser.getint('server', 'open-interfaces-size')
URL_ENDPOINT = parser.get('server', 'endpoint')
ALWAYS_REBUILD_SUMMARY = parser.getboolean('server', 'always-rebuild-summary')
CERTS_FOLDER = parser.get('server', 'certs-folder')
CERT_FILE = '%s/cert.crt' % CERTS_FOLDER
KEY_FILE = '%s/cert.key' % CERTS_FOLDER

def test_priority_system():
    """Temporary test to verify the priority system works"""
    try:
        print("\n=== Pre-launch test ===")

        # Test a coordinate that should exist in multiple sources
        test_coords = [
            (34.052235, -118.243683),  # LA - should use high-res if available
            (40.7128, -74.0060),       # NYC
            (0.0, 0.0),                # Gulf of Guinea - should use global fallback
            (67.945528,23.625417),     # Muoniovaara C
            (64.707167,21.177583),     # Ursviken C
            (64.70716666666667,21.17758333333333), # Ursviken C
        ]

        for lat, lng in test_coords:
            logging.info(f"== Got request for ({lat:.6f}, {lng:.6f}) ==")
            #print(f"\nTesting ({lat}, {lng}):")
            try:
                result = interface.lookup(lat, lng)
                if result == interface.NO_DATA_VALUE:
                    logging.info(f"Testing ({lat:.6f}, {lng:.6f}) → No data found")
                    #print(f"  → No data found")
                else:
                    logging.info(f"Testing ({lat:.6f}, {lng:.6f}) → Elevation: {result}m")
                    #print(f"  → Elevation: {result}m")
            except Exception as e:
                print(f"  → Error: {e}")

        print("=== Test Complete ===\n")

    except Exception as e:
        print(f"Priority system test failed: {e}")

# Check if we should use priority mode (if any metadata.json files exist)
def check_for_priority_mode():
    """Check if any metadata.json files exist in the data folder."""
    for root, _, files in os.walk(DATA_FOLDER, followlinks=True):
        if 'metadata.json' in files:
            return True
    return False

# Determine which interface to use
if check_for_priority_mode():
    print('Using priority-based multi-source interface')
    from gdal_interfaces import GDALPriorityTileInterface
    interface = GDALPriorityTileInterface(DATA_FOLDER, f'{DATA_FOLDER}/summary.json', OPEN_INTERFACES_SIZE)
else:
    print('Using standard single-source interface')
    interface = GDALTileInterface(DATA_FOLDER, f'{DATA_FOLDER}/summary.json', OPEN_INTERFACES_SIZE)

if interface.has_summary_json() and not ALWAYS_REBUILD_SUMMARY:
    print('Re-using existing summary JSON')
    interface.read_summary_json()
else:
    print('Creating summary JSON ...')
    interface.create_summary_json()

test_priority_system()

def get_elevation(lat, lng):
    """
    Get the elevation at point (lat,lng) using the currently opened interface
    :param lat:
    :param lng:
    :return:
    """
    try:
        elevation = interface.lookup(lat, lng)

        # Handle no-data scenarios
        if elevation == interface.NO_DATA_VALUE:
            return {
                'latitude': lat,
                'longitude': lng,
                'elevation': None,
                'status': 'no_data'
            }
        else:
            return {
                'latitude': lat,
                'longitude': lng,
                'elevation': elevation,
                'status': 'ok'
            }

    except Exception as e:
        print(f"Elevation lookup failed for ({lat}, {lng}): {e}")
        return {
            'latitude': lat,
            'longitude': lng,
            'elevation': None,
            'status': 'error'
        }

@hook('after_request')
def enable_cors():
    """
    Enable CORS support.
    :return:
    """
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'PUT, GET, POST, DELETE, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Origin, Accept, Content-Type, X-Requested-With, X-CSRF-Token'

def dms_to_decimal(coord: Union[str, float], typ: str = "lat") -> float:
    """
    Convert a coordinate given as DMS **or** decimal to decimal degrees.

    DMS format: [degrees][minutes][seconds].[fractional_seconds][N/S/E/W]
    - Latitude: DDMMSS.fffN / DDMMSS.fffS (max 6 digits before decimal)
    - Longitude: DDDMMSS.fffE / DDDMMSS.fffW (max 7 digits before decimal)

    Returns float in decimal degrees.
    """
    # Fast-path for float
    if isinstance(coord, float):
        return coord

    s = str(coord).strip()
    if not s:
        raise ValueError("Empty coordinate")

    # Detect DMS by trailing direction letter
    direction = s[-1].upper()
    if direction in {"N", "S", "E", "W"}:
        numeric_part = s[:-1].strip()
        if not numeric_part:
            raise ValueError("Missing numeric part for DMS coordinate")

        # Split integer and fractional parts
        if "." in numeric_part:
            int_part, frac_part = numeric_part.split(".", 1)
        else:
            int_part, frac_part = numeric_part, ""

        # Validate that all characters are digits
        if not int_part.isdigit():
            raise ValueError(f"Invalid numeric characters in DMS coordinate: {s}")

        # Determine maximum degrees based on type
        max_deg_len = 2 if typ == "lat" else 3
        min_deg_len = 1

        # Parse DMS: first 1-2 (lat) or 1-3 (lon) digits = degrees, next 2 = minutes, rest = seconds
        for deg_len in range(max_deg_len, min_deg_len - 1, -1):
            if len(int_part) < deg_len:
                continue

            deg = int(int_part[:deg_len])
            remaining = int_part[deg_len:]

            # Must have exactly 2 digits for minutes
            if len(remaining) < 2:
                continue

            min_val = int(remaining[:2])
            sec_str = remaining[2:]  # Everything after minutes

            # Validate minutes
            if min_val > 59:
                continue

            # Combine seconds integer part with fractional part
            if sec_str and frac_part:
                sec = float(f"{sec_str}.{frac_part}")
            elif sec_str:
                sec = float(sec_str)
            elif frac_part:
                sec = float(f"0.{frac_part}")
            else:
                sec = 0.0

            # Calculate decimal degrees
            decimal = abs(deg) + (min_val / 60.0) + (sec / 3600.0)

            # Apply direction sign
            if direction in {"S", "W"}:
                decimal = -decimal

            return decimal

        # If we get here, try treating as simple degrees (no minutes/seconds)
        try:
            deg = float(numeric_part)
            if direction in {"S", "W"}:
                deg = -deg
            return deg
        except ValueError:
            pass

        # Final fallback: treat as decimal with direction
        try:
            return float(numeric_part) * (1 if direction in {"N", "E"} else -1)
        except ValueError:
            raise ValueError(f"Could not parse DMS coordinate: {s}")
    else:
        # Plain decimal
        try:
            return float(s)
        except ValueError:
            raise ValueError(f"Invalid decimal coordinate: {s!r}")

def lat_lng_from_location(location_with_comma: str):
    """
    Parse latitude and longitude from comma-separated string.

    Each coordinate may be:
    - Decimal: "67.945528"
    - DMS: "675643.9N" (degrees + minutes + seconds + direction)
    """
    try:
        parts = [p.strip() for p in location_with_comma.split(',')]
        if len(parts) != 2:
            raise ValueError("Expected exactly two comma-separated values")

        lat = dms_to_decimal(parts[0], "lat")
        lng = dms_to_decimal(parts[1], "lon")

        return float(lat), float(lng)
    except (ValueError, TypeError) as exc:
        raise InternalException(
            json.dumps({
                "error": f'Bad parameter format "{location_with_comma}". Detail: {exc}'
            })
        )

def query_to_locations():
    """
    Grab a list of locations from the query and turn them into [(lat,lng),(lat,lng),...]
    :return:
    """
    locations = request.query.locations
    if not locations:
        raise InternalException(json.dumps({'error': '"Locations" is required.'}))

    return [lat_lng_from_location(l) for l in locations.split('|')]


def body_to_locations():
    """
    Grab a list of locations from the body and turn them into [(lat,lng),(lat,lng),...]
    :return:
    """
    try:
        locations = request.json.get('locations', None)
    except Exception:
        raise InternalException(json.dumps({'error': 'Invalid JSON.'}))

    if not locations:
        raise InternalException(json.dumps({'error': '"Locations" is required in the body.'}))

    latlng = []
    for l in locations:
        try:
            latlng += [ (l['latitude'],l['longitude']) ]
        except KeyError:
            raise InternalException(json.dumps({'error': '"%s" is not in a valid format.' % l}))

    return latlng

def do_lookup(get_locations_func):
    """
    Generic method which gets the locations in [(lat,lng),(lat,lng),...] format by calling get_locations_func
    and returns an answer ready to go to the client.
    :return:
    """
    try:
        locations = get_locations_func()
        return {'results': [get_elevation(lat, lng) for (lat, lng) in locations]}
    except InternalException as e:
        response.status = 400
        response.content_type = 'application/json'
        return e.args[0]

# For CORS
@route(URL_ENDPOINT, method=['OPTIONS'])
def cors_handler():
    return {}

@route(URL_ENDPOINT, method=['GET'])
def get_lookup():
    """
    GET method. Uses query_to_locations.
    :return:
    """
    return do_lookup(query_to_locations)

@route(URL_ENDPOINT, method=['POST'])
def post_lookup():
    """
    GET method. Uses body_to_locations.
    :return:
    """
    return do_lookup(body_to_locations)

if os.path.isfile(CERT_FILE) and os.path.isfile(KEY_FILE):
    print('Using HTTPS')
    run(host=HOST, port=PORT, server='gunicorn', workers=NUM_WORKERS, certfile=CERT_FILE, keyfile=KEY_FILE)
else:
    print('Using HTTP')
    run(host=HOST, port=PORT, server='gunicorn', workers=NUM_WORKERS)

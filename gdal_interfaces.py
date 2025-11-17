import os
from osgeo import gdal, osr
from lazy import lazy
from os import listdir
from os.path import isfile, join, getsize
import json
import logging
from rtree import index
from datetime import datetime

# Set up logging
logging.basicConfig(level=logging.DEBUG,
  format='%(asctime)s %(levelname)s: %(message)s',datefmt='[%Y-%m-%d %H:%M:%S %z]')

def age_in_months(date_str):
    try:
        date = datetime.strptime(date_str, "%Y-%m-%d")
        now = datetime.today()
        delta_days = (now - date).days
        return round(delta_days / 30.4375)
    except (ValueError, TypeError):
        # Return None on malformed date
        return None

class GDALInterface(object):
    SEA_LEVEL = 0
    NO_DATA_VALUE = -9999  # Sentinel for missing/no data
    gdal.UseExceptions()

    def __init__(self, tif_path):
        super(GDALInterface, self).__init__()
        self.tif_path = tif_path
        self.loadMetadata()

    def get_corner_coords(self):
        ulx, xres, xskew, uly, yskew, yres = self.geo_transform
        lrx = ulx + (self.src.RasterXSize * xres)
        lry = uly + (self.src.RasterYSize * yres)
        return {
            'TOP_LEFT': (ulx, uly),
            'TOP_RIGHT': (lrx, uly),
            'BOTTOM_LEFT': (ulx, lry),
            'BOTTOM_RIGHT': (lrx, lry),
        }

    def loadMetadata(self):
        # open the raster and its spatial reference
        self.src = gdal.Open(self.tif_path)

        if self.src is None:
            raise Exception('Could not load GDAL file "%s"' % self.tif_path)
        spatial_reference_raster = osr.SpatialReference(self.src.GetProjection())

        # get the WGS84 spatial reference
        spatial_reference = osr.SpatialReference()
        spatial_reference.ImportFromEPSG(4326)  # WGS84

        # coordinate transformation
        self.coordinate_transform = osr.CoordinateTransformation(spatial_reference, spatial_reference_raster)
        gt = self.geo_transform = self.src.GetGeoTransform()
        dev = (gt[1] * gt[5] - gt[2] * gt[4])
        self.geo_transform_inv = (gt[0], gt[5] / dev, -gt[2] / dev,
                                  gt[3], -gt[4] / dev, gt[1] / dev)

    @lazy
    def points_array(self):
        b = self.src.GetRasterBand(1)
        return b.ReadAsArray()

    def print_statistics(self):
        print(self.src.GetRasterBand(1).GetStatistics(True, True))

    def lookup(self, lat, lon):
        try:
            # get coordinate of the raster
            xgeo, ygeo, zgeo = self.coordinate_transform.TransformPoint(lon, lat, 0)
            # convert it to pixel/line on band
            u = xgeo - self.geo_transform_inv[0]
            v = ygeo - self.geo_transform_inv[3]
            # FIXME this int() is probably bad idea, there should be half cell size thing needed
            xpix = int(self.geo_transform_inv[1] * u + self.geo_transform_inv[2] * v)
            ylin = int(self.geo_transform_inv[4] * u + self.geo_transform_inv[5] * v)

            # Check bounds before accessing array
            if (xpix < 0 or ylin < 0 or
                xpix >= self.src.RasterXSize or
                ylin >= self.src.RasterYSize):
                return self.NO_DATA_VALUE

            # look the value up
            v = self.points_array[ylin, xpix]

            # Handle no-data scenarios
            if v is None:
                return self.NO_DATA_VALUE

            # Convert numpy types to Python int (fix for JSON serialization)
            if hasattr(v, 'item'):  # numpy scalar
                v = v.item()
            else:
                v = int(v)  # Ensure it's a regular Python int

            # Check for common no-data values
            no_data_values = [-32768, -9999, -99999, 32767, 65535]
            if v in no_data_values or v < -10000 or v > 90000:  # Unrealistic values
                return self.NO_DATA_VALUE

            return v if v != -32768 else self.SEA_LEVEL

        except Exception as e:
            print(e)
            return self.NO_DATA_VALUE  # Changed from SEA_LEVEL

    def close(self):
        self.src = None

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self.close()

class GDALTileInterface(object):
    NO_DATA_VALUE = -9999  # Sentinel for missing/no data

    def __init__(self, tiles_folder, summary_file, open_interfaces_size=5):
        super(GDALTileInterface, self).__init__()
        self.tiles_folder = tiles_folder
        self.summary_file = summary_file
        self.index = index.Index()
        self.cached_open_interfaces = []
        self.cached_open_interfaces_dict = {}
        self.open_interfaces_size = open_interfaces_size

    def _open_gdal_interface(self, path):
        if path in self.cached_open_interfaces_dict:
            interface = self.cached_open_interfaces_dict[path]
            self.cached_open_interfaces.remove(path)
            self.cached_open_interfaces += [path]
            return interface
        else:
            interface = GDALInterface(path)
            self.cached_open_interfaces += [path]
            self.cached_open_interfaces_dict[path] = interface

            if len(self.cached_open_interfaces) > self.open_interfaces_size:
                last_interface_path = self.cached_open_interfaces.pop(0)
                last_interface = self.cached_open_interfaces_dict[last_interface_path]
                last_interface.close()
                self.cached_open_interfaces_dict[last_interface_path] = None
                del self.cached_open_interfaces_dict[last_interface_path]

            return interface

    def _all_files(self):
        return [
            os.path.relpath(join(root, f), self.tiles_folder)
            for root, _, files in os.walk(self.tiles_folder, followlinks=True)
            for f in files
            if f.endswith('.tif')
        ]

    def has_summary_json(self):
        return os.path.exists(self.summary_file)

    def create_summary_json(self):
        all_coords = []
        for file in self._all_files():
            full_path = join(self.tiles_folder,file)
            print('Processing %s ... (%s MB)' % (full_path, getsize(full_path) / 2**20))
            i = self._open_gdal_interface(full_path)
            coords = i.get_corner_coords()

            lmin, lmax = coords['BOTTOM_RIGHT'][1], coords['TOP_RIGHT'][1]
            lngmin, lngmax = coords['TOP_LEFT'][0], coords['TOP_RIGHT'][0]
            all_coords += [
                {
                    'file': full_path,
                    'coords': ( lmin,  # latitude min
                                lmax,  # latitude max
                                lngmin,  # longitude min
                                lngmax,  # longitude max

                                )
                }
            ]
            print('Done! LAT (%s,%s) | LNG (%s,%s)\n' % (lmin, lmax, lngmin, lngmax))

        with open(self.summary_file, 'w') as f:
            json.dump(all_coords, f)

        self.all_coords = all_coords

        self._build_index()

    def read_summary_json(self):
        with open(self.summary_file) as f:
            self.all_coords = json.load(f)

        self._build_index()

    def lookup(self, lat, lng):
        """Enhanced lookup that handles no-data internally"""
        try:
            nearest = list(self.index.nearest((lat, lng), 1, objects=True))
            if not nearest:
                return self.NO_DATA_VALUE

            coords = nearest[0].object
            gdal_interface = self._open_gdal_interface(coords['file'])
            elevation = gdal_interface.lookup(lat, lng)

            # GDALInterface.lookup() already returns NO_DATA_VALUE for bad data
            # We just pass it through unchanged
            return elevation

        except Exception as e:
            print(f"Lookup error for ({lat}, {lng}): {e}")
            return self.NO_DATA_VALUE

    def _build_index(self):
        print('Building spatial index ...')
        index_id = 1
        for e in self.all_coords:
            e['index_id'] = index_id
            left, bottom, right, top = (e['coords'][0], e['coords'][2], e['coords'][1], e['coords'][3])
            self.index.insert( index_id, (left, bottom, right, top), obj=e)

class GDALPriorityTileInterface(GDALTileInterface):
    """Extends GDALTileInterface with priority-based source selection."""

    def __init__(self, data_folder, summary_file, open_interfaces_size=5):
        super().__init__(data_folder, summary_file, open_interfaces_size)
        self.source_info = {}  # Maps source directories to effective metadata
        # Build metadata registry at initialization
        self._load_metadata_registry()

    def _load_metadata_registry(self):
        """
        Build effective metadata per directory by walking the hierarchy.
        Each directory inherits from its nearest ancestor with metadata.json,
        unless overridden by fields in its own metadata.json.
        """
        defaults = {
            'priority': 9999,
            'name': 'default',
            'resolution': 2000,
        }

        # Walk the data folder, collect metadata.json per directory
        registry = {}
        for root, _, files in os.walk(self.tiles_folder, followlinks=True):
            if 'metadata.json' in files:
                try:
                    with open(os.path.join(root, 'metadata.json'), 'r') as f:
                        registry[root] = json.load(f)
                except Exception as e:
                    print(f"Error reading metadata from {os.path.join(root, 'metadata.json')}: {e}")

        # Compute effective metadata per directory
        for dirpath in sorted(registry.keys()):
            effective = dict(defaults)

            # Walk from this dir up to root, collecting overrides
            cursor = dirpath
            overrides = []
            while True:
                if cursor in registry:
                    overrides.append(registry[cursor])
                if cursor == self.tiles_folder:
                    break
                parent = os.path.dirname(cursor)
                if parent == cursor:
                    break
                cursor = parent

            # Apply overrides from nearest to farthest (farther override earlier)
            for meta in reversed(overrides):
                effective.update(meta)

            # Ensure required keys exist
            effective.setdefault('priority', defaults['priority'])
            effective.setdefault('name', os.path.basename(dirpath) if dirpath != self.tiles_folder else defaults['name'])
            effective.setdefault('resolution', defaults['resolution'])

            # Store age/dynamic_priority only if present; we handle missing at calc time
            effective['date'] = effective.get('date') if effective.get('date') else None
            effective['dynamic_priority'] = effective.get('dynamic_priority') if effective.get('dynamic_priority') is not None else None
            self.source_info[dirpath] = effective

        # Always ensure the data folder root itself is represented with defaults (or its own metadata)
        if self.tiles_folder not in self.source_info:
            self.source_info[self.tiles_folder] = defaults.copy()
        logging.info(f"Metadata registry loaded for {len(self.source_info)} directories")

    def _effective_metadata_for_file(self, filepath):
        """
        Resolve effective metadata for a file by walking its ancestor directories,
        using the pre-built registry for performance.
        """
        dirpath = os.path.dirname(filepath)

        # Walk up until we match a known registry entry
        cursor = dirpath
        visited = set()
        while cursor and cursor not in self.source_info:
            if cursor in visited:
                break
            visited.add(cursor)
            parent = os.path.dirname(cursor)
            if parent == cursor:
                break
            cursor = parent

        # If nothing matched (shouldn't happen), fallback to data folder defaults
        if cursor and cursor in self.source_info:
            return self.source_info[cursor]
        return self.source_info[self.tiles_folder]

    def create_summary_json(self):
        """Create summary JSON with minimal file-specific information."""
        all_coords = []
        for file in self._all_files():
            full_path = join(self.tiles_folder,file)
            print('Processing %s ... (%s MB)' % (full_path, getsize(full_path) / 2**20))
            i = self._open_gdal_interface(full_path)
            coords = i.get_corner_coords()
            lmin, lmax = coords['BOTTOM_RIGHT'][1], coords['TOP_RIGHT'][1]
            lngmin, lngmax = coords['TOP_LEFT'][0], coords['TOP_RIGHT'][0]

            all_coords += [{
                'file': full_path,
                'coords': (lmin, lmax, lngmin, lngmax),
                'source_dir': os.path.dirname(full_path)  # Only store directory reference
            }]
            print('Done! LAT (%s,%s) | LNG (%s,%s)\n' % (lmin, lmax, lngmin, lngmax))

        with open(self.summary_file, 'w') as f:
            json.dump(all_coords, f)

        self.all_coords = all_coords
        self._build_index()

    def read_summary_json(self):
        """Read summary JSON and build registry (no metadata replication needed)."""
        with open(self.summary_file) as f:
            self.all_coords = json.load(f)

        # Registry already built in __init__
        self._build_index()

    def lookup(self, lat, lng):
        """Enhanced lookup with priority-based source selection."""
        logging.info(f"Looking up elevation for ({lat:.6f}, {lng:.6f})")
        try:
            # Use a precise bounding box to find only tiles that actually contain this point
            # Expand by a tiny epsilon to catch tiles that exactly touch this coordinate
            epsilon = 0.0001  # About 10 meters
            bbox = (lat - epsilon, lng - epsilon, lat + epsilon, lng + epsilon)

            # Find tiles that contain this coordinate
            candidates = list(self.index.intersection(bbox, objects=True))

            if not candidates:
                logging.info(f"No tiles found for coordinate ({lat:.6f}, {lng:.6f})")
                return self.NO_DATA_VALUE

            logging.info(f"Found {len(candidates)} candidate tiles")
            for i, candidate in enumerate(candidates):
                tile_info = candidate.object
                logging.info(
                    f"  {i+1}. Tile: {os.path.basename(tile_info['file'])} "
                    f"(source_dir: {os.path.basename(tile_info.get('source_dir', ''))})"
                )

            # Optimization: If only one candidate, use it directly
            if len(candidates) == 1:
                gdal_interface = self._open_gdal_interface(candidates[0].object['file'])
                elevation = gdal_interface.lookup(lat, lng)
                if elevation != self.NO_DATA_VALUE:
                    logging.info(f"  → Single candidate elevation: {elevation}m")
                    return elevation
                else:
                    return self.NO_DATA_VALUE

            # Compute effective metadata and dynamic priority for each candidate
            adjusted = []
            for candidate in candidates:
                tile_info = candidate.object
                eff_meta = self._effective_metadata_for_file(tile_info['file'])
                # Determine if we need dynamic priority calculation
                needs_dynamic = eff_meta.get('dynamic_priority') is not None
                if needs_dynamic:
                    final_priority = self._calculate_dynamic_priority(tile_info, eff_meta)
                else:
                    final_priority = eff_meta.get('priority', 9999)
                adjusted.append((final_priority, eff_meta.get('resolution', 3000), candidate))

            # Sort by priority, then by resolution
            adjusted.sort(key=lambda x: (x[0], x[1]))
            logging.info("Priority-adjusted candidates:")
            for i, (p, r, candidate) in enumerate(adjusted):
                tile_info = candidate.object
                eff_meta = self._effective_metadata_for_file(tile_info['file'])
                logging.info(
                    f"  {i+1}. Tile: {os.path.basename(tile_info['file'])} "
                    f"(priority: {p}, "
                    f"resolution: {eff_meta.get('resolution','?')}m)"
                )

            # Try candidates in priority order
            logging.info("Trying in priority order:")
            for i, (p, r, candidate) in enumerate(adjusted):
                tile_info = candidate.object
                eff_meta = self._effective_metadata_for_file(tile_info['file'])
                gdal_interface = self._open_gdal_interface(tile_info['file'])
                logging.info(
                    f"  {i+1}. Trying {os.path.basename(tile_info['file'])} "
                    f"(priority: {p}, "
                    f"resolution: {eff_meta.get('resolution','?')}m)"
                )
                try:
                    elevation = gdal_interface.lookup(lat, lng)
                    if elevation != self.NO_DATA_VALUE:
                        logging.info(f"    ✓ Success! Elevation: {elevation}m")
                        return elevation
                    else:
                        logging.info(f"    ✗ No data in this tile, trying next...")
                except Exception as e:
                    logging.error(f"    ✗ Error in tile: {e}")
                    continue
            logging.warning(
                f"No elevation data found for ({lat:.6f}, {lng:.6f}) "
                f"in any source (tried {len(candidates)} tiles)"
            )
            return self.NO_DATA_VALUE
        except Exception as e:
            print(f"Lookup error for ({lat}, {lng}): {e}")
            return self.NO_DATA_VALUE

    def _calculate_dynamic_priority(self, tile_info, eff_meta):
        """
        Compute dynamic priority using effective metadata (eff_meta) for the file.
        Formula: base - (1000 - resolution_adj) - (360 - age_in_months_adj) - dynamic_priority_adj
        """
        logging.info(f"## Adjusting priority for {eff_meta['name']} ##")
        # Get the starting priority directly from the effective metadata
        starting_priority = eff_meta['priority']

        # Check if dynamic_priority exists, if not, return the starting priority without changes
        if eff_meta.get("dynamic_priority") is None:
            logging.info(f"dynamic_priority not set, return original value")
            return starting_priority

        # Extract dynamic_priority if it exists
        dynamic_priority = eff_meta.get("dynamic_priority")

        logging.debug(f"Initial priority: {eff_meta['priority']}")
        logging.debug(f"- Resolution adjustment: 1000-resolution = {1000 - eff_meta['resolution']}")

        # Handle missing date: if there's no 'date', we can either set age to 0 or skip it.
        dataset_age = None
        if eff_meta.get('date'):
            dataset_age = age_in_months(eff_meta['date'])
            if dataset_age is None:
                logging.warn(f"Error: Invalid date format '{eff_meta['date']}' for {eff_meta['name']}. Using default age.")
                dataset_age = 360  # Default to 30 years (360 months)
        else:
            dataset_age = 360  # If no date, set age to 0 months (or you can choose another default value)
        # Apply the dynamic priority formula
        priority = starting_priority - (1000 - eff_meta['resolution']) - (360 - dataset_age) - dynamic_priority

        logging.debug(f"- Adjustment (dynamic): {dynamic_priority}")
        logging.debug(f"- Age adjustment: 360-age = {360 - dataset_age}")
        logging.debug(f"= {priority}")
        return priority

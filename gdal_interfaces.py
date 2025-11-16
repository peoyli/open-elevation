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
logging.basicConfig(level=logging.INFO,
  format='%(asctime)s %(levelname)s: %(message)s',datefmt='[%Y-%m-%d %I:%M:%S %z]')

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
        self.source_info = {}  # Maps source IDs to source priority info

    def _get_source_info(self, filepath):
        """Extract source priority information from filepath."""
        # Default to lowest priority if no metadata
        default_priority = 9999
        default_name = "default"
        default_resolution = 2000

        # Check if we already computed this source
        for source_dir, info in self.source_info.items():
            if filepath.startswith(source_dir):
                return info

        # Determine source directory for this file
        source_dir = filepath
        while source_dir != self.tiles_folder:
            source_dir = os.path.dirname(source_dir)
            metadata_file = os.path.join(source_dir, 'metadata.json')

            if os.path.exists(metadata_file):
                try:
                    with open(metadata_file, 'r') as f:
                        metadata = json.load(f)

                    priority = metadata.get('priority', default_priority)
                    name = metadata.get('name', os.path.basename(source_dir))
                    resolution = metadata.get('resolution', default_resolution)

                    # Store for reuse
                    info = {'priority': priority, 'name': name, 'resolution': resolution}

                    if 'date' in metadata:
                        info['date'] = metadata.get('date')
                    if 'dynamic_priority' in metadata:
                        info['dynamic_priority'] = metadata.get('dynamic_priority')

                    self.source_info[source_dir] = info
                    return info
                except Exception as e:
                    print(f"Error reading metadata from {metadata_file}: {e}")

        # No metadata found, use defaults
        info = {'priority': default_priority, 'name': default_name, 'resolution': default_resolution}
        self.source_info[self.tiles_folder] = info  # Store for reuse
        return info

    def create_summary_json(self):
        """Create summary JSON with source priority information."""
        all_coords = []
        for file in self._all_files():
            full_path = join(self.tiles_folder,file)
            print('Processing %s ... (%s MB)' % (full_path, getsize(full_path) / 2**20))
            i = self._open_gdal_interface(full_path)
            coords = i.get_corner_coords()
            lmin, lmax = coords['BOTTOM_RIGHT'][1], coords['TOP_RIGHT'][1]
            lngmin, lngmax = coords['TOP_LEFT'][0], coords['TOP_RIGHT'][0]

            # Get both priority AND resolution from metadata
            #priority = self._get_file_priority(full_path)
            #resolution = self._get_file_resolution(full_path)

            # Get source priority information
            source_info = self._get_source_info(full_path)
            name = source_info['name']
            priority = source_info['priority']
            resolution = source_info['resolution']

            all_coords += [{
                'file': full_path,
                'coords': (lmin, lmax, lngmin, lngmax),
                'source_name': name,
                'priority': priority,
                'resolution': resolution,
                'date': source_info.get('date'),
                'dynamic_priority': source_info.get('dynamic_priority')
            }]
            print('Done! LAT (%s,%s) | LNG (%s,%s) | Priority: %s | Resolution: %sm\n' % (lmin, lmax, lngmin, lngmax, priority, resolution))

        with open(self.summary_file, 'w') as f:
            json.dump(all_coords, f)

        self.all_coords = all_coords
        self._build_index()

    def read_summary_json(self):
        """Read summary JSON with source priority information."""
        with open(self.summary_file) as f:
            self.all_coords = json.load(f)

        # Load source information from summary entries
        for entry in self.all_coords:
            source_dir = os.path.dirname(entry['file'])
            self.source_info[source_dir] = {
                'priority': entry['priority'],
                'name': entry['source_name'],
                'resolution': entry['resolution']
            }
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
                  f"(priority: {tile_info['priority']}, "
                  f"resolution: {tile_info['resolution']}m)"
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

            # Check if ANY candidate has dynamic_priority
            has_dynamic = any('dynamic_priority' in candidate.object for candidate in candidates)

            if has_dynamic:
                # Calculate dynamic priorities only for those that need it
                for candidate in candidates:
                    if 'dynamic_priority' in candidate.object:
                        tile_info = candidate.object
                        adjusted_priority = self._calculate_dynamic_priority(tile_info)
                        tile_info['priority'] = adjusted_priority

                # Show adjusted candidates
                logging.info("Priority-adjusted candidates:")
                for i, candidate in enumerate(candidates):
                    tile_info = candidate.object
                    logging.info(
                      f"  {i+1}. Tile: {os.path.basename(tile_info['file'])} "
                      f"(priority: {tile_info['priority']}, "
                      f"resolution: {tile_info['resolution']}m)"
                    )

            # Sort the candidates in priority order, then by resolution (lower number = higher priority)
            # resolution is only important when two candidates have the same priority
            sorted_candidates = sorted(candidates, key=lambda x: (x.object.get('priority', 9999), x.object.get('resolution', 3000)))
            logging.info("Candidates sorted by priority:")
            for i, candidate in enumerate(sorted_candidates):
                tile_info = candidate.object
                logging.info(
                  f"  {i+1}. Tile: {os.path.basename(tile_info['file'])} "
                  f"(priority: {tile_info['priority']}, "
                  f"resolution: {tile_info['resolution']}m)"
                )

            # Try candidates in priority order, done when a value is returned
            logging.info("Trying in priority order:")
            for i, candidate in enumerate(sorted_candidates):
                tile_info = candidate.object
                gdal_interface = self._open_gdal_interface(tile_info['file'])
                logging.info(
                  f"  {i+1}. Trying {os.path.basename(tile_info['file'])} "
                  f"(priority: {tile_info['priority']}, "
                  f"resolution: {tile_info['resolution']}m)"
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

    def _calculate_dynamic_priority(self, tile_info):
        logging.info(f"## Adjusting priority for {tile_info['source_name']} ##")
        # Get the starting priority directly from the tile information
        starting_priority = tile_info['priority']

        # Check if dynamic_priority exists, if not, return the starting priority without changes
        if "dynamic_priority" not in tile_info:
            logging.info(f"dynamic_priority not set, return original value")
            return starting_priority

        # Extract dynamic_priority if it exists
        dynamic_priority = tile_info.get("dynamic_priority")

        logging.debug(f"Initial priority: {tile_info['priority']}")
        logging.debug(f"- Resolution adjustment: 1000-resolution = {1000 - tile_info['resolution']}")

        # Handle missing date: if there's no 'date', we can either set age to 0 or skip it.
        if 'date' in tile_info:
            dataset_age = age_in_months(tile_info['date'])
            if dataset_age is None:
                logging.warn(f"Error: Invalid date format '{tile_info['date']}' for {tile_info['source_name']}. Using default age.")
                dataset_age = 360  # Default to 30 years (360 months)
                tile_info['date'] = "Invalid date"
        else:
            dataset_age = 360  # If no date, set age to 0 months (or you can choose another default value)
            tile_info['date'] = "No date"

        # Apply the dynamic priority formula
        # The formula for decreasing calculated priority with increasing resolution:
        #priority = starting_priority - (1000 - dataset['resolution']) + dataset_age - dynamic_priority
        priority = starting_priority - (1000 - tile_info['resolution']) - (360 - dataset_age) - dynamic_priority

        logging.debug(f"- Adjustment (dynamic): {dynamic_priority}")
        logging.debug(f"- Age adjustment: 360-age = {360 - dataset_age}")
        logging.debug(f"= {priority}")
        return priority

# v1.0-enhanced-base

**Tagged Commit:** 38a4994
**Date:** 2025-11-17
**Branch:** main

## Overview
Stable base version before priority system integration.

## Features
- Base elevation service with robust DMS handling
- No-data status responses
- Recursive data folder scanning with symlinks
- Comprehensive test coverage

## Technical Details
- API endpoints remain unchanged
- Backward compatible
- Ready for feature branch integration

## Detailed changelog
Feature (server.py):
- Handle no-data (return 'None' for elevation value)
- Return status ('ok', 'no_data' or 'error') on lookups
- Add DMS conversion of input parameters
  Feature-test files:
    Test cases sent to API using decimal and DMS coordinates + some incorrect cases
    tests/dms-conversion/coordinate-tests.py
    Pre-implementation tests, standalone testing before implementation
    tests/dms-conversion/pre-implementation-tests.py

Feature (gdal_interfaces.py):
- Handle no-data scenarios, return NO_DATA_VALUE (-9999) for lookups with no data
- Add recursive scanning of data folders, follow symbolic links for dataset folders

Minor changes:
- Doc: Update documentation links so they refer back to this repository
- Doc: Add gdal installation commands for Linux

2025-11-14 commit 38a4994f62a9d533296d006dad230925a5e52593
    Fix: _all_files in GDALTileInterface now follow symbolic links inside the 'data' folder

2025-11-14 commit cb20cab8f517d679bd45249775b436a97c239d74
    Add gdal.UseExceptions() in GDALInterface to avoid 'FutureWarning'

2025-11-13 commit 741358c4315df766b35bca2c0e1bce1545c66597
    Add no-data handling for elevation lookups

    - Add NO_DATA_VALUE (-9999) constant to distinguish missing elevation data
    - Return elevation: null for locations without data instead of 0 (sea level)
    - Add 'status' field to API responses (ok/no_data/error) for client clarity
    - Fix JSON serialization for numpy int16 types from GDAL data
    - Preserve full floating-point precision from elevation datasets
    - Improve bounds checking to prevent out-of-range coordinate errors

    This change allows API consumers to distinguish between:
    - Real sea level (elevation: 0, status: ok)
    - Missing elevation data (elevation: null, status: no_data)
    - Coordinate lookup errors (elevation: null, status: error)"

    Before vs After API Response
    {"results": [{"latitude": 89.5, "longitude": 45.0, "elevation": 0}]}
    {"results": [{"latitude": 89.5, "longitude": 45.0, "elevation": null, "status": "no_data"}]}

2025-11-13 commit 9f98de1101eb4d677aaa4690207f468b28470e12
    Add coordinate test cases for DMS conversion

2025-11-13 commit 5cd636b91759c97c5a9e63df18e4d79a59c16a23
    Add pre-implementation test cases for DMS conversion

2025-11-13 commit 269896c5e016960b657f08bdf6bf2b890d28e515
    Implement DMS conversion logic in server.py

2025-11-10 commit 0ef6f6e86206695a6291ac12a397d21ad6f02a3f
    Add 'apt install' commands for gdal

2025-11-10 commit 933360fc59d22f7f2ff41f42bcafc03169976e7b
    Made scanning of data folder recursive

2025-11-10 commit e00fbe94fd48f805f12b7ff9f911a2abd1df618f
    Update github links to documentation and repository in commands

2025-11-10
Initial clone from https://github.com/Jorl17/open-elevation
commit 677f9de1b6c1a10b48028f36e072bf8b6ba19b9e
Author: João Ricardo Lourenço <jorl17.8@gmail.com>
Date:   Thu Sep 16 13:19:52 2021 +0100

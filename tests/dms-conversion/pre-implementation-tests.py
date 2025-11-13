import re
import json
from typing import Union

class InternalException(Exception):
    """Custom exception used in the service."""
    pass

def dms_to_decimal(coord: Union[str, float], typ: str = "lat") -> float:
    """
    Convert a coordinate given as DMS **or** decimal to decimal degrees.
    
    DMS format: [degrees][minutes][seconds].[fractional_seconds][N/S/E/W]
    - Latitude: DDMMSS.fffN (max 6 digits before decimal)
    - Longitude: DDDMMSS.fffE (max 7 digits before decimal)
    
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

# Test coordinates
test_coordinates = [
    # Original DMS cases
    ("675643.9N,233731.5E", 67.9455277778, 23.6254166667),
    ("675643.9S,233731.5W", -67.9455277778, -23.6254166667),
    ("675643.9N,1574905.9W", 67.9455277778, -157.8183055556),
    ("375025.6S,1445537.2E", -37.8404444444, 144.9270000000),
    ("345223.5N,1182436.8E", 34.8731944444, 118.4102222222),
    
    # Decimal equivalents
    ("67.9455277778,23.6254166667", 67.9455277778, 23.6254166667),
    ("-67.9455277778,-23.6254166667", -67.9455277778, -23.6254166667),
    ("67.9455277778,-157.8183055556", 67.9455277778, -157.8183055556),
    ("-37.8404444444,144.9270000000", -37.8404444444, 144.9270000000),
    ("34.8731944444,118.4102222222", 34.8731944444, 118.4102222222),
    
    # Additional DMS cases
    ("0N,0E", 0.0, 0.0),
    ("90N,180E", 90.0, 180.0),
    ("90S,180W", -90.0, -180.0),
    ("5N,6E", 5.0, 6.0),
    ("5615N,12345E", 56.25, 123.75),
    
    # Mixed formats
    ("56.5,232400E", 56.5, 232.6666666667),
    ("5630.5N,23.4", 56.5001388889, 23.4),
    
    # Decimal with direction
    ("89.999999N,179.999999E", 89.999999, 179.999999),
    ("895959.9N,1795959.9E", 89.9999722222, 179.9999722222),
]

def run_tests():
    passed = 0
    total = len(test_coordinates)
    
    print("Running DMS coordinate tests:")
    for input_str, expected_lat, expected_lng in test_coordinates:
        try:
            lat, lng = lat_lng_from_location(input_str)
            if abs(lat - expected_lat) < 1e-8 and abs(lng - expected_lng) < 1e-8:
                print(f"✓ PASS: {input_str}")
                passed += 1
            else:
                print(f"✗ FAIL: {input_str}")
                print(f"  Expected: ({expected_lat:.10f}, {expected_lng:.10f})")
                print(f"  Got:      ({lat:.10f}, {lng:.10f})")
        except Exception as e:
            print(f"✗ ERROR: {input_str}")
            print(f"  Exception: {e}")
    
    print(f"\nResults: {passed}/{total} tests passed")

if __name__ == "__main__":
    run_tests()

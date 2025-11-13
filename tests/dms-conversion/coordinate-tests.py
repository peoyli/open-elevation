import requests

def send_coordinate_to_api(coordinate, api_endpoint="http://localhost:8080/api/v1/lookup?locations="):
    """Sends a coordinate string to the API and prints the response."""
    try:
        response = requests.get(f"{api_endpoint}{coordinate}")
        response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
        print(f"Response for '{coordinate}':\n {response.text}")

    except requests.exceptions.RequestException as e:
        print(f"Error sending coordinate '{coordinate}': {e}")


if __name__ == "__main__":
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

  for coord, expected_lat, expected_lng in test_coordinates:
    send_coordinate_to_api(coord)

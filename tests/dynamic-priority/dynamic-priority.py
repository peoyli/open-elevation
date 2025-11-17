from datetime import datetime

def age_in_months(date_str):
    try:
        date = datetime.strptime(date_str, "%Y-%m-%d")
        now = datetime.today()
        delta_days = (now - date).days
        return round(delta_days / 30.4375)
    except (ValueError, TypeError):
        # Return None on malformed date
        return None

datadate = "2020-10-13"
months = age_in_months(datadate)
print(f"Months since {datadate}: {months}")

# Example test data with initial priorities
test_data = [
    {"name": "ALOS 30m", "priority": 2000, "resolution": 30,
     "date": "2006-01-24", "updated": "2020-05-15", "dynamic_priority": 10},
    {"name": "ArcticDEM 32m", "priority": 2000, "resolution": 32,
     "date": "2017-03-15", "updated": "2021-08-10", "dynamic_priority": 5},
    {"name": "ArcticDEM 100m", "priority": 2500, "resolution": 100,
     "date": "2017-03-15", "updated": "2021-08-10"},
    {"name": "SRTM NE 250m", "priority": 3000, "resolution": 250,
     "date": "2000-02-22", "updated": "2014-10-02", "dynamic_priority": 0},

    {"name": "SRTM SE", "priority": 3000, "resolution": 250,
     "date": "2xxx-xx-xx", "updated": "2014-10-02", "dynamic_priority": -5},
    {"name": "SRTM SE no date", "priority": 3000, "resolution": 250,
     "dynamic_priority": -5},

    {"name": "SRTM W", "priority": 3000, "resolution": 250,
     "date": "2000-02-22", "updated": "2014-10-02"},

    {"name": "Test dynamic no date", "priority": 3000, "resolution": 250, "dynamic_priority": -5},

    {"name": "Test no date", "priority": 3000, "resolution": 250}
]

# Real functions

def calculate_dynamic_priority(dataset):
    print(f"\n## Adjusting priority for {dataset['name']} ##")
    # Get the starting priority directly from the dataset
    starting_priority = dataset['priority']

    # Check if dynamic_priority exists, if not, return the starting priority without changes
    if "dynamic_priority" not in dataset:
        print(f"dynamic_priority not set, return original value")
        return starting_priority

    # Extract dynamic_priority if it exists
    dynamic_priority = dataset.get("dynamic_priority")

    print(f"Initial priority: {dataset['priority']}")
    print(f"- Resolution adjustment: 1000-resolution = {1000 - dataset['resolution']}")

    # Handle missing date: if there's no 'date', we can either set age to 0 or skip it.
    if 'date' in dataset:
        dataset_age = age_in_months(dataset['date'])
        if dataset_age is None:
            print(f"Error: Invalid date format '{dataset['date']}' for {dataset['name']}. Using default age.")
            dataset_age = 360  # Default to 30 years (360 months)
            dataset['date'] = "Invalid date"
    else:
        dataset_age = 360  # If no date, set age to 0 months (or you can choose another default value)
        dataset['date'] = "No date"

    # Apply the dynamic priority formula
    # The formula for decreasing calculated priority with increasing resolution:
    #priority = starting_priority - (1000 - dataset['resolution']) + dataset_age - dynamic_priority
    priority = starting_priority - (1000 - dataset['resolution']) - (360 - dataset_age) - dynamic_priority

    print(f"- Adjustment (dynamic): {dynamic_priority}")
    print(f"- Age adjustment: 360-age = {360 - dataset_age}")
    print("=")
    return priority

def print_elevation_data(datasets):
    for data in datasets:
        name = data.get("name")
        priority = data.get("priority", 0)
        resolution = data.get("resolution",2000)
        date = data.get("date", "No date available")
        updated = data.get("updated", "No update date available")
        dynamic_priority = data.get("dynamic_priority", 0)

        # Calculate dynamic priority based on the formula
        dynamic_priority_value = calculate_dynamic_priority(data)

        print(f"Name: {name}, Initial Priority: {priority}, Dynamic Priority (calculated): {dynamic_priority_value}, Resolution: {resolution}m\n Date: {date}, Updated: {updated}")

def onlyprint_elevation_data(datasets):
    for data in datasets:
        name = data.get("name")
        priority = data.get("priority")
        resolution = data.get("resolution")
        date = data.get("date", "No date available")
        updated = data.get("updated", "No update date available")
        print(f"Name: {name}, Priority: {priority}, Resolution: {resolution}m, Date: {date}, Updated: {updated}")

# Test the function with the updated data
print("== Initial data ==")
onlyprint_elevation_data(test_data)

print("\n== Priority adjustment ==")
# Test the function with the updated data
print_elevation_data(test_data)

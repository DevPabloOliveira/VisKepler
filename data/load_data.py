import os
import geopandas as gpd
import pandas as pd

def read_geojsons(*directories):
    geojsons = {}
    for directory in directories:
        if not os.path.exists(directory):
            continue
        for file in os.listdir(directory):
            file_path = os.path.join(directory, file)
            if file.endswith('.geojson'):
                try:
                    geojsons[file] = gpd.read_file(file_path)
                    print(f"Loaded GeoJSON file: {file_path}")
                except Exception as e:
                    print(f"Error reading GeoJSON {file_path}: {e}")
            elif file.endswith('.csv'):
                try:
                    geojsons[file] = pd.read_csv(file_path)
                    print(f"Loaded CSV file: {file_path}")
                except Exception as e:
                    print(f"Error reading CSV {file_path}: {e}")
    return geojsons

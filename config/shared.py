import json
import os
from os import listdir
from os.path import isfile, join

# Get the list of configuration files
def read_configs(config_path):
    only_files = [f for f in listdir(config_path) if isfile(join(config_path, f))]
    # filter json files
    json_files = [f for f in only_files if f.lower().endswith(".json")]
    configs = []

    for json_file in json_files:
        file_path = os.path.join(config_path, json_file)
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                config = json.load(f)
                configs.append(config)
        except json.JSONDecodeError as e:
            print(f"Error decoding JSON from file {file_path}: {e}")
        except Exception as e:
            print(f"Error reading file {file_path}: {e}")
    return configs

def load_user_config():
    try:
        with open("./config/config.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON from user config file: {e}")
    except Exception as e:
        print(f"Error reading user config file: {e}")

import sys
import os
import glob
import pickle
import json
import numpy as np
import pandas as pd

class CustomJSONEncoder(json.JSONEncoder):
    """
    Custom JSON encoder to handle NumPy and Pandas data types.
    """
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, np.floating):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, (pd.DataFrame, pd.Series)):
            return obj.to_dict()
        elif isinstance(obj, pd.Timestamp):
            return obj.isoformat()
        return super(CustomJSONEncoder, self).default(obj)

def inspect_latest_pickle_json(folder_path='../gym_continuousDoubleAuction/episode_data'):
    """
    Finds the latest .pkl file in the specified folder, unpacks it, and saves its content to a JSON file.
    """
    # Check if directory exists
    if not os.path.exists(folder_path):
        # Fallback for relative path if running from different directories
        if not os.path.exists('episode_data'):
            print(f"Error: Directory '{folder_path}' or 'episode_data' not found.")
            return
        folder_path = 'episode_data'

    # Find all .pkl files in the directory
    pkl_files = glob.glob(os.path.join(folder_path, '*.pkl'))

    if not pkl_files:
        print(f"No .pkl files found in '{folder_path}'.")
        return

    # Get the latest file based on modification time
    latest_file = max(pkl_files, key=os.path.getmtime)
    print(f"Latest file found: {latest_file}\n")

    # Create an output filename
    output_filename = 'latest_episode_data.json'
    
    try:
        with open(latest_file, 'rb') as f:
            data = pickle.load(f)
        
        with open(output_filename, 'w') as out_f:
            json.dump(data, out_f, cls=CustomJSONEncoder, indent=4)
            
        print(f"Data successfully written to {output_filename}")

    except Exception as e:
        print(f"Error reading {latest_file} or writing JSON: {e}")

if __name__ == "__main__":
    # Allow user to pass a custom folder path as an argument
    if len(sys.argv) > 1:
        inspect_latest_pickle_json(sys.argv[1])
    else:
        inspect_latest_pickle_json()

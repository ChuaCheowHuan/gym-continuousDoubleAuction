import sys
import os
import glob
import pickle
import pprint

# logical imports for unpickling
import numpy as np
import pandas as pd
import sys

def inspect_latest_pickle(folder_path='../gym_continuousDoubleAuction/episode_data'):
    """
    Finds the latest .pkl file in the specified folder, unpacks it, and displays its content.
    """
    # Check if directory exists
    if not os.path.exists(folder_path):
        print(f"Error: Directory '{folder_path}' not found.")
        return

    # Find all .pkl files in the directory
    pkl_files = glob.glob(os.path.join(folder_path, '*.pkl'))

    if not pkl_files:
        print(f"No .pkl files found in '{folder_path}'.")
        return

    # Get the latest file based on modification time
    latest_file = max(pkl_files, key=os.path.getmtime)
    print(f"Latest file found: {latest_file}\n")

    # latest_file = '../gym_continuousDoubleAuction/episode_data/942f38b1ed534369af2c3cd0a3ad5d6a.pkl'
    # print(f"Latest file found: {latest_file}\n")

    # Create an output filename
    output_filename = 'latest_episode_data.txt'
    
    try:
        with open(latest_file, 'rb') as f:
            data = pickle.load(f)
        
        with open(output_filename, 'w') as out_f:
            out_f.write(f"--- Content of {latest_file} ---\n")
            if isinstance(data, (dict, list)):
                pprint.pprint(data, stream=out_f)
            else:
                out_f.write(str(data))
            out_f.write("\n--- End of File ---\n")
            
        print(f"Data successfully written to {output_filename}")

    except Exception as e:
        print(f"Error reading {latest_file}: {e}")

if __name__ == "__main__":
    # Allow user to pass a custom folder path as an argument
    if len(sys.argv) > 1:
        inspect_latest_pickle(sys.argv[1])
    else:
        inspect_latest_pickle()

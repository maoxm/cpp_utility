"""Common utils
"""
import os, sys, shutil, fnmatch


# Return ["top level path to root google3", "relative path after that"
def find_google3_path(file_path):
  path_array = os.path.abspath(file_path).split("/")
  # find first google3
  i = path_array.index("google3")
  return ["/".join(path_array[:i + 1]), "/".join(path_array[i + 1:])]

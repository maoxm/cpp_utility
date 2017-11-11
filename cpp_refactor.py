#!/usr/bin/python

import os, glob, subprocess, sys, re, shutil
import common
import cpp_partial_parser
import pprint

DEBUG = False


def find_header_file(fin):
  while True:
    lc = fin.readline()
    if not lc:
      break
    m = re.match(r'^#include.*"(.*)"', lc)
    if m:
      return m.group(1)


def remove_str(str_in, target):
  str_in_list = str_in.split()
  if target in str_in_list:
    str_in_list.remove(target)
  return " ".join(str_in_list)


# Generates the key of each functions that can be used as key in the hashtable
def add_function_key(functions):
  for f in functions:
    # skip "static" in prefix
    prefix = remove_str(f["prefix"], "static")
    # skip "override" in suffix
    suffix = remove_str(f["suffix"], "override")
    keys = []
    keys.append(prefix)
    keys.append(f["return"])
    keys.append(f["name"])
    for each_input in f["sig"]:
      # append input type name only, not the default value
      keys.append(each_input[0])
    keys.append(suffix)
    f["key"] = " ".join(keys)


def get_uniques(functions):
  result = {}
  for i in range(len(functions)):
    name = functions[i]["name"]
    if name in result:
      result[name] = -1
    else:
      result[name] = i
  return result


def compare_functions(header_functions, cc_functions):
  cc_keys = {}
  for i in range(len(cc_functions)):
    cc_keys[cc_functions[i]["key"]] = i

  header_delete = []
  for i in range(len(header_functions)):
    key = header_functions[i]["key"]
    if key in cc_keys:
      del cc_keys[key]
      continue
    header_delete.append(i)

  cc_add = sorted(cc_keys.values())
  if len(cc_add) == 0:
    # only deletion
    print "INFO: changed 0, delete", len(header_delete)
    return []
  if len(cc_add) == 1 and len(header_delete) == 1:
    # one add and one delete
    h_i = header_delete[0]
    cc_i = cc_add[0]
    header_functions[h_i]["change_to"] = cc_i
    if DEBUG:
      print "DEBUG: one function changed: ", h_i, " to ", cc_i
    print "INFO: change 1 only"
    return []

  # last try to pair add and delete by unique function name
  header_unique = get_uniques(header_functions)
  cc_unique = get_uniques(cc_functions)
  header_delete_name_index_map = {}
  for i in header_delete:
    header_delete_name_index_map[header_functions[i]["name"]] = i
  # Real add is final added function from cc files after matching pairs
  real_add = []
  change_num = 0
  for i in cc_add:
    name = cc_functions[i]["name"]
    if name in cc_unique and cc_unique[name] >= 0 and name in header_unique and header_unq[name] >= 0:
      # found pair match
      header_functions[header_delete_name_index_map[name]]["change_to"] = i
      del header_delete_name_index_map[name]
      change_num += 1
      if DEBUG:
        print "DEBUG: found pair on", name
    else:
      real_add.append(i)
  header_delete = sorted(header_delete_name_index_map.values())
  for i in header_delete:
    header_functions[i]["delete"] = True
  print "INFO: changed", change_num, "delete", len(header_delete), "add", len(
      real_add)
  return real_add


def generate_function_string(base_f, mod_f=None):

  if mod_f is None:
    target = base_f
  else:
    target = mod_f

  prefix = target["prefix"]
  suffix = target["suffix"]
  name = target["name"]
  f_return = target["return"]
  args = target["sig"]

  if mod_f is not None:
    if "static" in base_f["prefix"].split():
      prefix = "static " + prefix

    if "override" in base_f["suffix"].split():
      suffix += " override"

    # hash args with default values
    defaults = {}
    for each_sig in base_f["sig"]:
      if each_sig[1] is None:
        continue
      defaults[each_sig[0]] = each_sig[1]

    # see if defaults can match
    for each_sig in mod_f["sig"]:
      key = each_sig[0]
      if key in defaults:
        each_sig[1] = defaults[key]

  # Now generate string
  result = " ".join([prefix, f_return, name]) + "("
  # add args
  arg_str_list = []
  for each_sig in args:
    arg_str = ""
    arg_str += each_sig[0]
    if each_sig[1] is not None:
      arg_str += "=" + each_sig[1]
    arg_str_list.append(arg_str)

  result += ", ".join(arg_str_list)

  result += ")"
  if suffix != "":
    result += " " + suffix
  result += ";\n"
  return result


def update_header_file(header_file, header_lines, header_functions,
                       cc_functions, class_offset):
  add_function_key(header_functions)
  add_function_key(cc_functions)
  cc_add = compare_functions(header_functions, cc_functions)
  public_pos = cpp_partial_parser.find_public_line(header_lines, class_offset)

  # Now we have everything to process
  out_file = header_file + ".modified_by_cpp_refactor.h"
  with open(out_file, "w") as fout:
    header_f_i = 0
    header_l_i = 0
    while header_l_i < len(header_lines):
      if header_f_i < len(header_functions):
        curr_f = header_functions[header_f_i]
        f_range = curr_f["range"]
        if f_range[0] + class_offset == header_l_i:
          header_f_i += 1
          # check function changed or not
          if "change_to" in curr_f:
            new_f = generate_function_string(curr_f,
                                             cc_functions[curr_f["change_to"]])
            print "INFO: updated:\n   ", generate_function_string(
                curr_f), "-->", new_f
            fout.write(new_f)
            # Jump to next line of current function
            header_l_i = f_range[1] + class_offset + 1
            continue
          if "delete" in curr_f:
            header_l_i = f_range[1] + class_offset + 1
            print "INFO: deleted: \n", generate_function_string(curr_f)
            continue

      # regular write
      fout.write(header_lines[header_l_i])

      # Check "public:"
      if header_l_i == public_pos[0]:
        # write all new function
        for add_i in cc_add:
          new_f = generate_function_string(cc_functions[add_i])
          print "INFO: added: \n", new_f
          fout.write(new_f)

      # i++
      header_l_i += 1

  if DEBUG:
    #os.system("clang-format " + out_file_unformat + ">" + out_file)
    shutil.copy(header_file, header_file + ".before_cpp_refactor.h")
    #os.remove(out_file_unformat)

  if not DEBUG:
    shutil.move(out_file, header_file)


def main():
  if len(sys.argv) <= 1:
    print "Error: need 1 arg as input cc file"
    exit(1)

  pp = pprint.PrettyPrinter(indent=4)
  file_path = sys.argv[1]

  header_functions = []
  header_file = None
  with open(file_path, "r") as fin:
    (google3_dir, dummy) = common.find_google3_path(file_path)
    header_file = google3_dir + "/" + find_header_file(fin)

  header_lines = []
  with open(header_file, "r") as fheader:
    header_lines = fheader.readlines()

  # We only support the first class for now
  (class_name, class_lines,
   class_offset) = cpp_partial_parser.parse_classes(header_lines)[0]
  print "INFO: class name:", class_name
  header_functions = cpp_partial_parser.parse_functions(class_lines)
  if DEBUG:
    print "DEBUG: header functions:"
    pp.pprint(header_functions)

  cc_lines = []
  with open(file_path, "r") as fin:
    cc_lines = fin.readlines()
  # This requires the first "class_name::" is the starting line of cc functions
  # TODO: process namespace to be more accurate
  for i in range(len(cc_lines)):
    if class_name + "::" in cc_lines[i]:
      cc_lines = cc_lines[i:]
      break
  cc_functions = cpp_partial_parser.parse_functions(cc_lines, class_name)
  if DEBUG:
    print "Info cc file function definition:"
    pp.pprint(cc_functions)

  update_header_file(header_file, header_lines, header_functions, cc_functions,
                     class_offset)


if __name__ == "__main__":
  main()

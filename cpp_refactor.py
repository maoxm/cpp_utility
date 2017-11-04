#!/usr/bin/python

import os, glob, subprocess, sys, re, shutil
import common
import cpp_partial_parser
import pprint

TYPES = ["void", "int", "bool", "double", "float"]
RE_MATCH_CLASS = "^class (\S+)(.*){"
DEBUG = False


class FunctionFinder(object):

  def __init__(self, function_types, namespace, is_cc_file):
    self.function_types = function_types
    self.namespace = namespace
    self.is_cc_file = is_cc_file
    self.curr_func = ""
    self.func_default_value = []
    self.state = "wait_for_start"

  def set_namespace(self, namespace):
    self.namespace = namespace

  def is_start(self, line):
    namespace_prefix = ""
    if self.is_cc_file:
      namespace_prefix = self.namespace + "::"
    for ftype in self.function_types:
      m = re.match(r"\s*" + ftype + "\s+" + namespace_prefix + "([^(]+\()",
                   line)
      if m:
        return True
    return False

  # this may also modify self.curr_func
  def is_end(self, line):
    # Put this before the test of ";" to avoid problem on example:
    # void foo() { return; }
    m = re.match(r"(.*){", line)
    if m:
      #print "found ) {"
      self.curr_func += m.group(1)
      return True

    m = re.match(r"(.*);", line)
    if m:
      #print "found );"
      self.curr_func += m.group(1)
      return True
    m = re.match(r"{(.*)", line)
    if m:
      #print "found {"
      return True
    return False

  # 1. remove the function prefix for cc file
  # 2. preserve default value if there is any for header file
  def post_process_fun(self):
    self.curr_func = self.curr_func.strip()
    if self.is_cc_file:
      self.curr_func = re.sub(r"" + self.namespace + "::", r"", self.curr_func)
    else:
      self.func_default_value = re.findall(r"([^ ]+) = ([^,)]+)",
                                           self.curr_func)
      self.curr_func = re.sub(r" = [^,)]+", r"", self.curr_func)

    # speical handle overide, virtual
    term = "virtual"
    if self.curr_func.startswith(term):
      self.func_is_virtual = True
      self.curr_func = (self.curr_func[len(term):]).strip()
    else:
      self.func_is_virtual = False

    term = "override"
    if self.curr_func.endswith(term):
      self.func_is_override = True
      self.curr_func = (self.curr_func[:-len(term)]).strip()
    else:
      self.func_is_override = False

  # return true if successfully got one full function definition
  def accumulate_current_fuction(self, line):
    if self.state == "wait_for_start":
      if self.is_start(line):
        self.state = "wait_for_end"
      else:
        return False

    if self.state == "wait_for_end":
      line = line.strip()
      if self.is_end(line):
        self.state = "wait_for_start"
        self.post_process_fun()
        return True

      self.curr_func += line

      # Next line we will strim heading space, so add space here after comma
      if self.curr_func.endswith(","):
        self.curr_func += " "

      return False
    return False

  def consume_curr_fun(self):
    result = (self.curr_func, self.func_default_value, self.func_is_virtual,
              self.func_is_override)
    self.curr_func = ""
    self.func_default_value = []
    return result

  def in_accumulation(self):
    return self.state == "wait_for_end"


def get_function_name(function_definition):
  m = re.match(r".*\s+([^ (]+)\s*\(.*", function_definition)
  if m:
    return m.group(1)
  print "Error: cannot find function name of", function_definition
  raise


def process_header_file(file_path):
  class_name = None
  ff = FunctionFinder(TYPES, "", False)

  functions = {}
  with open(file_path, "r") as fin:
    for line in fin:
      if class_name is None:
        m = re.match(r"" + RE_MATCH_CLASS, line)
        if m:
          class_name = m.group(1)
          ff.set_namespace(class_name)
        continue
      if ff.accumulate_current_fuction(line):
        result = ff.consume_curr_fun()
        functions[result[0]] = result[1]

  if DEBUG:
    print "Info header file function definition:\n", functions
    print "DEBUG: class name:", class_name

  return [class_name, functions]


def find_header_file(fin):
  while True:
    lc = fin.readline()
    if not lc:
      break
    m = re.match(r'^#include.*"(.*)"', lc)
    if m:
      return m.group(1)


def update_function_in_cc_file_only(fout, cc_functions, header_functions):

  cc_names_dict = get_names_dict(cc_functions)
  header_names_dict = get_names_dict(header_functions)
  for f_def, defaults in cc_functions.iteritems():
    if f_def in header_functions:
      continue

    f_name = get_function_name(f_def)

    # Add conditions:
    # 1. brand new in header
    # 2. has existing in header but the name is not unqiue. If it is, we will
    # replace it later in prossing the private function
    if not f_name in header_names_dict or (
        f_name in header_names_dict and
        not (len(header_names_dict[f_name]) == 1 and
             len(cc_names_dict[f_name]) == 1)):
      print "Info: add: ", f_def
      fout.write(f_def + ";\n\n")


def get_names_dict(functions_dict):
  result = {}
  for f_def, defaults in functions_dict.iteritems():
    f_name = get_function_name(f_def)
    if not f_name in result:
      result[f_name] = []
    result[f_name].append(f_def)
  return result


def update_header_file(file_path, cc_functions, header_functions):
  print "INFO >>>>>>>>>>>> Updating header file"
  out_file = file_path + ".cc_refactor_output.h"
  out_file_unformat = out_file + ".unformat.h"
  cc_names_dict = get_names_dict(cc_functions)
  with open(file_path, "r") as fin:
    with open(out_file_unformat, "w") as fout:
      found_class = False
      found_class_end = False
      ff = FunctionFinder(TYPES, "", False)
      state = ""
      is_public = True
      original_function_lines = ""
      for line in fin:

        if not found_class:
          m = re.match(r"" + RE_MATCH_CLASS, line)
          if m:
            found_class = True
            fout.write(line)
            continue

        if ff.accumulate_current_fuction(line):
          (header_f_def, defaults, is_virtual,
           is_override) = ff.consume_curr_fun()
          original_function_lines += line
          if header_f_def in cc_functions:
            fout.write(original_function_lines)
            original_function_lines = ""
            del cc_functions[header_f_def]
            continue

          # try function name
          f_name = get_function_name(header_f_def)
          if f_name in cc_names_dict and len(cc_names_dict[f_name]) == 1:
            # The function name is unique(no overload)
            # write using cc file's definition and using current default
            cc_f_def = cc_names_dict[f_name][0]
            cc_f_def_with_default = cc_f_def
            if is_virtual:
              cc_f_def_with_default = "virtual " + cc_f_def_with_default
            for each_default in defaults:
              cc_f_def_with_default = re.sub(
                  r"\s+" + each_default[0] + r"([,)])",
                  " " + each_default[0] + " = " + each_default[1] + r"\1",
                  cc_f_def_with_default, 1)
            if is_override:
              cc_f_def_with_default += " override"
            fout.write(cc_f_def_with_default + ";\n\n")
            original_function_lines = ""
            del cc_functions[cc_f_def]
            print "INFO: replace '", header_f_def, "' to '", cc_f_def_with_default, "'"
            continue

          # Didn't find the match, don't write anything, this function is
          # deleted
          print "INFO: Deleted '", header_f_def
          original_function_lines = ""
          continue

        elif ff.in_accumulation():
          original_function_lines += line
          continue

        if is_public:
          m = re.match(r"\s*(private|protected):\s*", line)
          if m:
            is_public = False
            update_function_in_cc_file_only(fout, cc_functions,
                                            header_functions)
        fout.write(line)

  if not DEBUG:
    #os.system("clang-format " + out_file_unformat + ">" + out_file)
    shutil.move(file_path, file_path + ".before_cpp_refactor.h")
    shutil.move(out_file_unformat, file_path)
    #os.remove(out_file_unformat)


def main():
  if len(sys.argv) <= 1:
    print "Error: need 1 arg as input cc file"
    exit(1)

  file_path = sys.argv[1]
  cc_functions = {}
  header_functions = []
  header_file = None
  with open(file_path, "r") as fin:
    (google3_dir, dummy) = common.find_google3_path(file_path)
    header_file = google3_dir + "/" + find_header_file(fin)

  header_lines = []
  with open(header_file, "r") as fheader:
    header_lines = fheader.readlines()

  # We only support the first class for now
  class_info = cpp_partial_parser.parse_classes(header_lines)[0]
  class_name = class_info[0]
  print "INFO: class name:", class_name
  header_functions = cpp_partial_parser.parse_functions(class_info[1])
  pp = pprint.PrettyPrinter(indent=4)
  pp.pprint(header_functions)

  return

  # process reset of cc file
  ff = FunctionFinder(TYPES, class_name, True)
  for line in fin:
    if ff.accumulate_current_fuction(line):
      result = ff.consume_curr_fun()
      cc_functions[result[0]] = result[1]

  if DEBUG:
    print "Info cc file function definition:\n", cc_functions

  update_header_file(header_file, cc_functions, header_functions)


if __name__ == "__main__":
  main()

#!/usr/bin/python
"""A cpp parser that currently parse class name and function def
"""

import re, unittest

COMMON_EXCLUDE_PAIRS = [("{", "}"), ("(", ")"), ("<", ">")]


class Parser(object):

  def __init__(self, lines):
    self.lines = lines
    self.next_i = 0
    self.next_j = 0
    self.comment_i = None

  def set_start_pos(self, i, j):
    self.next_i = i
    self.next_j = j

  def _check_exclude(self, chars, excluding, exclude_pairs):
    for each_exclude_pair in exclude_pairs:
      if chars == each_exclude_pair[0]:
        excluding.append(each_exclude_pair)
        return 1
      if chars == each_exclude_pair[1]:
        # last element in excluding should match
        assert chars == excluding.pop()[1]
        return 2
    return 0

  # Get all string with comments with no space line before the target
  def get_string_until(self, target, exclude_pairs=[]):
    total_len = len(self.lines)
    excluding = list()

    comment_i = None
    for i in range(self.next_i, total_len):
      curr_line = self.lines[i]

      # Handle comments
      if curr_line.strip().startswith("//"):
        if comment_i is None:
          comment_i = i
        continue

      if curr_line.strip() == "":
        comment_i = None

      if i == self.next_i:
        start_j = self.next_j
      else:
        start_j = 0
      for j in range(start_j, len(curr_line)):
        next_j = j + len(target)
        if len(excluding) == 0 and curr_line[j:next_j] == target:
          self.next_i = i
          self.next_j = next_j
          self.comment_i = comment_i
          return [i, j]

        self._check_exclude(curr_line[j], excluding, exclude_pairs)
        if j == len(curr_line) - 1:
          continue
        if self._check_exclude(curr_line[j:j + 2], excluding, [["/*", "*/"]]):
          if comment_i is None:
            comment_i = i

    return None


def parse_classes(lines):
  parser = Parser(lines)
  class_result = []
  while True:
    pos = parser.get_string_until("class")
    if pos is None:
      break
    # try to get class name
    i, j = pos
    line = lines[i].strip()
    m = re.match(r".*class\s+(\S+).*", line)
    assert m is not None
    class_name = m.group(1)

    (start_i, j) = parser.get_string_until("{")
    (end_i, j) = parser.get_string_until("}", COMMON_EXCLUDE_PAIRS)
    class_result.append([class_name, lines[start_i:end_i + 1]])

  return class_result


class FunctionParser(object):

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


# Test for this file
class TestAll(unittest.TestCase):

  def test_parser(self):
    self.assertEqual(
        Parser(["abc\n", "class b {"]).get_string_until("class"), [1, 0])
    self.assertEqual(
        Parser(["//class\n", " class b {"]).get_string_until("class"), [1, 1])
    self.assertEqual(
        Parser(["/* bb\n", " class a {*/\n",
                "class b {"]).get_string_until("class"), [2, 0])
    self.assertEqual(Parser(["abc\n", "bbb\n"]).get_string_until("bcd"), None)

  def test_find_class(self):
    self.assertEqual(
        parse_classes(["class a {\n", " //dummy\n", "};\n"]),
        [["a", ["class a {\n", " //dummy\n", "};\n"]]])
    self.assertEqual(
        parse_classes([
            "class a {\n",
            " //dummy\n",
            "};\n",
            "class b {\n",
            " //dummy\n",
            " void m1() { return; }\n"
            "};\n",
            "Other function\n",
            "void f1() { reutrn ; }\n",
        ]), [["a", ["class a {\n", " //dummy\n", "};\n"]], [
            "b", [
                "class b {\n",
                " //dummy\n",
                " void m1() { return; }\n"
                "};\n",
            ]
        ]])
    print ">>>>>>>>>>>>>>>>><"
    self.assertEqual(
        parse_classes(["class a : b {\n", " //dummy\n", "};\n"]),
        [["a", ["class a : b {\n", " //dummy\n", "};\n"]]])


if __name__ == "__main__":

  unittest.main()

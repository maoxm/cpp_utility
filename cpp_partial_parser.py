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

  def _check_exclude(self, line, index, excluding, exclude_pairs):
    for each_exclude_pair in exclude_pairs:
      chars = line[index:index + len(each_exclude_pair[0])]
      if chars == each_exclude_pair[0]:
        excluding.append(each_exclude_pair)
        return 1
      chars = line[index:index + len(each_exclude_pair[1])]
      if chars == each_exclude_pair[1]:
        # last element in excluding must match
        # For "\n" we need special handle as unlike others, it is not a real
        # pair with "//", every newline will hit here
        if len(excluding) > 0 and excluding[-1][1] == chars:
          excluding.pop()
          return 2
        return 0
    return 0

  # Get all string with comments with no space line before the target
  def find(self, targets, exclude_pairs=[]):
    if isinstance(targets, basestring):
      targets = [targets]
    total_len = len(self.lines)
    excluding = list()

    comment_on = False
    comment_i = None
    comment_exclude_list = [["/*", "*/"], ["//", "\n"]]
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
        if comment_on == False:
          # process only if it is not comment
          for target in targets:
            next_j = j + len(target)
            if len(excluding) == 0 and curr_line[j:next_j] == target:
              self.next_i = i
              self.next_j = next_j
              self.comment_i = comment_i
              return [i, j]

          self._check_exclude(curr_line, j, excluding, exclude_pairs)
          if j == len(curr_line) - 1:
            continue
        result = self._check_exclude(curr_line, j, excluding,
                                     comment_exclude_list)
        if result == 1:
          comment_on = True
          comment_i = i
        elif result == 2:
          comment_on = False

    return None


def parse_classes(lines):
  """Parses all recognized classes in lines

  Returns a list of class_info
  class_info: [class_name, [class_lines]]
  """
  parser = Parser(lines)
  result = []
  while True:
    pos = parser.find("class")
    if pos is None:
      break
    # try to get class name
    i, j = pos
    line = lines[i].strip()
    m = re.match(r".*class\s+(\S+).*", line)
    assert m is not None
    class_name = m.group(1)

    (start_i, start_j) = parser.find("{")
    (end_i, j) = parser.find("}", COMMON_EXCLUDE_PAIRS)
    result_lines = lines[start_i:end_i + 1]
    result_lines[0] = result_lines[0][start_j:]
    result.append([class_name, result_lines])

  return result


# including the starting char, excluding end char
def get_string_from_lines(lines, start_i, start_j, end_i, end_j):
  if start_i > end_i:
    return ""
  if start_i == end_i:
    return lines[start_i][start_j:end_j]
  result = lines[start_i][start_j:]
  for i in range(start_i + 1, end_i + 1):
    if i == end_i:
      result += lines[i][:end_j]
      break
    result += lines[i]
  return result


# return a list of functions as dictionary of following template:
# input: class_name to identify the function in cc file
TEMPLATE = {
    "range": None,  # range of lines [starting index, ending index]
    "name": None,
    "return": "",
    "prefix": "",  # ie. static
    "suffix": "",  # ie. const / override
    "sig": [],  # signatures: [type name, default]
}


def parse_functions(lines, class_name=None):
  parser = Parser(lines)
  result = []

  # corner cases
  if len(lines) == 0:
    return result
  lines[0] = lines[0].strip()
  if lines[0] != "" and lines[0][0] == "{":
    lines[0] = lines[0][1:]

  exclude_pairs = [("{", "}"), ("<", ">")]
  while True:
    pos = parser.find("(", exclude_pairs)
    if pos is None:
      break
    f = dict(TEMPLATE)
    i, j = pos
    line = lines[i][:j].strip()
    words = line.split()
    name = words[-1]

    # filter out funcions in cc file
    if class_name is not None and not name.startswith(class_name + "::"):
      continue

    f["name"] = remove_class_name(name, class_name)
    if len(words) > 1:
      f["return"] = remove_class_name(words[-2], class_name)
      f["prefix"] = remove_class_name(" ".join(words[:-2]), class_name)

    # signatur handle
    pos_sig_end = parser.find(")", COMMON_EXCLUDE_PAIRS)
    assert pos_sig_end is not None
    sig_i, sig_j = pos_sig_end
    sig_string = get_string_from_lines(lines, i, j, sig_i, sig_j + 1)
    sig_string = remove_class_name(sig_string, class_name)
    f["sig"] = parse_sig(sig_string)

    # process between ")" to either ";" or "{"
    pos_def_end = parser.find([";", "{"], COMMON_EXCLUDE_PAIRS)
    assert pos_def_end is not None
    def_i, def_j = pos_def_end
    suffix = get_string_from_lines(lines, sig_i, sig_j + 1, def_i,
                                   def_j).strip()
    f["suffix"] = suffix

    # If it is just declearation, we are done
    if lines[def_i][def_j] == ";":
      f["range"] = [i, def_i]
      result.append(f)
      continue

    # process body in case in header file
    pos_body_end = parser.find("}", COMMON_EXCLUDE_PAIRS)
    if class_name is None:
      # skip this function as it as body in header file
      continue
    body_i, body_j = pos_body_end
    # TODO: not include body for now
    # include the "}"
    # f["body"] = get_string_from_lines(lines, def_i, def_j, body_i, body_j + 1)
    f["range"] = [i, body_i]
    result.append(f)
  return result


def remove_class_name(word, class_name):
  if class_name is None:
    return word
  return re.sub(class_name + "::", "", word)


# return list of params: [type and name, default]
def parse_sig(sig_string):
  # Remove the "("
  sig_string = sig_string.strip()[1:]
  # only one line
  parser = Parser([sig_string])
  result = []
  last_j = 0
  while True:
    pos = parser.find([",", ")"], COMMON_EXCLUDE_PAIRS)
    if pos is None:
      break
    i, j = pos
    assert i == 0
    one_sig = sig_string[last_j:j].strip()
    if one_sig == "":
      # No more parameters
      return result
    equal_parser = Parser([one_sig])
    equal_pos = equal_parser.find("=", COMMON_EXCLUDE_PAIRS)
    if equal_pos is None:
      result.append([one_sig, None])
    else:
      equal_i, equal_j = equal_pos
      result.append([one_sig[:equal_j].strip(), one_sig[equal_j + 1:].strip()])
    last_j = j + 1
    parser.set_start_pos(i, last_j)
  return result


# Test for this file
class TestAll(unittest.TestCase):

  def test_parser(self):
    self.assertEqual(Parser(["abc\n", "class b {"]).find("class"), [1, 0])
    self.assertEqual(Parser(["//class\n", " class b {"]).find("class"), [1, 1])
    self.assertEqual(
        Parser(["/* bb\n", " class a {*/\n", "class b {"]).find("class"),
        [2, 0])
    self.assertEqual(Parser(["abc\n", "bbb\n"]).find("bcd"), None)

    # comments on same line
    print ">>>>>>>>>>>>>>>>>>>>>>>>>>>>><<<<<<<<<<<<<<<<<<<<<<<"
    self.assertEqual(
        Parser(["int a; // range [1,5)  ok "]).find("b", [["(", ")"]]), None)
    print ">>>>>>>>>>>>>>>>>>>>>>>>>>>>><<<<<<<<<<<<<<<<<<<<<<<"

  def test_find_class(self):
    self.assertEqual(
        parse_classes(["class a {\n", " //dummy\n", "};\n"]),
        [["a", ["{\n", " //dummy\n", "};\n"]]])
    self.assertEqual(
        parse_classes("""class a {
 //dummy
};
class b {
 //dummy
 void m1() { return; }
};
Other function
void f1() { reutrn ; }
""".splitlines(True)),
        [["a", ["{\n", " //dummy\n", "};\n"]],
         ["b", [
             "{\n",
             " //dummy\n",
             " void m1() { return; }\n",
             "};\n",
         ]]])
    self.assertEqual(
        parse_classes(["class a : b {\n", " //dummy\n", "};\n"]),
        [["a", ["{\n", " //dummy\n", "};\n"]]])

  def test_parse_sig(self):
    self.assertEqual(parse_sig("()"), [])
    self.assertEqual(parse_sig("(int a)"), [["int a", None]])
    self.assertEqual(
        parse_sig("(int a, float b)"), [["int a", None], ["float b", None]])
    self.assertEqual(parse_sig("(int a=2)"), [["int a", "2"]])
    self.assertEqual(
        parse_sig("(int a, std::pair<int, int> b = {2,3})"),
        [["int a", None], ["std::pair<int, int> b", "{2,3}"]])

  def test_parse_function(self):
    self.assertEqual(
        parse_functions("""
  void f1();
};""".splitlines(True)), [{
    "range": [1, 1],
    "name": "f1",
    "return": "void",
    "prefix": "",
    "suffix": "",
    "sig": [],
}])

    # Test suffix/ multiline/ leading "{"
    self.assertEqual(
        parse_functions("""{int f1(
                        ) override;""".splitlines(True)), [{
                            "range": [0, 1],
                            "name": "f1",
                            "return": "int",
                            "prefix": "",
                            "suffix": "override",
                            "sig": [],
                        }])

    # Test constructor/destructor
    self.assertEqual(
        parse_functions("""MyC(int a);
                          ~MyC();""".splitlines(True)), [{
                              "range": [0, 0],
                              "name": "MyC",
                              "return": "",
                              "prefix": "",
                              "suffix": "",
                              "sig": [["int a", None]],
                          }, {
                              "range": [1, 1],
                              "name": "~MyC",
                              "return": "",
                              "prefix": "",
                              "suffix": "",
                              "sig": [],
                          }])

    # header file with function body
    self.assertEqual(
        parse_functions("""void f1() {
                        }""".splitlines(True)), [])

    # cc file with no namepspace
    self.assertEqual(
        parse_functions("""void f1() {
                        }""".splitlines(True), "ClassA"), [])

    # cc file
    self.assertEqual(
        parse_functions("""static ClassA::T1 ClassA::f1(ClassA::T2 a) const {
return;
}""".splitlines(True), "ClassA"), [{
    "range": [0, 2],
    "name": "f1",
    "return": "T1",
    "prefix": "static",
    "suffix": "const",
    "sig": [["T2 a", None]],
}])


if __name__ == "__main__":

  unittest.main()

import unittest

from lark import GrammarError, ParseError, UnexpectedCharacters

from fetchai.ledger.parser.etch_parser import EtchParser, Function

CONTRACT_TEXT = """
persistent sharded balance : UInt64;
persistent owner_name : String;

@init
function setup(owner : Address)
  use balance[owner];
  balance.set(owner, 1000000u64);
endfunction

@action
function transfer(from: Address, to: Address, amount: UInt64)

  use balance[from, to, "constant_string", "prefix." + to];

  // Check if the sender has enough balance to proceed
  if (balance.get(from) >= amount)

    // update the account balances
    balance.set(from, balance.get(from) - amount);
    balance.set(to, balance.get(to, 0u64) + amount);
  endif

endfunction

@query
function balance(address: Address) : UInt64
    use balance[address];
    return balance.get(address, 0u64);
endfunction

function sub(val1: UInt64, val2: UInt64) : UInt64
    return val1 - val2;
endfunction
"""

# Function block template - for testing statements that are illegal outside a function
FUNCTION_BLOCK = """function a()
{}
endfunction
"""


class ParserTests(unittest.TestCase):
    def setUp(self) -> None:
        try:
            self.parser = EtchParser(CONTRACT_TEXT)
            self.assertIsNotNone(self.parser.parsed_tree, "Parsed tree missing when code passed")
        except ParseError as e:
            self.fail("Failed to parse contract text: \n" + str(e))

    def test_grammar(self):
        """Check that grammer compiles"""
        # TODO: Grammar is loaded from a file, which may impact unit test performance
        try:
            parser = EtchParser()
            self.assertIsNone(parser.parsed_tree, "Parsed tree present when no code passed")
        except GrammarError as e:
            self.fail("Etch grammar failed to load with: \n" + str(e))

    def test_entry_points(self):
        entry_points = self.parser.entry_points()
        self.assertIn('init', entry_points)
        self.assertIn('action', entry_points)
        self.assertIn('query', entry_points)

        self.assertEqual(entry_points['init'], ['setup'])
        self.assertEqual(entry_points['action'], ['transfer'])
        self.assertEqual(entry_points['query'], ['balance'])

    def test_globals_declared(self):
        glob_decl = self.parser.globals_declared()
        self.assertEqual(set(glob_decl.keys()), {'balance', 'owner_name'})
        self.assertEqual(glob_decl['balance'].name, 'balance')
        self.assertEqual(glob_decl['balance'].gtype, 'UInt64')
        self.assertEqual(glob_decl['balance'].is_sharded, True)

        self.assertEqual(glob_decl['owner_name'].name, 'owner_name')
        self.assertEqual(glob_decl['owner_name'].gtype, 'String')
        self.assertEqual(glob_decl['owner_name'].is_sharded, False)

    def test_globals_used(self):
        """Test accurate parsing of globals used in entry points"""
        # Test accurate parsing of declared globals
        glob_used = self.parser.globals_used('setup', ['abc'])
        self.assertEqual(len(glob_used), 1)
        self.assertEqual(len(glob_used[0]), 2)
        self.assertEqual(glob_used[0][0], 'balance')
        self.assertEqual(glob_used[0][1].value, 'abc')
        self.assertEqual(glob_used[0][1].name, 'owner')

    def test_global_addresses(self):
        """Test accurate parsing of globals used in entry points"""

        glob_addresses = self.parser.used_globals_to_addresses('transfer', ['abc', 'def', 100])
        self.assertEqual(len(glob_addresses), 4)
        self.assertEqual(glob_addresses[0], 'balance.abc')
        self.assertEqual(glob_addresses[1], 'balance.def')
        self.assertEqual(glob_addresses[2], 'balance.constant_string')
        self.assertEqual(glob_addresses[3], 'balance.prefix.def')

    def test_scope(self):
        """Tests which instructions are allowed at each scope"""
        # Regular instructions are not allowed at global scope
        with self.assertRaises(UnexpectedCharacters):
            self.parser.parse("var a = 5;")

        # Allowed at global scope
        try:
            # Persistent global declaration
            self.parser.parse("persistent sharded balance : UInt64;")
            self.parser.parse("persistent owner : String;")

            # Functions
            self.parser.parse("""function a(owner : String)
            var b = owner;
            endfunction""")

            # Annotated functions
            self.parser.parse("""@action
            function a(owner : String)
            var b = owner;
            endfunction""")

            # Comments
            self.parser.parse("// A comment")
        except UnexpectedCharacters as e:
            self.fail("Etch parsing of top level statement failed: \n" + str(e))

    def test_builtins(self):
        """Tests for correct parsing of all supported builtin types"""
        parser = EtchParser()
        int_types = ['Int' + str(x) for x in [8, 16, 32, 64, 256]]
        uint_types = ['UInt' + str(x) for x in [8, 16, 32, 64, 256]]

        float_types = ['Float' + str(x) for x in [32, 64]]
        fixed_types = ['Fixed' + str(x) for x in [32, 64]]

        # Test declaration of numerical types
        for t in int_types + uint_types + float_types + fixed_types:
            tree = self.parser.parse(FUNCTION_BLOCK.format("var a : {};".format(t)))
            tree = next(tree.find_data("instruction"))
            self.assertEqual(tree.children[0].data, 'declaration')
            self.assertEqual(tree.children[0].children[1].type, 'TYPE')
            self.assertEqual(tree.children[0].children[1].value, t)

        # Test declaration of other types
        other_types = ['Boolean', 'String']
        for t in other_types:
            tree = self.parser.parse(FUNCTION_BLOCK.format("var a : {};".format(t)))
            tree = next(tree.find_data("instruction"))
            self.assertEqual(tree.children[0].data, 'declaration')
            self.assertEqual(tree.children[0].children[1].type, 'TYPE')
            self.assertEqual(tree.children[0].children[1].value, t)

        # TODO: Test these in a meaningful way, beyond simply that they parse
        # Test declaration of array
        tree = self.parser.parse(FUNCTION_BLOCK.format("var myArray = Array<Int32>(5);"))
        # Test assignment to array
        tree = self.parser.parse(FUNCTION_BLOCK.format("myArray[0] = 5;"))
        # Test assignment from array
        tree = self.parser.parse(FUNCTION_BLOCK.format("b = myArray[0];"))
        tree = self.parser.parse(FUNCTION_BLOCK.format("var b = myArray[0];"))

        # As above, for map type
        # tree = self.parser.parse(FUNCTION_BLOCK.format("var myArray = Map<String. Int32>(5);"))
        # # Test assignment to array
        # tree = self.parser.parse(FUNCTION_BLOCK.format("myArray['test'] = 5;"))
        # # Test assignment from array
        # tree = self.parser.parse(FUNCTION_BLOCK.format("b = myArray['test'];"))
        # tree = self.parser.parse(FUNCTION_BLOCK.format("var b = myArray['test'];"))

    def test_inline(self):
        """Tests for correct parsing of inline type annotations"""

    def test_template(self):
        """Tests for correct parsing of template variables"""
        tree = self.parser.parse(FUNCTION_BLOCK.format("a = State<UInt64>();"))
        tree.expand_kids_by_index(0)
        # print(next(tree.find_data('code_block')))

    def test_functions(self):
        """Tests correct detection of non-entry-point functions"""
        self.assertEqual(self.parser.subfunctions(), ['sub'])

    def test_class_function(self):
        """Tests correct ingestion of functions"""
        # Test minimal function
        tree = self.parser.parse("""function init()
        endfunction""")

        func = Function.from_tree(next(tree.find_data('function')))

        self.assertIsNone(func.annotation)
        self.assertIsNone(func.code_block)
        self.assertIsNone(func.return_type)
        self.assertEqual(func.name, 'init')
        self.assertEqual(func.parameters, [])

        # Test Function parsing from_tree
        tree = self.parser.parse("""
        @action
        function a(b : UInt64) : String
        return b;
        endfunction
        """)
        func = Function.from_tree(next(tree.find_data('annotation')))

        self.assertEqual(func.name, 'a')
        self.assertEqual(func.return_type, 'String')
        self.assertEqual(func.annotation, 'action')
        self.assertEqual(func.parameters[0].name, 'b')
        self.assertEqual(func.parameters[0].ptype, 'UInt64')

        # Test all_from_tree
        tree = self.parser.parse("""
        @action
        function a(b : UInt64) : String
        return 'test';
        endfunction
        
        function c(d: UInt64): String
        return 'test2';
        endfunction
        """)

        funcs = Function.all_from_tree(tree)
        self.assertEqual(funcs[0].name, 'a')
        self.assertEqual(funcs[0].return_type, 'String')
        self.assertEqual(funcs[0].annotation, 'action')
        self.assertEqual(funcs[0].parameters[0].name, 'b')
        self.assertEqual(funcs[0].parameters[0].ptype, 'UInt64')

        self.assertEqual(funcs[1].name, 'c')
        self.assertEqual(funcs[1].return_type, 'String')
        self.assertIsNone(funcs[1].annotation)
        self.assertEqual(funcs[1].parameters[0].name, 'd')
        self.assertEqual(funcs[1].parameters[0].ptype, 'UInt64')


if __name__ == '__main__':
    unittest.main()
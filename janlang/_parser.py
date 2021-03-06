import astree as ast
import tokens

class Parser:

    def __init__(self, _tokens):
        self.tokens = _tokens
        self.pos = 0
        self._hard_fail_on_error = False
        self.statement_parse_order = (
            self.parse_function_definition,
            self.parse_return_statement,
            self.parse_if_statement,
            self.parse_while_statement,
            self.parse_continue_statement,
            self.parse_break_statement,
            self.parse_simple_statement,
            self.parse_assign_and_declaration_statement,
        )
        self.atoms = (
            self.parse_name,
            self.parse_string,
            self.parse_int,
            self.parse_float,
        )
        self.comparison_tokens = {
            tokens.Eq: ast.Eq, 
            tokens.NotEq: ast.NotEq, 
            tokens.Gt: ast.Gt, 
            tokens.GtE: ast.GtE, 
            tokens.Lt: ast.Lt, 
            tokens.LtE: ast.LtE, 
        }
        self.binary_tokens_to_ast_nodes = {
            **self.comparison_tokens,
            tokens.Star: ast.Multiply,
            tokens.Plus: ast.Add,
            tokens.Minus: ast.Subtract,
        }

    def parse_module(self):
        tok_length = len(self.tokens)
        body = self.parse_statements()
        root_module = ast.Module(body)
        return root_module

    def parse_statements(self):
        stmts = []
        while True:
            self.expect_greedy(tokens.NL, min_to_pass=0)
            if isinstance(self.peek(), tokens.EOF):
                break
            try:
                result = self.parse_statement()
                if isinstance(result, (list, tuple)):
                    stmts.extend(result)
                else:
                    stmts.append(result)
            except ParseError:
                break
        return stmts

    def parse_statement(self):
        start_pos = self.pos
        for parse_fn in self.statement_parse_order:
            try:
                return parse_fn()
            except ParseError:
                self.pos = start_pos
        self.error()

    def parse_function_definition(self):
        self.expect(tokens.FunctionDef)
        name = self.require(tokens.Name).value
        print(name)
        self.require(tokens.OpenParen)
        params = self.parse_parameters()
        self.require(tokens.CloseParen)
        self.require(tokens.Colon)
        self.require(tokens.NL)
        body = self.parse_block()
    
        return ast.FunctionDefinition(name, params, [], body)

    def parse_assign_and_declaration_statement(self):
        result = []
        decl = self.match(tokens.VariableDeclaration)
        if decl:
            mut = self.match(tokens.Mutable)
            is_mutable = bool(mut)
            name = self.parse_name()
            result.append(ast.VariableDeclaration(name, is_mutable))
        else:
            name = self.parse_name()
        if self.match(tokens.Assign):
            right = self.parse_expression()
            result.append(ast.Assignment(name, right))
        return result

    def parse_if_statement(self):
        self.expect(tokens.If)
        test = self.parse_expression()
        self.require(tokens.Colon)
        self.require(tokens.NL)
        body = self.parse_block()
        return ast.IfStatement(test, [], body)

    def parse_while_statement(self):
        self.expect(tokens.While)
        test = self.parse_expression()
        self.require(tokens.Colon)
        self.require(tokens.NL)
        body = self.parse_block()
        return ast.WhileStatement(test, body)

    def parse_for_statement(self):
        self.expect(tokens.For)
        name = self.parse_name()
        self.require(tokens.In)
        iter = self.parse_expression()
        self.require(tokens.Colon)
        self.require(tokens.NL)
        body = self.parse_block()
        return ast.ForStatement(name, iter, body)

    def parse_continue_statement(self):
        self.expect(tokens.Continue)
        self.require(tokens.NL)
        return ast.ContinueStatement()

    def parse_break_statement(self):
        self.expect(tokens.Break)
        self.require(tokens.NL)
        return ast.BreakStatement()

    def parse_return_statement(self):
        self.expect(tokens.Return)
        val = self.parse_expression()
        self.require(tokens.NL)
        return ast.Return(val)

    def parse_block(self):
        self.expect(tokens.Indent)
        stmts = self.parse_statements()
        if not stmts:
            self.hard_error()
        self.require(tokens.Dedent)
        return stmts
        
    
    def parse_operations(self, next_parse_fn, operator_tokens):
        operands = []
        operators = []
        while True:
            try:
                if len(operands) == len(operators):
                    node = next_parse_fn()
                    add_list = operands
                else:
                    tok = self.expect(operator_tokens)
                    node = self.binary_tokens_to_ast_nodes[type(tok)]()
                    add_list = operators
            except ParseError as e:
                if not operands:
                    raise e
                break
            else:
                add_list.append(node)
        assert not operands or len(operands) - 1 == len(operators)
        return operands, operators

    def binop_tree(self, next_parse_fn, operator_tokens):
        operands, operators = self.parse_operations(next_parse_fn, operator_tokens)
        left = operands[0]
        for i, op in enumerate(operators, start=1):
            right = operands[i]
            left = ast.BinOp(left, op, right)
        return left

    def parse_simple_statement(self):
        result = self.parse_expression()
        self.expect(tokens.NL)
        return result
        
    def parse_expression(self):
        return self.parse_compare()

    def parse_compare(self):
        op_tokens = tuple(self.comparison_tokens)
        (left, *comparators), operators = self.parse_operations(self.parse_additive, op_tokens)
        if not comparators:
            return left
        return ast.Compare(left, operators, comparators)

    def parse_additive(self):
        op_tokens = (tokens.Plus, tokens.Minus)
        return self.binop_tree(self.parse_multiplicative, op_tokens)

    def parse_multiplicative(self):
        op_tokens = (tokens.Star, tokens.Slash)
        return self.binop_tree(self.parse_atom, op_tokens)

    def parse_atom(self):
        start_pos = self.pos
        node = None
        for fn in self.atoms:
            try:
                node = fn()
            except ParseError:
                self.pos = start_pos
            else:
                break
        if not node:
            self.error()
        chain_functions = (self.finish_call,)
        while True:
            next_node = self.chain_atom(node, chain_functions)
            if not next_node:
                break
            node = next_node
        return node

    def chain_atom(self, root, chain_functions):
        next_node = None
        start_pos = self.pos
        for fn in chain_functions:
            try:
                next_node = fn(root)
            except ParseError:
                pass
            else:
                break
        if next_node is None:
            self.pos = start_pos
        return next_node

    def finish_call(self, func):
        self.expect(tokens.OpenParen)
        args = self.parse_listvals()
        self.expect(tokens.CloseParen)
        return ast.Call(func, args, {})

    def parse_name(self):
        tok = self.expect(tokens.Name)
        return ast.Name(tok.value)

    def parse_float(self):
        tok = self.expect(tokens.Float)
        return ast.Float(tok.val)

    def parse_int(self):
        tok = self.expect(tokens.Int)
        return ast.Integer(tok.val)

    def parse_string(self):
        tok = self.expect(tokens.String)
        return ast.String(tok.val)

    def parse_parameters(self):
        start = self.pos
        vals = []
        pos = self.pos
        while True:
            try:
                param_name = self.parse_name().value
                vals.append(ast.Parameter(param_name))
                pos = self.pos
                self.expect(tokens.Comma)
                pos = self.pos
            except ParseError:
                break
        self.pos = pos
        return vals
        

    def parse_listvals(self):
        # (expr (',' expr)*)*
        start = self.pos
        vals = []
        pos = self.pos
        while True:
            try:
                vals.append(self.parse_expression())
                pos = self.pos
                self.expect(tokens.Comma)
                pos = self.pos
            except ParseError:
                break
        self.pos = pos
        return vals
        
    def expect_if_not_eof(self, types):
        if not isinstance(self.peek(), tokens.EOF):
            self.expect(types)

    def expect_greedy(self, types, min_to_pass=1):
        count = 0
        while self.match(types):
            count += 1
        if count < min_to_pass:
            self.error()

    def expect(self, types):
        if not isinstance(types, (list, tuple)):
            types = [types]
        next_tok = self.peek()
        for tok_type in types:
            if isinstance(next_tok, tok_type):
                return self.advance()
        self.error()

    def require(self, types):
        try:
            return self.expect(types)
        except ParseError as e:
            raise HardParseError() from e

    def match(self, types):
        try:
            return self.expect(types)
        except ParseError:
            pass

    def advance(self):
        curr = self.tokens[self.pos]
        self.pos += 1
        return curr

    def peek(self):
        try:
            return self.tokens[self.pos]
        except IndexError:
            return

    def _error(self, msg, error_class):
        tok = self.peek()
        error_msg = f'Got an error at token {self.pos}, {tok}'
        if msg:
            error_msg += f'\n{msg}'
        raise error_class(error_msg)

    def error(self, msg=''):
        self._error(msg, ParseError)

    def hard_error(self, msg=''):
        self._error(msg, HardParseError)



class ParseError(Exception):
    pass

class HardParseError(Exception):
    pass

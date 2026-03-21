//! Lightweight DPLL SAT solver — WASM plugin for ZeroClaw's R.A.I.N. Lab.
//!
//! Accepts a JSON-encoded propositional formula in CNF-like human notation,
//! parses it, and returns satisfiability + a witness model (if SAT).

use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};
use std::ffi::{CStr, CString};
use std::os::raw::c_char;

// ---------------------------------------------------------------------------
// Public C ABI
// ---------------------------------------------------------------------------

/// Entry point called by the WASM host.
///
/// Accepts a JSON string: `{"formula": "(A OR B) AND (NOT A)"}`.
/// Returns a JSON string with the result or an error message.
#[no_mangle]
pub extern "C" fn verify_logic(input_ptr: *const c_char) -> *mut c_char {
    let input = unsafe {
        if input_ptr.is_null() {
            return error_response("null input pointer");
        }
        match CStr::from_ptr(input_ptr).to_str() {
            Ok(s) => s,
            Err(_) => return error_response("invalid UTF-8 in input"),
        }
    };

    let result = run_solver(input);
    match CString::new(result) {
        Ok(c) => c.into_raw(),
        Err(_) => error_response("result contained interior NUL byte"),
    }
}

/// Free a string previously returned by [`verify_logic`].
#[no_mangle]
pub extern "C" fn free_string(ptr: *mut c_char) {
    if !ptr.is_null() {
        unsafe {
            drop(CString::from_raw(ptr));
        }
    }
}

// ---------------------------------------------------------------------------
// JSON schema
// ---------------------------------------------------------------------------

#[derive(Deserialize)]
struct Request {
    formula: String,
}

#[derive(Serialize)]
struct SuccessResponse {
    satisfiable: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    model: Option<HashMap<String, bool>>,
}

#[derive(Serialize)]
struct ErrorResponse {
    error: String,
}

// ---------------------------------------------------------------------------
// Solver orchestration
// ---------------------------------------------------------------------------

fn run_solver(input: &str) -> String {
    let req: Request = match serde_json::from_str(input) {
        Ok(r) => r,
        Err(e) => return json_error(&format!("JSON parse error: {e}")),
    };

    let formula = req.formula.trim();
    if formula.is_empty() {
        return json_error("formula is empty");
    }

    match parse_formula(formula) {
        Ok(cnf) => {
            let vars = collect_vars(&cnf);
            let mut assignment: HashMap<String, bool> = HashMap::new();
            if dpll(&cnf, &vars, &mut assignment) {
                json_ok(true, Some(assignment))
            } else {
                json_ok(false, None)
            }
        }
        Err(e) => json_error(&format!("parse error: {e}")),
    }
}

// ---------------------------------------------------------------------------
// Formula parser
// ---------------------------------------------------------------------------
// Accepted grammar (case-insensitive operators):
//   formula  = clause (AND clause)*
//   clause   = '(' literal (OR literal)* ')'  |  literal
//   literal  = 'NOT'? VARIABLE
//   VARIABLE = [A-Za-z_][A-Za-z0-9_]*

/// A literal: variable name + polarity.
#[derive(Clone, Debug)]
struct Literal {
    var: String,
    negated: bool,
}

/// A clause is a disjunction of literals.
type Clause = Vec<Literal>;

/// CNF formula = conjunction of clauses.
type Cnf = Vec<Clause>;

fn parse_formula(input: &str) -> Result<Cnf, String> {
    let tokens = tokenize(input)?;
    parse_cnf(&tokens)
}

#[derive(Debug, Clone, PartialEq)]
enum Token {
    LParen,
    RParen,
    And,
    Or,
    Not,
    Var(String),
}

fn tokenize(input: &str) -> Result<Vec<Token>, String> {
    let mut tokens = Vec::new();
    let chars: Vec<char> = input.chars().collect();
    let mut i = 0;
    while i < chars.len() {
        match chars[i] {
            ' ' | '\t' | '\n' | '\r' => i += 1,
            '(' => {
                tokens.push(Token::LParen);
                i += 1;
            }
            ')' => {
                tokens.push(Token::RParen);
                i += 1;
            }
            c if c.is_ascii_alphabetic() || c == '_' => {
                let start = i;
                while i < chars.len() && (chars[i].is_ascii_alphanumeric() || chars[i] == '_') {
                    i += 1;
                }
                let word: String = chars[start..i].iter().collect();
                match word.to_ascii_uppercase().as_str() {
                    "AND" => tokens.push(Token::And),
                    "OR" => tokens.push(Token::Or),
                    "NOT" => tokens.push(Token::Not),
                    _ => tokens.push(Token::Var(word)),
                }
            }
            other => return Err(format!("unexpected character: '{other}'")),
        }
    }
    Ok(tokens)
}

fn parse_cnf(tokens: &[Token]) -> Result<Cnf, String> {
    let mut clauses: Cnf = Vec::new();
    let mut pos = 0;

    let (clause, next) = parse_clause(tokens, pos)?;
    clauses.push(clause);
    pos = next;

    while pos < tokens.len() {
        if tokens[pos] == Token::And {
            pos += 1;
            let (clause, next) = parse_clause(tokens, pos)?;
            clauses.push(clause);
            pos = next;
        } else {
            return Err(format!("expected AND or end, got {:?}", tokens[pos]));
        }
    }

    Ok(clauses)
}

fn parse_clause(tokens: &[Token], pos: usize) -> Result<(Clause, usize), String> {
    if pos >= tokens.len() {
        return Err("unexpected end of formula".into());
    }

    if tokens[pos] == Token::LParen {
        // Parenthesized clause: (lit OR lit OR ...)
        let mut lits = Vec::new();
        let mut p = pos + 1;

        let (lit, next) = parse_literal(tokens, p)?;
        lits.push(lit);
        p = next;

        while p < tokens.len() && tokens[p] == Token::Or {
            p += 1;
            let (lit, next) = parse_literal(tokens, p)?;
            lits.push(lit);
            p = next;
        }

        if p >= tokens.len() || tokens[p] != Token::RParen {
            return Err("expected closing ')'".into());
        }
        Ok((lits, p + 1))
    } else {
        // Bare literal as a unit clause
        let (lit, next) = parse_literal(tokens, pos)?;
        Ok((vec![lit], next))
    }
}

fn parse_literal(tokens: &[Token], pos: usize) -> Result<(Literal, usize), String> {
    if pos >= tokens.len() {
        return Err("expected literal, got end of input".into());
    }
    if tokens[pos] == Token::Not {
        let p = pos + 1;
        if p >= tokens.len() {
            return Err("NOT without variable".into());
        }
        if let Token::Var(name) = &tokens[p] {
            Ok((
                Literal {
                    var: name.clone(),
                    negated: true,
                },
                p + 1,
            ))
        } else {
            Err(format!("expected variable after NOT, got {:?}", tokens[p]))
        }
    } else if let Token::Var(name) = &tokens[pos] {
        Ok((
            Literal {
                var: name.clone(),
                negated: false,
            },
            pos + 1,
        ))
    } else {
        Err(format!("expected literal, got {:?}", tokens[pos]))
    }
}

// ---------------------------------------------------------------------------
// DPLL solver
// ---------------------------------------------------------------------------

fn collect_vars(cnf: &Cnf) -> Vec<String> {
    let mut seen = HashSet::new();
    let mut vars = Vec::new();
    for clause in cnf {
        for lit in clause {
            if seen.insert(lit.var.clone()) {
                vars.push(lit.var.clone());
            }
        }
    }
    vars
}

fn eval_literal(lit: &Literal, assignment: &HashMap<String, bool>) -> Option<bool> {
    assignment.get(&lit.var).map(|&v| if lit.negated { !v } else { v })
}

fn eval_clause(clause: &Clause, assignment: &HashMap<String, bool>) -> Option<bool> {
    let mut has_unassigned = false;
    for lit in clause {
        match eval_literal(lit, assignment) {
            Some(true) => return Some(true),
            Some(false) => {}
            None => has_unassigned = true,
        }
    }
    if has_unassigned {
        None // undetermined
    } else {
        Some(false) // all false
    }
}

/// Unit propagation: find clauses with exactly one unassigned literal
/// (all others false) and force that literal.
fn unit_propagate(cnf: &Cnf, assignment: &mut HashMap<String, bool>) -> bool {
    let mut changed = true;
    while changed {
        changed = false;
        for clause in cnf {
            let mut unassigned_lit: Option<&Literal> = None;
            let mut unassigned_count = 0;
            let mut clause_sat = false;

            for lit in clause {
                match eval_literal(lit, assignment) {
                    Some(true) => {
                        clause_sat = true;
                        break;
                    }
                    Some(false) => {}
                    None => {
                        unassigned_count += 1;
                        unassigned_lit = Some(lit);
                    }
                }
            }

            if clause_sat {
                continue;
            }

            if unassigned_count == 0 {
                // Conflict: clause is all-false
                return false;
            }

            if unassigned_count == 1 {
                let lit = unassigned_lit.unwrap();
                assignment.insert(lit.var.clone(), !lit.negated);
                changed = true;
            }
        }
    }
    true
}

/// Pure literal elimination: if a variable appears with only one polarity
/// in all remaining undetermined clauses, assign it to satisfy those clauses.
fn pure_literal_assign(cnf: &Cnf, assignment: &mut HashMap<String, bool>) {
    let mut polarity: HashMap<&str, (bool, bool)> = HashMap::new(); // (seen_pos, seen_neg)

    for clause in cnf {
        // Skip satisfied clauses
        if let Some(true) = eval_clause(clause, assignment) {
            continue;
        }
        for lit in clause {
            if assignment.contains_key(&lit.var) {
                continue;
            }
            let entry = polarity.entry(&lit.var).or_insert((false, false));
            if lit.negated {
                entry.1 = true;
            } else {
                entry.0 = true;
            }
        }
    }

    for (var, (pos, neg)) in polarity {
        if pos && !neg {
            assignment.insert(var.to_string(), true);
        } else if !pos && neg {
            assignment.insert(var.to_string(), false);
        }
    }
}

fn dpll(cnf: &Cnf, vars: &[String], assignment: &mut HashMap<String, bool>) -> bool {
    // Unit propagation
    if !unit_propagate(cnf, assignment) {
        return false;
    }

    // Pure literal elimination
    pure_literal_assign(cnf, assignment);

    // Check if all clauses are satisfied
    let mut all_sat = true;
    for clause in cnf {
        match eval_clause(clause, assignment) {
            Some(true) => {}
            Some(false) => return false,
            None => {
                all_sat = false;
            }
        }
    }
    if all_sat {
        return true;
    }

    // Pick the first unassigned variable
    let next_var = match vars.iter().find(|v| !assignment.contains_key(*v)) {
        Some(v) => v.clone(),
        None => return false,
    };

    // Branch: try true
    let mut try_true = assignment.clone();
    try_true.insert(next_var.clone(), true);
    if dpll(cnf, vars, &mut try_true) {
        *assignment = try_true;
        return true;
    }

    // Branch: try false
    let mut try_false = assignment.clone();
    try_false.insert(next_var, false);
    if dpll(cnf, vars, &mut try_false) {
        *assignment = try_false;
        return true;
    }

    false
}

// ---------------------------------------------------------------------------
// JSON helpers
// ---------------------------------------------------------------------------

fn json_ok(sat: bool, model: Option<HashMap<String, bool>>) -> String {
    serde_json::to_string(&SuccessResponse {
        satisfiable: sat,
        model,
    })
    .unwrap_or_else(|_| r#"{"error":"serialization failure"}"#.to_string())
}

fn json_error(msg: &str) -> String {
    serde_json::to_string(&ErrorResponse {
        error: msg.to_string(),
    })
    .unwrap_or_else(|_| r#"{"error":"serialization failure"}"#.to_string())
}

fn error_response(msg: &str) -> *mut c_char {
    let json = json_error(msg);
    CString::new(json)
        .unwrap_or_else(|_| CString::new(r#"{"error":"internal"}"#).unwrap())
        .into_raw()
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sat_simple_or() {
        let result = run_solver(r#"{"formula": "(A OR B)"}"#);
        let v: serde_json::Value = serde_json::from_str(&result).unwrap();
        assert_eq!(v["satisfiable"], true);
    }

    #[test]
    fn sat_with_negation() {
        let result = run_solver(r#"{"formula": "(A OR B) AND (NOT A)"}"#);
        let v: serde_json::Value = serde_json::from_str(&result).unwrap();
        assert_eq!(v["satisfiable"], true);
        assert_eq!(v["model"]["A"], false);
        assert_eq!(v["model"]["B"], true);
    }

    #[test]
    fn unsat_contradiction() {
        let result = run_solver(r#"{"formula": "A AND (NOT A)"}"#);
        let v: serde_json::Value = serde_json::from_str(&result).unwrap();
        assert_eq!(v["satisfiable"], false);
    }

    #[test]
    fn sat_three_vars() {
        let result = run_solver(r#"{"formula": "(A OR B OR C) AND (NOT A OR NOT B) AND (NOT C OR A)"}"#);
        let v: serde_json::Value = serde_json::from_str(&result).unwrap();
        assert_eq!(v["satisfiable"], true);
    }

    #[test]
    fn unsat_pigeonhole_small() {
        // All pairs conflict: (A OR B) AND (NOT A) AND (NOT B)
        let result = run_solver(r#"{"formula": "(A OR B) AND (NOT A) AND (NOT B)"}"#);
        let v: serde_json::Value = serde_json::from_str(&result).unwrap();
        assert_eq!(v["satisfiable"], false);
    }

    #[test]
    fn error_empty_formula() {
        let result = run_solver(r#"{"formula": ""}"#);
        let v: serde_json::Value = serde_json::from_str(&result).unwrap();
        assert!(v["error"].is_string());
    }

    #[test]
    fn error_bad_json() {
        let result = run_solver("not json at all");
        let v: serde_json::Value = serde_json::from_str(&result).unwrap();
        assert!(v["error"].is_string());
    }

    #[test]
    fn bare_literal_clause() {
        let result = run_solver(r#"{"formula": "A AND B"}"#);
        let v: serde_json::Value = serde_json::from_str(&result).unwrap();
        assert_eq!(v["satisfiable"], true);
        assert_eq!(v["model"]["A"], true);
        assert_eq!(v["model"]["B"], true);
    }
}

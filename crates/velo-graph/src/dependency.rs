use rustpython_ast::{self as ast, Stmt};
use rustpython_parser::parse;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DependencyType {
    Hard,
    Soft,
}

#[derive(Debug, Clone)]
pub struct Dependency {
    pub name: String,
    pub dep_type: DependencyType,
}

pub struct DependencyScanner {
    dependencies: Vec<Dependency>,
    in_soft_context: u32,
}

impl Default for DependencyScanner {
    fn default() -> Self {
        Self::new()
    }
}

impl DependencyScanner {
    pub fn new() -> Self {
        Self {
            dependencies: Vec::new(),
            in_soft_context: 0,
        }
    }

    pub fn scan(&mut self, source: &str) -> Vec<Dependency> {
        let ast = match parse(source, rustpython_parser::Mode::Module, "<source>") {
            Ok(ast) => {
                if let ast::Mod::Module(ast::ModModule { body, .. }) = ast {
                    body
                } else {
                    return Vec::new();
                }
            }
            Err(_) => return Vec::new(),
        };

        for stmt in ast {
            self.visit_stmt(&stmt);
        }

        std::mem::take(&mut self.dependencies)
    }

    fn visit_stmt(&mut self, stmt: &Stmt) {
        match stmt {
            Stmt::Import(ast::StmtImport { names, .. }) => {
                for name in names {
                    self.add_dependency(name.name.to_string());
                }
            }
            Stmt::ImportFrom(ast::StmtImportFrom {
                module: Some(module_name),
                ..
            }) => {
                self.add_dependency(module_name.to_string());
            }
            Stmt::FunctionDef(ast::StmtFunctionDef { body, .. })
            | Stmt::AsyncFunctionDef(ast::StmtAsyncFunctionDef { body, .. }) => {
                self.in_soft_context += 1;
                for s in body {
                    self.visit_stmt(s);
                }
                self.in_soft_context -= 1;
            }
            Stmt::ClassDef(ast::StmtClassDef { body, .. }) => {
                self.in_soft_context += 1;
                for s in body {
                    self.visit_stmt(s);
                }
                self.in_soft_context -= 1;
            }
            Stmt::Try(ast::StmtTry {
                body,
                handlers,
                orelse,
                finalbody,
                ..
            }) => {
                self.in_soft_context += 1;
                for s in body {
                    self.visit_stmt(s);
                }
                for h in handlers {
                    match h {
                        ast::ExceptHandler::ExceptHandler(ast::ExceptHandlerExceptHandler {
                            body,
                            ..
                        }) => {
                            for s in body {
                                self.visit_stmt(s);
                            }
                        }
                    }
                }
                for s in orelse {
                    self.visit_stmt(s);
                }
                for s in finalbody {
                    self.visit_stmt(s);
                }
                self.in_soft_context -= 1;
            }
            Stmt::If(ast::StmtIf { body, orelse, .. }) => {
                self.in_soft_context += 1;
                for s in body {
                    self.visit_stmt(s);
                }
                for s in orelse {
                    self.visit_stmt(s);
                }
                self.in_soft_context -= 1;
            }
            _ => {}
        }
    }

    fn add_dependency(&mut self, name: String) {
        let dep_type = if self.in_soft_context > 0 {
            DependencyType::Soft
        } else {
            DependencyType::Hard
        };
        self.dependencies.push(Dependency { name, dep_type });
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_hard_dependency() {
        let source = "import os\nfrom math import sin";
        let mut scanner = DependencyScanner::new();
        let deps = scanner.scan(source);
        assert_eq!(deps.len(), 2);
        assert_eq!(deps[0].name, "os");
        assert_eq!(deps[0].dep_type, DependencyType::Hard);
        assert_eq!(deps[1].name, "math");
        assert_eq!(deps[1].dep_type, DependencyType::Hard);
    }

    #[test]
    fn test_soft_dependency_in_func() {
        let source = "def foo():\n    import sys";
        let mut scanner = DependencyScanner::new();
        let deps = scanner.scan(source);
        assert_eq!(deps.len(), 1);
        assert_eq!(deps[0].name, "sys");
        assert_eq!(deps[0].dep_type, DependencyType::Soft);
    }

    #[test]
    fn test_type_checking_dependency() {
        let source = "if TYPE_CHECKING:\n    import typing_extensions";
        let mut scanner = DependencyScanner::new();
        let deps = scanner.scan(source);
        assert_eq!(deps.len(), 1);
        assert_eq!(deps[0].name, "typing_extensions");
        assert_eq!(deps[0].dep_type, DependencyType::Soft);
    }

    #[test]
    fn test_multiple_imports_one_line() {
        let source = "import os, sys, json";
        let mut scanner = DependencyScanner::new();
        let deps = scanner.scan(source);
        assert_eq!(deps.len(), 3);
        assert_eq!(deps[0].name, "os");
        assert_eq!(deps[1].name, "sys");
        assert_eq!(deps[2].name, "json");
    }

    #[test]
    fn test_relative_import_scanner() {
        // from . import foo -> module is None, level is 1
        // For now scanner extracts nothing if module is None,
        // which matches current implementation.
        let source = "from . import foo";
        let mut scanner = DependencyScanner::new();
        let deps = scanner.scan(source);
        assert_eq!(deps.len(), 0);
    }

    #[test]
    fn test_combined_l0_1() {
        let source = "import hard_mod\nif False:\n    import soft_if\ntry:\n    import soft_try\nexcept:\n    pass\ndef f():\n    import soft_fn";
        let mut scanner = DependencyScanner::new();
        let deps = scanner.scan(source);

        // Debug output
        for d in &deps {
            println!("{:?}", d);
        }

        assert_eq!(deps.len(), 4);

        // Check hard_mod
        let hard = deps.iter().find(|d| d.name == "hard_mod").unwrap();
        assert_eq!(hard.dep_type, DependencyType::Hard);

        // Check soft_if
        let soft_if = deps.iter().find(|d| d.name == "soft_if").unwrap();
        assert_eq!(
            soft_if.dep_type,
            DependencyType::Soft,
            "soft_if should be Soft"
        );

        // Check soft_try
        let soft_try = deps.iter().find(|d| d.name == "soft_try").unwrap();
        assert_eq!(
            soft_try.dep_type,
            DependencyType::Soft,
            "soft_try should be Soft"
        );

        // Check soft_fn
        let soft_fn = deps.iter().find(|d| d.name == "soft_fn").unwrap();
        assert_eq!(
            soft_fn.dep_type,
            DependencyType::Soft,
            "soft_fn should be Soft"
        );
    }
}
